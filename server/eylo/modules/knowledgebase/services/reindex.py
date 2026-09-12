"""Atomic product state for staged knowledgebase vector reindexing."""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy import text as sql
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.absurd_work import (
    AbsurdBoundWorkService,
    DurableFailureRecovery,
    DurableState,
    DurableWorkLock,
)
from eylo.common.contracts.embedding import (
    EmbeddingError,
    EmbeddingSpace,
    embedding_space_from_record,
    target_embedding_space_from_record,
)
from eylo.durable_runtime import DURABLE_MAX_ATTEMPTS
from eylo.events.schema.py_events.knowledgebase import KnowledgeReindexTransition
from eylo.modules.embedding_configs.domain import InvalidEmbeddingConfig
from eylo.modules.knowledgebase.events import register_reindex_lifecycle
from eylo.modules.knowledgebase.jobs import (
    KnowledgeIngestionJobModel,
    KnowledgeReindexJobModel,
)
from eylo.modules.knowledgebase.models import KnowledgeChunkModel, KnowledgebaseModel
from eylo.modules.knowledgebase.reindex import KnowledgeReindexState
from eylo.modules.knowledgebase.services.knowledgebases import (
    KnowledgebaseError,
    KnowledgebaseNotFound,
)
from eylo.modules.knowledgebase.vendors import KnowledgeVendor
from eylo.modules.provider_configs.errors import NotConfiguredError

REINDEX_BATCH_SIZE = 64


