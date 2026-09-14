"""Absurd workflow for storage-prefix discovery into ingestion jobs."""

from __future__ import annotations

import logging
from uuid import UUID

from absurd_sdk import AsyncTaskContext, CancelledTask
from pydantic import JsonValue, ValidationError

from eylo.absurd_work import (
    AbsurdBoundWorkService,
    DurableFailureRecovery,
    DurableState,
    DurableWorkBindingPending,
    DurableWorkLock,
    spawn_bound_work,
    spawn_unbound_work,
)
from eylo.common.contracts.knowledgebase import KnowledgeScope
from eylo.common.contracts.storage_objects import StoredObject
from eylo.common.database import start_transaction
from eylo.durable_runtime import (
    PlatformDurableRuntime,
    run_with_durable_heartbeat,
)
from eylo.events.schema.py_events.knowledgebase import KnowledgeWorkTransition
from eylo.modules.knowledgebase.events import register_corpus_lifecycle
from eylo.modules.knowledgebase.jobs import (
    MAX_CORPUS_OBJECTS,
    KnowledgeCorpusImportModel,
    storage_authority_from_record,
)
from eylo.modules.knowledgebase.services.corpus import CorpusImportService, screen
from eylo.modules.knowledgebase.services.ingestion import IngestionService
from eylo.modules.knowledgebase.services.knowledgebases import KnowledgebaseService
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.knowledgebase.durable_execution import (
    spawn_knowledge_ingestion,
)
from eylo.pipelines.knowledgebase.lifecycle import notify_cancelled_tasks
from eylo.pipelines.knowledgebase.work_contracts import (
    KnowledgeCorpusFailure,
    KnowledgeCorpusFailureReceipt,
    KnowledgeCorpusParams,
    KnowledgeCorpusReceipt,
)
from eylo.pipelines.storage.runtime import resolve_storage_runtime_for_authority

logger = logging.getLogger(__name__)

KNOWLEDGE_CORPUS_WORKFLOW = "eylo.knowledge.corpus.v1"


def register_knowledge_corpus_workflow(runtime: PlatformDurableRuntime) -> None:
    workflow = KnowledgeCorpusWorkflow()
    runtime.register_task(
        name=KNOWLEDGE_CORPUS_WORKFLOW,
        handler=workflow.execute,
    )


async def spawn_knowledge_corpus(
    *,
    organization_id: UUID,
    import_id: UUID,
) -> UUID:
    return await spawn_bound_work(
        model=KnowledgeCorpusImportModel,
        params=KnowledgeCorpusParams(
            organization_id=organization_id, import_id=import_id
        ),
        workflow_name=KNOWLEDGE_CORPUS_WORKFLOW,
        idempotency_prefix="knowledge-corpus",
    )


async def spawn_unbound_knowledge_corpora(*, limit: int = 100) -> int:
    async def spawn(organization_id: UUID, import_id: UUID) -> UUID:
        return await spawn_knowledge_corpus(
            organization_id=organization_id,
            import_id=import_id,
        )

    spawned, failures = await spawn_unbound_work(
        model=KnowledgeCorpusImportModel,
        spawn=spawn,
        limit=limit,
    )
    for import_id, error in failures:
        logger.error(
            "Could not spawn knowledge corpus id=%s error_type=%s",
            import_id,
            type(error).__name__,
        )
    return spawned


async def cancel_knowledge_corpus(
    *,
    organization_id: UUID,
    knowledgebase_id: UUID,
    import_id: UUID,
) -> bool:
    async with start_transaction() as session:
        cancelled, task_id = await CorpusImportService(session).cancel(
            import_id,
            knowledgebase_id,
            organization_id,
        )
    if cancelled and task_id is not None:
        await notify_cancelled_tasks(
            (task_id,),
            resource_kind="knowledge corpus",
            resource_id=import_id,
        )
    return cancelled