class ReindexChunk(BaseModel):
    """Validated source chunk captured before external embedding work."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        from_attributes=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    id: UUID
    content: str = Field(repr=False)


def _safe_failure_summary(error: Exception) -> str:
    """Return bounded operator detail without persisting provider exceptions."""
    if isinstance(error, (InvalidEmbeddingConfig, NotConfiguredError)):
        return "Knowledgebase embedding configuration is unavailable."
    if isinstance(error, EmbeddingError):
        return "Knowledgebase embedding provider could not complete the reindex."
    if isinstance(error, KnowledgebaseError):
        return "Knowledgebase reindex authority is invalid."
    return "Knowledgebase reindex failed."


def _safe_failure_code(error: Exception) -> str:
    if isinstance(error, (InvalidEmbeddingConfig, NotConfiguredError)):
        return "knowledge_embedding_not_configured"
    if isinstance(error, EmbeddingError):
        return "knowledge_embedding_failed"
    if isinstance(error, KnowledgebaseError):
        return "knowledge_reindex_invalid"
    return "knowledge_reindex_failed"


class KnowledgeReindexService:
    """Own the request, staging fence, cutover, and operator projection."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def request(
        self,
        *,
        organization_id: UUID,
        knowledgebase_id: UUID,
        target_space: EmbeddingSpace,
        max_attempts: int = DURABLE_MAX_ATTEMPTS,
    ) -> KnowledgeReindexJobModel:
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            knowledgebase_id,
        )
        if knowledgebase.vendor != KnowledgeVendor.PGVECTOR:
            raise KnowledgebaseError("Only pgvector knowledgebases can be reindexed.")
        if target_space.organization_id != organization_id:
            raise KnowledgebaseError(
                "Embedding config must belong to the knowledgebase organization."
            )
        source_space = embedding_space_from_record(knowledgebase)
        if source_space is None:
            raise KnowledgebaseError("Knowledgebase has no active embedding space.")
        if source_space.is_compatible_with(target_space):
            raise KnowledgebaseError("Selected embedding space is already active.")

        active = await self.session.scalar(
            select(KnowledgeReindexJobModel).where(
                KnowledgeReindexJobModel.organization_id == organization_id,
                KnowledgeReindexJobModel.knowledgebase_id == knowledgebase_id,
                KnowledgeReindexJobModel.state.in_(
                    (DurableState.PENDING, DurableState.RUNNING)
                ),
                KnowledgeReindexJobModel.deleted.is_(False),
            )
        )
        if active is not None:
            active_target = target_embedding_space_from_record(active)
            if active_target is not None and active_target.is_compatible_with(
                target_space
            ):
                return active
            raise KnowledgebaseError(
                "Knowledgebase already has an active reindex to another space."
            )

        previous_target = knowledgebase.target_embedding_space_id
        if previous_target is not None and previous_target != target_space.id:
            await self.session.execute(
                delete(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.organization_id == organization_id,
                    KnowledgeChunkModel.knowledgebase_id == knowledgebase_id,
                    KnowledgeChunkModel.embedding_space_id == previous_target,
                )
            )

        self._stage_target(knowledgebase, target_space)
        job = KnowledgeReindexJobModel(
            organization_id=organization_id,
            knowledgebase_id=knowledgebase_id,
            max_attempts=max_attempts,
        )
        _assign_job_spaces(job, source_space, target_space)
        self.session.add(job)
        await self.session.flush()
        register_reindex_lifecycle(
            job,
            KnowledgeReindexTransition.QUEUED,
            index_state=knowledgebase.reindex_state,
        )
        return job

    async def latest_job(
        self,
        *,
        organization_id: UUID,
        knowledgebase_id: UUID,
    ) -> KnowledgeReindexJobModel | None:
        return await self.session.scalar(
            select(KnowledgeReindexJobModel)
            .where(
                KnowledgeReindexJobModel.organization_id == organization_id,
                KnowledgeReindexJobModel.knowledgebase_id == knowledgebase_id,
                KnowledgeReindexJobModel.deleted.is_(False),
            )
            .order_by(
                KnowledgeReindexJobModel.created_at.desc(),
                KnowledgeReindexJobModel.id.desc(),
            )
            .limit(1)
        )

    async def begin_attempt(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> KnowledgeReindexJobModel:
        job = await AbsurdBoundWorkService(
            KnowledgeReindexJobModel,
            self.session,
        ).begin_attempt(work_id=job_id, organization_id=organization_id)
        if job.state not in {
            DurableState.SUCCEEDED,
            DurableState.FAILED,
            DurableState.CANCELLED,
        }:
            knowledgebase = await self._knowledgebase_for_update(
                organization_id,
                job.knowledgebase_id,
            )
            register_reindex_lifecycle(
                job,
                KnowledgeReindexTransition.ATTEMPT_STARTED,
                index_state=knowledgebase.reindex_state,
            )
        return job

    async def prepare_attempt(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> KnowledgeReindexJobModel:
        job = await AbsurdBoundWorkService(
            KnowledgeReindexJobModel,
            self.session,
        ).get(
            work_id=job_id,
            organization_id=organization_id,
            lock=DurableWorkLock.UPDATE,
        )
        if job.state in {
            DurableState.SUCCEEDED,
            DurableState.FAILED,
            DurableState.CANCELLED,
        }:
            return job
        if job.state is not DurableState.RUNNING:
            raise KnowledgebaseError("Knowledgebase reindex attempt is not running.")
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            job.knowledgebase_id,
        )
        target = target_embedding_space_from_record(knowledgebase)
        job_target = target_embedding_space_from_record(job)
        if (
            target is None
            or job_target is None
            or target.id != job_target.id
            or knowledgebase.embedding_space_id != job.source_embedding_space_id
        ):
            raise KnowledgebaseError("Knowledgebase reindex authority changed.")
        knowledgebase.reindex_state = KnowledgeReindexState.REINDEXING
        knowledgebase.reindex_last_error = None
        await self.session.flush()
        return job

    async def next_batch(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        limit: int = REINDEX_BATCH_SIZE,
    ) -> list[ReindexChunk]:
        job = await self._running_job(organization_id, job_id)
        rows = await self.session.execute(
            sql(
                """
                SELECT source.id, source.content
                FROM knowledge_chunks AS source
                WHERE source.organization_id = :organization_id
                  AND source.knowledgebase_id = :knowledgebase_id
                  AND source.embedding_space_id = :source_space_id
                  AND source.deleted IS FALSE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM knowledge_chunks AS target
                      WHERE target.organization_id = source.organization_id
                        AND target.knowledgebase_id = source.knowledgebase_id
                        AND target.embedding_space_id = :target_space_id
                        AND target.reindex_source_chunk_id = source.id
                        AND target.deleted IS FALSE
                  )
                ORDER BY source.id
                LIMIT :limit
                """
            ),
            {
                "organization_id": organization_id,
                "knowledgebase_id": job.knowledgebase_id,
                "source_space_id": job.source_embedding_space_id,
                "target_space_id": job.target_embedding_space_id,
                "limit": limit,
            },
        )
        return [ReindexChunk.model_validate(row) for row in rows]

    async def store_vectors(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        chunks: Sequence[ReindexChunk],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        if len(chunks) != len(vectors):
            raise KnowledgebaseError("Reindex embedding returned a partial batch.")
        chunks = tuple(ReindexChunk.model_validate(chunk) for chunk in chunks)
        job = await self._running_job(organization_id, job_id)
        if any(len(vector) != job.target_embedding_dimensions for vector in vectors):
            raise KnowledgebaseError("Reindex embedding dimensions are invalid.")
        stored = 0
        for chunk, vector in zip(chunks, vectors, strict=True):
            result = await self.session.execute(
                sql(
                    """
                    INSERT INTO knowledge_chunks
                        (id, organization_id, knowledgebase_id, document_id,
                         scope, scope_id, position, content, title, source_uri,
                         meta, embedding, embedding_space_id,
                         reindex_source_chunk_id, deleted, created_at, updated_at)
                    SELECT gen_random_uuid(), source.organization_id,
                           source.knowledgebase_id, source.document_id,
                           source.scope, source.scope_id, source.position,
                           source.content, source.title, source.source_uri,
                           source.meta, CAST(:embedding AS vector),
                           :target_space_id, source.id, false, now(), now()
                    FROM knowledge_chunks AS source
                    WHERE source.id = :source_chunk_id
                      AND source.organization_id = :organization_id
                      AND source.knowledgebase_id = :knowledgebase_id
                      AND source.embedding_space_id = :source_space_id
                      AND source.deleted IS FALSE
                    ON CONFLICT
                        (knowledgebase_id, document_id, position, embedding_space_id)
                        WHERE embedding_space_id IS NOT NULL
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        title = EXCLUDED.title,
                        source_uri = EXCLUDED.source_uri,
                        meta = EXCLUDED.meta,
                        embedding = EXCLUDED.embedding,
                        reindex_source_chunk_id = EXCLUDED.reindex_source_chunk_id,
                        deleted = false,
                        updated_at = now()
                    """
                ),
                {
                    "organization_id": organization_id,
                    "knowledgebase_id": job.knowledgebase_id,
                    "source_space_id": job.source_embedding_space_id,
                    "target_space_id": job.target_embedding_space_id,
                    "source_chunk_id": chunk.id,
                    "embedding": _vector(vector),
                },
            )
            if not isinstance(result, CursorResult) or result.rowcount not in {0, 1}:
                raise KnowledgebaseError("Reindex chunk staging count is invalid.")
            stored += result.rowcount
        await self.session.flush()
        return stored

    async def finalize_if_caught_up(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> bool:
        work = AbsurdBoundWorkService(KnowledgeReindexJobModel, self.session)
        job = await work.get(
            work_id=job_id,
            organization_id=organization_id,
            lock=DurableWorkLock.UPDATE,
        )
        if job.state is DurableState.SUCCEEDED:
            return True
        if job.state is not DurableState.RUNNING:
            raise KnowledgebaseError("Knowledgebase reindex cutover is not running.")
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            job.knowledgebase_id,
        )
        if (
            knowledgebase.embedding_space_id != job.source_embedding_space_id
            or knowledgebase.target_embedding_space_id != job.target_embedding_space_id
        ):
            raise KnowledgebaseError("Knowledgebase reindex fence changed.")

        await self.session.execute(
            delete(KnowledgeChunkModel).where(
                KnowledgeChunkModel.organization_id == organization_id,
                KnowledgeChunkModel.knowledgebase_id == job.knowledgebase_id,
                KnowledgeChunkModel.embedding_space_id == job.target_embedding_space_id,
                KnowledgeChunkModel.reindex_source_chunk_id.is_(None),
            )
        )
        active_ingestions = await self.session.scalar(
            select(func.count())
            .select_from(KnowledgeIngestionJobModel)
            .where(
                KnowledgeIngestionJobModel.organization_id == organization_id,
                KnowledgeIngestionJobModel.knowledgebase_id == job.knowledgebase_id,
                KnowledgeIngestionJobModel.embedding_space_id
                == job.source_embedding_space_id,
                KnowledgeIngestionJobModel.state.in_(
                    (DurableState.PENDING, DurableState.RUNNING)
                ),
                KnowledgeIngestionJobModel.deleted.is_(False),
            )
        )
        missing = await self.session.scalar(
            sql(
                """
                SELECT count(*)
                FROM knowledge_chunks AS source
                WHERE source.organization_id = :organization_id
                  AND source.knowledgebase_id = :knowledgebase_id
                  AND source.embedding_space_id = :source_space_id
                  AND source.deleted IS FALSE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM knowledge_chunks AS target
                      WHERE target.organization_id = source.organization_id
                        AND target.knowledgebase_id = source.knowledgebase_id
                        AND target.embedding_space_id = :target_space_id
                        AND target.reindex_source_chunk_id = source.id
                        AND target.deleted IS FALSE
                  )
                """
            ),
            {
                "organization_id": organization_id,
                "knowledgebase_id": job.knowledgebase_id,
                "source_space_id": job.source_embedding_space_id,
                "target_space_id": job.target_embedding_space_id,
            },
        )
        if active_ingestions or missing:
            return False

        source_count = await self._chunk_count(
            organization_id,
            job.knowledgebase_id,
            job.source_embedding_space_id,
        )
        target_count = await self._chunk_count(
            organization_id,
            job.knowledgebase_id,
            job.target_embedding_space_id,
        )
        if source_count != target_count:
            raise KnowledgebaseError("Reindex target is not a complete source copy.")

        await self.session.execute(
            update(KnowledgeChunkModel)
            .where(
                KnowledgeChunkModel.organization_id == organization_id,
                KnowledgeChunkModel.knowledgebase_id == job.knowledgebase_id,
                KnowledgeChunkModel.embedding_space_id == job.target_embedding_space_id,
            )
            .values(reindex_source_chunk_id=None)
        )
        await self.session.execute(
            delete(KnowledgeChunkModel).where(
                KnowledgeChunkModel.organization_id == organization_id,
                KnowledgeChunkModel.knowledgebase_id == job.knowledgebase_id,
                KnowledgeChunkModel.embedding_space_id == job.source_embedding_space_id,
            )
        )
        self._activate_target(knowledgebase)

        def project_result(row: KnowledgeReindexJobModel) -> None:
            row.source_chunk_count = source_count
            row.indexed_chunk_count = target_count

        completed = await work.succeed(
            work_id=job_id,
            organization_id=organization_id,
            project_result=project_result,
        )
        register_reindex_lifecycle(
            completed,
            KnowledgeReindexTransition.SUCCEEDED,
            index_state=knowledgebase.reindex_state,
        )
        return True

    async def record_failure(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
        error: Exception,
        recovery: DurableFailureRecovery,
    ) -> DurableState:
        work = AbsurdBoundWorkService(KnowledgeReindexJobModel, self.session)
        job = await work.get(
            work_id=job_id,
            organization_id=organization_id,
            lock=DurableWorkLock.UPDATE,
        )
        was_running = job.state is DurableState.RUNNING
        state = await work.fail(
            work_id=job_id,
            organization_id=organization_id,
            error=_safe_failure_summary(error),
            recovery=recovery,
        )
        if not was_running:
            return state
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            job.knowledgebase_id,
        )
        if state is DurableState.FAILED:
            if knowledgebase.target_embedding_space_id == job.target_embedding_space_id:
                knowledgebase.reindex_state = KnowledgeReindexState.FAILED
                knowledgebase.reindex_last_error = job.last_error
                await self.session.flush()
        register_reindex_lifecycle(
            job,
            (
                KnowledgeReindexTransition.RETRY_SCHEDULED
                if state is DurableState.PENDING
                else KnowledgeReindexTransition.FAILED
            ),
            index_state=knowledgebase.reindex_state,
            failure_code=_safe_failure_code(error),
        )
        return state

    async def discard_pending(
        self,
        *,
        organization_id: UUID,
        knowledgebase_id: UUID,
    ) -> KnowledgebaseModel:
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            knowledgebase_id,
        )
        if knowledgebase.reindex_state is KnowledgeReindexState.ACTIVE:
            return knowledgebase
        active_job = await self.session.scalar(
            select(KnowledgeReindexJobModel.id).where(
                KnowledgeReindexJobModel.organization_id == organization_id,
                KnowledgeReindexJobModel.knowledgebase_id == knowledgebase_id,
                KnowledgeReindexJobModel.state.in_(
                    (DurableState.PENDING, DurableState.RUNNING)
                ),
                KnowledgeReindexJobModel.deleted.is_(False),
            )
        )
        if active_job is not None:
            raise KnowledgebaseError(
                "Cancel the active knowledgebase reindex before discarding it."
            )
        target_space_id = knowledgebase.target_embedding_space_id
        latest_job = await self.latest_job(
            organization_id=organization_id,
            knowledgebase_id=knowledgebase_id,
        )
        if target_space_id is not None:
            await self.session.execute(
                delete(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.organization_id == organization_id,
                    KnowledgeChunkModel.knowledgebase_id == knowledgebase_id,
                    KnowledgeChunkModel.embedding_space_id == target_space_id,
                )
            )
        self._clear_target(knowledgebase)
        await self.session.flush()
        if (
            target_space_id is not None
            and latest_job is not None
            and latest_job.target_embedding_space_id == target_space_id
        ):
            register_reindex_lifecycle(
                latest_job,
                KnowledgeReindexTransition.TARGET_DISCARDED,
                index_state=knowledgebase.reindex_state,
            )
        return knowledgebase

    async def cancel(
        self,
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> None:
        work = AbsurdBoundWorkService(KnowledgeReindexJobModel, self.session)
        changed, _task_id = await work.cancel(
            work_id=job_id,
            organization_id=organization_id,
        )
        if not changed:
            return
        job = await work.get(work_id=job_id, organization_id=organization_id)
        knowledgebase = await self._knowledgebase_for_update(
            organization_id,
            job.knowledgebase_id,
        )
        if (
            knowledgebase.embedding_space_id == job.source_embedding_space_id
            and knowledgebase.target_embedding_space_id == job.target_embedding_space_id
        ):
            knowledgebase.reindex_state = KnowledgeReindexState.REQUIRED
            knowledgebase.reindex_last_error = None
            await self.session.flush()
        register_reindex_lifecycle(
            job,
            KnowledgeReindexTransition.CANCELLED,
            index_state=knowledgebase.reindex_state,
        )

    async def _knowledgebase_for_update(
        self,
        organization_id: UUID,
        knowledgebase_id: UUID,
    ) -> KnowledgebaseModel:
        knowledgebase = await self.session.scalar(
            select(KnowledgebaseModel)
            .where(
                KnowledgebaseModel.id == knowledgebase_id,
                KnowledgebaseModel.organization_id == organization_id,
                KnowledgebaseModel.deleted.is_(False),
            )
            .with_for_update()
        )
        if knowledgebase is None:
            raise KnowledgebaseNotFound("Knowledgebase was not found.")
        return knowledgebase

    async def _job(
        self,
        organization_id: UUID,
        job_id: UUID,
    ) -> KnowledgeReindexJobModel:
        return await AbsurdBoundWorkService(
            KnowledgeReindexJobModel,
            self.session,
        ).get(work_id=job_id, organization_id=organization_id)

    async def _running_job(
        self,
        organization_id: UUID,
        job_id: UUID,
    ) -> KnowledgeReindexJobModel:
        job = await self._job(organization_id, job_id)
        if job.state is not DurableState.RUNNING:
            raise KnowledgebaseError("Knowledgebase reindex batch is not running.")
        return job

    async def _chunk_count(
        self,
        organization_id: UUID,
        knowledgebase_id: UUID,
        space_id: str,
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(KnowledgeChunkModel)
                .where(
                    KnowledgeChunkModel.organization_id == organization_id,
                    KnowledgeChunkModel.knowledgebase_id == knowledgebase_id,
                    KnowledgeChunkModel.embedding_space_id == space_id,
                    KnowledgeChunkModel.deleted.is_(False),
                )
            )
            or 0
        )

    @staticmethod
    def _stage_target(
        knowledgebase: KnowledgebaseModel,
        target: EmbeddingSpace,
    ) -> None:
        target = EmbeddingSpace.model_validate(target, strict=True)
        knowledgebase.target_embedding_provider_config_id = target.provider_config_id
        knowledgebase.target_embedding_provider_config_revision = (
            target.provider_config_revision
        )
        knowledgebase.target_embedding_provider = target.provider
        knowledgebase.target_embedding_endpoint = target.endpoint
        knowledgebase.target_embedding_model = target.model
        knowledgebase.target_embedding_dimensions = target.dimensions
        knowledgebase.target_embedding_semantic_options = dict(target.semantic_options)
        knowledgebase.target_embedding_space_id = target.id
        knowledgebase.reindex_state = KnowledgeReindexState.REQUIRED
        knowledgebase.reindex_last_error = None

    @staticmethod
    def _activate_target(knowledgebase: KnowledgebaseModel) -> None:
        target = target_embedding_space_from_record(knowledgebase)
        if target is None:
            raise KnowledgebaseError("Knowledgebase reindex target is missing.")
        knowledgebase.embedding_provider_config_id = target.provider_config_id
        knowledgebase.embedding_provider_config_revision = (
            target.provider_config_revision
        )
        knowledgebase.embedding_provider = target.provider
        knowledgebase.embedding_endpoint = target.endpoint
        knowledgebase.embedding_model = target.model
        knowledgebase.embedding_dimensions = target.dimensions
        knowledgebase.embedding_semantic_options = dict(target.semantic_options)
        knowledgebase.embedding_space_id = target.id
        KnowledgeReindexService._clear_target(knowledgebase)

    @staticmethod
    def _clear_target(knowledgebase: KnowledgebaseModel) -> None:
        knowledgebase.target_embedding_provider_config_id = None
        knowledgebase.target_embedding_provider_config_revision = None
        knowledgebase.target_embedding_provider = None
        knowledgebase.target_embedding_endpoint = None
        knowledgebase.target_embedding_model = None
        knowledgebase.target_embedding_dimensions = None
        knowledgebase.target_embedding_semantic_options = None
        knowledgebase.target_embedding_space_id = None
        knowledgebase.reindex_state = KnowledgeReindexState.ACTIVE
        knowledgebase.reindex_last_error = None


def _assign_job_spaces(
    job: KnowledgeReindexJobModel, source: EmbeddingSpace, target: EmbeddingSpace
) -> None:
    """Validate both authorities before stamping immutable reindex-job fields."""
    source = EmbeddingSpace.model_validate(source, strict=True)
    target = EmbeddingSpace.model_validate(target, strict=True)
    job.source_embedding_provider_config_id = source.provider_config_id
    job.source_embedding_provider_config_revision = source.provider_config_revision
    job.source_embedding_provider = source.provider
    job.source_embedding_endpoint = source.endpoint
    job.source_embedding_model = source.model
    job.source_embedding_dimensions = source.dimensions
    job.source_embedding_semantic_options = source.semantic_options
    job.source_embedding_space_id = source.id
    job.target_embedding_provider_config_id = target.provider_config_id
    job.target_embedding_provider_config_revision = target.provider_config_revision
    job.target_embedding_provider = target.provider
    job.target_embedding_endpoint = target.endpoint
    job.target_embedding_model = target.model
    job.target_embedding_dimensions = target.dimensions
    job.target_embedding_semantic_options = target.semantic_options
    job.target_embedding_space_id = target.id


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