class KnowledgeCorpusWorkflow:
    """List a prefix, then atomically file child jobs and the import result."""

    async def execute(
        self,
        params: object,
        task_context: AsyncTaskContext,
    ) -> dict[str, JsonValue]:
        organization_id, import_id = _parse_params(params)
        try:
            return await self._execute(
                organization_id=organization_id,
                import_id=import_id,
                task_context=task_context,
            )
        except CancelledTask:
            async with start_transaction() as session:
                work = AbsurdBoundWorkService(
                    KnowledgeCorpusImportModel,
                    session,
                )
                record = await work.get(
                    work_id=import_id,
                    organization_id=organization_id,
                    lock=DurableWorkLock.UPDATE,
                )
                changed, _task_id = await work.cancel(
                    work_id=import_id,
                    organization_id=organization_id,
                )
                if changed:
                    register_corpus_lifecycle(
                        record,
                        KnowledgeWorkTransition.CANCELLED,
                    )
            raise

    async def _execute(
        self,
        *,
        organization_id: UUID,
        import_id: UUID,
        task_context: AsyncTaskContext,
    ) -> dict[str, JsonValue]:
        try:
            async with start_transaction() as session:
                record = await AbsurdBoundWorkService(
                    KnowledgeCorpusImportModel,
                    session,
                ).begin_attempt(
                    work_id=import_id,
                    organization_id=organization_id,
                )
                if record.state in {
                    DurableState.SUCCEEDED,
                    DurableState.FAILED,
                    DurableState.CANCELLED,
                }:
                    return _receipt(record)
                register_corpus_lifecycle(
                    record,
                    KnowledgeWorkTransition.ATTEMPT_STARTED,
                )
                knowledgebase = await KnowledgebaseService(session).get(
                    record.knowledgebase_id,
                    organization_id,
                )
                scope = KnowledgeScope(knowledgebase.scope)
                scope_id = knowledgebase.scope_id
                storage_authority = storage_authority_from_record(record)
                prefix = record.prefix
                knowledgebase_id = record.knowledgebase_id
        except DurableWorkBindingPending:
            raise
        except Exception as error:  # noqa: BLE001 - load failure is product state
            return await _handle_failure(
                organization_id=organization_id,
                import_id=import_id,
                error=error,
                recovery=(
                    DurableFailureRecovery.TERMINAL
                    if isinstance(error, NotConfiguredError)
                    else DurableFailureRecovery.RETRY
                ),
            )

        async def list_objects() -> list[StoredObject]:
            async with start_transaction(ro=True) as session:
                storage = await resolve_storage_runtime_for_authority(
                    storage_authority,
                    db=session,
                )
            return await storage.adapter.list_objects(
                prefix,
                limit=MAX_CORPUS_OBJECTS,
            )

        try:
            objects = await run_with_durable_heartbeat(task_context, list_objects)
            screened = screen(objects)
        except Exception as error:  # noqa: BLE001 - listing failure is product state
            return await _handle_failure(
                organization_id=organization_id,
                import_id=import_id,
                error=error,
                recovery=(
                    DurableFailureRecovery.TERMINAL
                    if isinstance(error, NotConfiguredError)
                    else DurableFailureRecovery.RETRY
                ),
            )

        queued_ids: list[UUID] = []
        async with start_transaction() as session:
            work = AbsurdBoundWorkService(KnowledgeCorpusImportModel, session)
            current = await work.get(
                work_id=import_id,
                organization_id=organization_id,
                lock=DurableWorkLock.UPDATE,
            )
            if current.state is not DurableState.RUNNING:
                return _receipt(current)
            ingestion = IngestionService(session)
            for entry in screened.keep:
                job = await ingestion.enqueue_from_storage(
                    organization_id=organization_id,
                    knowledgebase_id=knowledgebase_id,
                    scope=scope,
                    scope_id=scope_id,
                    locator=storage_authority.locate(entry.key),
                    corpus_import_id=import_id,
                )
                if job is not None:
                    queued_ids.append(job.id)
            if current.state is DurableState.RUNNING:

                def project_result(row: KnowledgeCorpusImportModel) -> None:
                    row.discovered_count = len(objects)
                    row.queued_count = len(queued_ids)
                    row.skipped = screened.skipped_summary()

                result = await work.succeed(
                    work_id=import_id,
                    organization_id=organization_id,
                    project_result=project_result,
                )
                register_corpus_lifecycle(
                    result,
                    KnowledgeWorkTransition.SUCCEEDED,
                )
            else:
                result = current

        for job_id in queued_ids:
            try:
                await spawn_knowledge_ingestion(
                    organization_id=organization_id,
                    job_id=job_id,
                )
            except Exception as error:  # noqa: BLE001 - DB outbox retains the job
                logger.error(
                    "Could not immediately spawn ingestion id=%s error_type=%s",
                    job_id,
                    type(error).__name__,
                )
        return _receipt(result)


def _parse_params(params: object) -> tuple[UUID, UUID]:
    try:
        parsed = KnowledgeCorpusParams.model_validate(params)
    except ValidationError as error:
        if any(
            item["type"] in {"missing", "extra_forbidden", "model_type"}
            for item in error.errors(include_input=False)
        ):
            raise ValueError(
                "Knowledge corpus task params must contain IDs only."
            ) from None
        raise ValueError(
            "Knowledge corpus task params contain an invalid UUID."
        ) from None
    return parsed.organization_id, parsed.import_id


async def _handle_failure(
    *,
    organization_id: UUID,
    import_id: UUID,
    error: Exception,
    recovery: DurableFailureRecovery,
) -> dict[str, JsonValue]:
    summary = (
        KnowledgeCorpusFailure.NOT_CONFIGURED
        if isinstance(error, NotConfiguredError)
        else KnowledgeCorpusFailure.IMPORT
    )
    async with start_transaction() as session:
        work = AbsurdBoundWorkService(
            KnowledgeCorpusImportModel,
            session,
        )
        record = await work.get(
            work_id=import_id,
            organization_id=organization_id,
            lock=DurableWorkLock.UPDATE,
        )
        was_running = record.state is DurableState.RUNNING
        state = await work.fail(
            work_id=import_id,
            organization_id=organization_id,
            error=summary,
            recovery=recovery,
        )
        if was_running:
            register_corpus_lifecycle(
                record,
                (
                    KnowledgeWorkTransition.RETRY_SCHEDULED
                    if state is DurableState.PENDING
                    else KnowledgeWorkTransition.FAILED
                ),
                failure_code=summary,
            )
    if state is DurableState.PENDING:
        raise error
    logger.warning("Knowledge corpus failed id=%s code=%s", import_id, summary)
    return KnowledgeCorpusFailureReceipt(import_id=import_id, state=state).to_payload()


def _receipt(record: KnowledgeCorpusImportModel) -> dict[str, JsonValue]:
    return KnowledgeCorpusReceipt(
        organization_id=record.organization_id,
        import_id=record.id,
        state=record.state,
        discovered=record.discovered_count,
        queued=record.queued_count,
    ).to_payload()


__all__ = [
    "KNOWLEDGE_CORPUS_WORKFLOW",
    "KnowledgeCorpusWorkflow",
    "cancel_knowledge_corpus",
    "register_knowledge_corpus_workflow",
    "spawn_knowledge_corpus",
    "spawn_unbound_knowledge_corpora",
]
