"""Domain policy for source streams, serialized runs, and committed checkpoints."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry

from .contracts import (
    SorAdapterCapabilityManifest,
    SorChangeStrategy,
    SorProjectionDisposition,
    SorSourceState,
    SorSourceTransition,
    SorStreamState,
    SorSyncRunKind,
    SorWorkState,
)
from .custom_datasets import CUSTOM_DATASET_ENTITY
from .dependencies import selected_stream_dependencies, topological_stream_layers
from .events import register_records_tombstoned, register_sync_completed
from .models import (
    SorRecordModel,
    SorSourceModel,
    SorSourceStreamModel,
    SorSyncGenerationModel,
    SorSyncRunModel,
)
from .relationships import SorRelationshipService
from .repositories import SorRepository
from .services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
    SorProjectionService,
    SorSourceService,
    snapshot_objects,
)


@dataclass(frozen=True, slots=True)
class SorSyncCounts:
    """Bounded counters committed with a sync page or terminal run."""

    added: int = 0
    updated: int = 0
    tombstoned: int = 0
    unchanged: int = 0
    rejected: int = 0

    def __post_init__(self) -> None:
        if min(
            self.added,
            self.updated,
            self.tombstoned,
            self.unchanged,
            self.rejected,
        ) < 0:
            raise ValueError("SOR sync counts cannot be negative.")

    def add(self, other: "SorSyncCounts") -> "SorSyncCounts":
        return SorSyncCounts(
            added=self.added + other.added,
            updated=self.updated + other.updated,
            tombstoned=self.tombstoned + other.tombstoned,
            unchanged=self.unchanged + other.unchanged,
            rejected=self.rejected + other.rejected,
        )

    @classmethod
    def from_dispositions(
        cls,
        dispositions: list[SorProjectionDisposition],
        *,
        rejected: int = 0,
    ) -> "SorSyncCounts":
        return cls(
            added=dispositions.count(SorProjectionDisposition.ADDED),
            updated=dispositions.count(SorProjectionDisposition.UPDATED),
            unchanged=dispositions.count(SorProjectionDisposition.UNCHANGED),
            rejected=rejected,
        )


@dataclass(frozen=True, slots=True)
class SorStreamRunContext:
    """Locked DB state required to commit one fetched page."""

    source: SorSourceModel
    stream: SorSourceStreamModel
    run: SorSyncRunModel


@dataclass(frozen=True, slots=True)
class SorSyncGenerationPlan:
    """One committed source generation plus every ordered stream intent."""

    generation: SorSyncGenerationModel
    runs: tuple[SorSyncRunModel, ...]

    @property
    def ready_run_ids(self) -> tuple[UUID, ...]:
        return tuple(run.id for run in self.runs if run.state is SorWorkState.PENDING)


class SorStreamService:
    """Create explicit streams only for executable profile/vendor capabilities."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.sources = SorSourceService(session, registry=registry)
        self.registry = registry or get_sor_registry()

    async def ensure(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        canonical_entity_kind: str,
        strategy: SorChangeStrategy,
        lookback_seconds: int = 0,
        schedule: str | None = None,
    ) -> SorSourceStreamModel:
        """Create or return one immutable object-to-entity stream identity."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.active_mapping_revision_id is None:
            raise SorConfigurationError("Publish a mapping before creating streams.")
        if source.state is SorSourceState.DISABLED:
            raise SorConfigurationError("Disabled sources cannot create streams.")
        object_key = vendor_object_key.strip()
        entity = canonical_entity_kind.strip()
        if not object_key or len(object_key) > 160:
            raise SorConfigurationError("Stream object key is invalid.")
        if not entity or len(entity) > 96:
            raise SorConfigurationError("Stream canonical entity is invalid.")
        if source.selected_objects and object_key not in set(source.selected_objects):
            raise SorConfigurationError(
                "Stream object is not selected by the source configuration."
            )
        if lookback_seconds < 0:
            raise SorConfigurationError("Stream lookback cannot be negative.")
        if schedule is not None and not 1 <= len(schedule.strip()) <= 128:
            raise SorConfigurationError("Stream schedule is invalid.")

        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        stream_spec = next(
            (candidate for candidate in manifest.streams if candidate.key == object_key),
            None,
        )
        if stream_spec is None:
            await self._require_custom_stream(
                organization_id=organization_id,
                source=source,
                manifest=manifest,
                object_key=object_key,
                entity=entity,
                strategy=strategy,
            )
            depends_on: list[str] = []
            relationship_targets: dict[str, str] = {}
        elif entity != stream_spec.canonical_entity:
            raise SorConfigurationError(
                "Stream canonical entity does not match the adapter contract."
            )
        elif strategy not in stream_spec.change_strategies:
            raise SorConfigurationError(
                "Adapter does not implement that strategy for this stream."
            )
        else:
            depends_on = sorted(stream_spec.depends_on)
            relationship_targets = dict(stream_spec.relationship_targets)

        existing = await self.repository.get_stream_by_object(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=object_key,
            for_update=True,
        )
        if existing is not None:
            if (
                existing.canonical_entity_kind != entity
                or existing.strategy is not strategy
                or existing.lookback_seconds != lookback_seconds
                or existing.schedule != (schedule.strip() if schedule else None)
                or existing.depends_on != depends_on
                or existing.relationship_targets != relationship_targets
            ):
                raise SorConflictError(
                    "The source object already has a different stream contract."
                )
            return existing

        stream = SorSourceStreamModel(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=object_key,
            canonical_entity_kind=entity,
            depends_on=depends_on,
            relationship_targets=relationship_targets,
            strategy=strategy,
            lookback_seconds=lookback_seconds,
            schedule=schedule.strip() if schedule else None,
            state=SorStreamState.ACTIVE,
        )
        self.session.add(stream)
        await self.session.flush()
        return stream

    async def refresh_manifest_contracts(
        self,
        *,
        source: SorSourceModel,
        streams: Sequence[SorSourceStreamModel],
    ) -> None:
        """Converge pre-DAG stream rows to the current code-owned manifest."""
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        specs = {stream.key: stream for stream in manifest.streams}
        changed = False
        for stream in streams:
            spec = specs.get(stream.vendor_object_key)
            depends_on = sorted(spec.depends_on) if spec is not None else []
            targets = dict(spec.relationship_targets) if spec is not None else {}
            if spec is not None and stream.strategy not in spec.change_strategies:
                if len(spec.change_strategies) != 1:
                    raise SorConfigurationError(
                        "SOR stream strategy no longer matches the adapter contract."
                    )
                stream.strategy = next(iter(spec.change_strategies))
                changed = True
            if stream.depends_on != depends_on:
                stream.depends_on = depends_on
                changed = True
            if stream.relationship_targets != targets:
                stream.relationship_targets = targets
                changed = True
        if changed:
            await self.session.flush()

    async def _require_custom_stream(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        manifest: SorAdapterCapabilityManifest,
        object_key: str,
        entity: str,
        strategy: SorChangeStrategy,
    ) -> None:
        """Validate a discovery-approved audit dataset outside static streams."""
        if (
            not manifest.supports_custom_objects
            or entity != CUSTOM_DATASET_ENTITY
            or strategy not in manifest.custom_object_change_strategies
        ):
            raise SorConfigurationError(
                "Adapter does not expose the requested custom-object stream."
            )
        if source.active_schema_revision_id is None:
            raise SorConfigurationError("Discover a source schema before creating streams.")
        schema = await self.repository.get_schema_revision(
            organization_id=organization_id,
            source_id=source.id,
            schema_revision_id=source.active_schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Active source schema no longer exists.")
        discovered = snapshot_objects(schema.schema_snapshot)
        metadata = discovered.get(object_key)
        if metadata is None or not metadata[1]:
            raise SorConfigurationError(
                "Custom-object stream is absent from the active discovery."
            )


class SorSyncRunService:
    """Persist sync intent before spawn and commit each covered page atomically."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.sources = SorSourceService(session)
        self.streams = SorStreamService(session)

    async def create_generation(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        stream_ids: Sequence[UUID],
        kind: SorSyncRunKind,
        max_attempts: int = 3,
    ) -> SorSyncGenerationPlan:
        """Persist one source-level DAG before any root run can be spawned."""
        self._validate_run_request(kind=kind, max_attempts=max_attempts)
        unique_stream_ids = tuple(dict.fromkeys(stream_ids))
        if not unique_stream_ids:
            raise SorConfigurationError("A sync generation requires a source stream.")
        if len(unique_stream_ids) != len(stream_ids):
            raise SorConfigurationError("A sync generation cannot repeat a stream.")

        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        active_generation = await self.repository.get_active_source_sync_generation(
            organization_id=organization_id,
            source_id=source_id,
        )
        if active_generation is not None:
            raise SorConflictError("SOR source already has active synchronization.")
        streams: list[SorSourceStreamModel] = []
        for stream_id in unique_stream_ids:
            stream = await self.repository.get_stream(
                organization_id=organization_id,
                source_id=source_id,
                stream_id=stream_id,
                for_update=True,
            )
            if stream is None:
                raise SorNotFoundError("SOR source stream not found.")
            active = await self.repository.get_active_sync_run(
                organization_id=organization_id,
                stream_id=stream.id,
                for_update=True,
            )
            if active is not None:
                raise SorConflictError(
                    f"Source stream {stream.vendor_object_key} already has active work."
                )
            streams.append(stream)

        mapping_revision_id = source.active_mapping_revision_id
        if mapping_revision_id is None:
            raise SorConfigurationError(
                "SOR source has no published mapping for synchronization."
            )
        await self.streams.refresh_manifest_contracts(source=source, streams=streams)
        for stream in streams:
            self._require_runnable(source=source, stream=stream, kind=kind)
        selected_keys = frozenset(stream.vendor_object_key for stream in streams)
        dependency_graph = selected_stream_dependencies(
            {
                stream.vendor_object_key: frozenset(stream.depends_on)
                for stream in streams
            },
            selected_keys,
        )
        topological_stream_layers(dependency_graph)

        generation = SorSyncGenerationModel(
            organization_id=organization_id,
            source_id=source_id,
            kind=kind,
            state=SorWorkState.PENDING,
        )
        self.session.add(generation)
        await self.session.flush()

        runs: list[SorSyncRunModel] = []
        for stream in streams:
            run = SorSyncRunModel(
                organization_id=organization_id,
                source_id=source_id,
                generation_id=generation.id,
                stream_id=stream.id,
                mapping_revision_id=mapping_revision_id,
                kind=kind,
                state=(
                    SorWorkState.WAITING
                    if dependency_graph[stream.vendor_object_key]
                    else SorWorkState.PENDING
                ),
                max_attempts=max_attempts,
                checkpoint_before=(
                    None
                    if kind
                    in {SorSyncRunKind.BOOTSTRAP, SorSyncRunKind.RECONCILIATION}
                    else stream.checkpoint
                ),
            )
            self.session.add(run)
            runs.append(run)
        await self.session.flush()
        return SorSyncGenerationPlan(generation=generation, runs=tuple(runs))

    async def create_stream_run(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        stream_id: UUID,
        kind: SorSyncRunKind,
        max_attempts: int = 3,
    ) -> tuple[SorSyncRunModel, bool]:
        """Create one serialized stream run or return the already-active run."""
        self._validate_run_request(kind=kind, max_attempts=max_attempts)
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        stream = await self.repository.get_stream(
            organization_id=organization_id,
            source_id=source_id,
            stream_id=stream_id,
            for_update=True,
        )
        if stream is None:
            raise SorNotFoundError("SOR source stream not found.")
        self._require_runnable(source=source, stream=stream, kind=kind)
        active = await self.repository.get_active_sync_run(
            organization_id=organization_id,
            stream_id=stream_id,
            for_update=True,
        )
        if active is not None:
            return active, False
        plan = await self.create_generation(
            organization_id=organization_id,
            source_id=source_id,
            stream_ids=(stream_id,),
            kind=kind,
            max_attempts=max_attempts,
        )
        return plan.runs[0], True

    @staticmethod
    def _validate_run_request(*, kind: SorSyncRunKind, max_attempts: int) -> None:
        if kind not in {
            SorSyncRunKind.BOOTSTRAP,
            SorSyncRunKind.INCREMENTAL,
            SorSyncRunKind.RECONCILIATION,
        }:
            raise SorConfigurationError("This sync run kind is not stream-based.")
        if not 1 <= max_attempts <= 10:
            raise SorConfigurationError("Sync max attempts must be between 1 and 10.")

    async def mark_generation_started(
        self,
        *,
        organization_id: UUID,
        generation_id: UUID,
    ) -> None:
        """Mark source-level orchestration active when its first root begins."""
        generation = await self.repository.get_sync_generation(
            organization_id=organization_id,
            generation_id=generation_id,
            for_update=True,
        )
        if generation is None or generation.state in {
            SorWorkState.SUCCEEDED,
            SorWorkState.FAILED,
            SorWorkState.CANCELLED,
        }:
            return
        generation.state = SorWorkState.RUNNING
        generation.started_at = generation.started_at or datetime.now(timezone.utc)
        await self.session.flush()

    async def advance_generation(
        self,
        *,
        organization_id: UUID,
        generation_id: UUID,
    ) -> tuple[UUID, ...]:
        """Release ready descendants under the source-first lock order."""
        identity = await self.repository.get_sync_generation(
            organization_id=organization_id,
            generation_id=generation_id,
        )
        if identity is None:
            return ()
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=identity.source_id,
            for_update=True,
        )
        generation = await self.repository.get_sync_generation(
            organization_id=organization_id,
            generation_id=generation_id,
            for_update=True,
        )
        if generation is None:
            return ()
        if generation.source_id != source.id:
            raise SorConflictError("SOR sync generation source changed while locking.")
        runs = await self.repository.list_generation_runs(
            organization_id=organization_id,
            generation_id=generation_id,
            for_update=True,
        )
        if not runs:
            raise SorConflictError("SOR sync generation has no stream runs.")
        streams = {
            stream.id: stream
            for stream in await self.repository.list_streams(
                organization_id=organization_id,
                source_id=generation.source_id,
            )
        }
        runs_by_key: dict[str, SorSyncRunModel] = {}
        for run in runs:
            if run.stream_id is None or run.stream_id not in streams:
                raise SorConflictError("SOR sync generation references a missing stream.")
            key = streams[run.stream_id].vendor_object_key
            if key in runs_by_key:
                raise SorConflictError("SOR sync generation repeats a source stream.")
            runs_by_key[key] = run

        now = datetime.now(timezone.utc)
        released: list[UUID] = []
        changed = True
        while changed:
            changed = False
            for key, run in runs_by_key.items():
                if run.state is not SorWorkState.WAITING:
                    continue
                stream = streams[run.stream_id]
                dependencies = [
                    runs_by_key[dependency]
                    for dependency in stream.depends_on
                    if dependency in runs_by_key
                ]
                if any(
                    dependency.state
                    in {SorWorkState.FAILED, SorWorkState.CANCELLED}
                    for dependency in dependencies
                ):
                    run.state = SorWorkState.FAILED
                    run.safe_error_code = "DEPENDENCY_FAILED"
                    run.safe_error_summary = (
                        f"A required stream failed before {key} could run."
                    )
                    run.finished_at = now
                    stream.state = SorStreamState.DEGRADED
                    stream.last_failure_at = now
                    stream.last_error_code = "DEPENDENCY_FAILED"
                    changed = True
                elif all(
                    dependency.state is SorWorkState.SUCCEEDED
                    for dependency in dependencies
                ):
                    run.state = SorWorkState.PENDING
                    released.append(run.id)
                    changed = True

        terminal = {
            SorWorkState.SUCCEEDED,
            SorWorkState.FAILED,
            SorWorkState.CANCELLED,
        }
        if all(run.state in terminal for run in runs):
            failed = any(
                run.state in {SorWorkState.FAILED, SorWorkState.CANCELLED}
                for run in runs
            )
            generation.state = (
                SorWorkState.FAILED if failed else SorWorkState.SUCCEEDED
            )
            generation.finished_at = now
            if failed:
                generation.safe_error_code = "GENERATION_INCOMPLETE"
                generation.safe_error_summary = (
                    "One or more source streams did not synchronize successfully."
                )
            else:
                generation.safe_error_code = None
                generation.safe_error_summary = None
            if generation.kind is SorSyncRunKind.BOOTSTRAP:
                if source.state in {
                    SorSourceState.BOOTSTRAPPING,
                    SorSourceState.DEGRADED,
                }:
                    await self.sources.transition(
                        organization_id=organization_id,
                        source_id=generation.source_id,
                        transition=(
                            SorSourceTransition.BOOTSTRAP_FAILED
                            if failed
                            else SorSourceTransition.BOOTSTRAP_SUCCEEDED
                        ),
                        error_code=("GENERATION_INCOMPLETE" if failed else None),
                        error_summary=(
                            "One or more source streams did not synchronize "
                            "successfully."
                            if failed
                            else None
                        ),
                    )
        else:
            generation.state = SorWorkState.RUNNING
            generation.started_at = generation.started_at or now
            generation.finished_at = None
        generation.updated_at = now
        await self.session.flush()
        return tuple(released)

    async def lock_page_context(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        expected_checkpoint: str | None,
    ) -> SorStreamRunContext:
        """Lock run, stream, and source and reject a stale page commit."""
        context = await self._lock_context(
            organization_id=organization_id,
            run_id=run_id,
            expected_checkpoint=expected_checkpoint,
        )
        if context.run.scan_complete:
            raise SorConflictError("SOR sync scan has already committed its final page.")
        return context

    async def lock_finalization_context(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        expected_checkpoint: str | None,
    ) -> SorStreamRunContext:
        """Lock a fully scanned run before applying terminal source state."""
        context = await self._lock_context(
            organization_id=organization_id,
            run_id=run_id,
            expected_checkpoint=expected_checkpoint,
        )
        if not context.run.scan_complete:
            raise SorConflictError("SOR sync scan has not committed its final page.")
        return context

    async def _lock_context(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        expected_checkpoint: str | None,
    ) -> SorStreamRunContext:
        """Lock source authority before the run and stream write set."""
        identity = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
        )
        if identity is None or identity.stream_id is None:
            raise SorNotFoundError("SOR stream sync run not found.")
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=identity.source_id,
            for_update=True,
        )
        run = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
            for_update=True,
        )
        if (
            run is None
            or run.stream_id is None
            or run.source_id != source.id
        ):
            raise SorNotFoundError("SOR stream sync run not found.")
        if run.state is not SorWorkState.RUNNING:
            raise SorConflictError("SOR sync run is no longer running.")
        stream = await self.repository.get_stream(
            organization_id=organization_id,
            source_id=run.source_id,
            stream_id=run.stream_id,
            for_update=True,
        )
        if stream is None:
            raise SorNotFoundError("SOR source stream not found.")
        self._require_runnable(source=source, stream=stream, kind=run.kind)
        if run.mapping_revision_id != source.active_mapping_revision_id:
            raise SorConflictError(
                "SOR source mapping changed after the sync run was created."
            )
        current_checkpoint = (
            run.checkpoint_after
            if run.kind
            in {SorSyncRunKind.BOOTSTRAP, SorSyncRunKind.RECONCILIATION}
            else stream.checkpoint
        )
        if current_checkpoint != expected_checkpoint:
            raise SorConflictError(
                "SOR stream checkpoint changed before the fetched page committed."
            )
        return SorStreamRunContext(source=source, stream=stream, run=run)

    async def commit_page(
        self,
        *,
        context: SorStreamRunContext,
        checkpoint_after: str | None,
        counts: SorSyncCounts,
        scan_complete: bool,
    ) -> None:
        """Advance the covered checkpoint and counters in the projection transaction."""
        run = context.run
        stream = context.stream
        if run.kind is not SorSyncRunKind.RECONCILIATION:
            stream.checkpoint = checkpoint_after
        run.checkpoint_after = checkpoint_after
        run.scan_complete = scan_complete
        _add_counts(run, counts)
        await self.session.flush()

    async def finish_success(
        self,
        *,
        context: SorStreamRunContext,
        counts: SorSyncCounts,
    ) -> None:
        """Finalize source freshness after all bounded projection work commits."""
        now = datetime.now(timezone.utc)
        _set_counts(context.run, counts)
        _set_counts(context.stream, counts)
        context.stream.last_success_at = now
        context.stream.last_failure_at = None
        context.stream.last_error_code = None
        context.stream.next_due_at = now + timedelta(
            seconds=context.source.required_sync_interval_seconds
        )
        context.stream.state = SorStreamState.ACTIVE
        if context.run.kind is SorSyncRunKind.RECONCILIATION:
            context.source.last_reconciliation_at = now
        if context.run.kind is not SorSyncRunKind.BOOTSTRAP:
            streams = await self.repository.list_streams(
                organization_id=context.source.organization_id,
                source_id=context.source.id,
            )
            degraded = next(
                (
                    stream
                    for stream in streams
                    if stream.state is SorStreamState.DEGRADED
                ),
                None,
            )
            if degraded is None:
                await self.sources.transition(
                    organization_id=context.source.organization_id,
                    source_id=context.source.id,
                    transition=SorSourceTransition.SYNC_SUCCEEDED,
                )
            elif context.source.state is SorSourceState.ACTIVE:
                await self.sources.transition(
                    organization_id=context.source.organization_id,
                    source_id=context.source.id,
                    transition=SorSourceTransition.SYNC_FAILED,
                    error_code=degraded.last_error_code or "STREAM_DEGRADED",
                    error_summary="One or more SOR source streams are degraded.",
                )
        register_sync_completed(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            stream_id=context.stream.id,
            sync_run_id=context.run.id,
            kind=context.run.kind,
            records_added=counts.added,
            records_updated=counts.updated,
            records_tombstoned=counts.tombstoned,
            records_unchanged=counts.unchanged,
            records_rejected=counts.rejected,
        )

    async def tombstone_missing_batch(
        self,
        *,
        context: SorStreamRunContext,
        limit: int,
    ) -> int:
        """Tombstone one restart-safe full-scan batch under current locks."""
        if context.run.kind not in {
            SorSyncRunKind.BOOTSTRAP,
            SorSyncRunKind.RECONCILIATION,
        }:
            return 0
        if context.stream.strategy is not SorChangeStrategy.FULL_RECONCILE:
            return 0
        if isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise ValueError("SOR tombstone batch limit must be between 1 and 1000.")
        scan_started_at = context.run.started_at
        if scan_started_at is None:
            raise SorConfigurationError(
                "A complete source scan cannot tombstone before its run has started."
            )

        result = await self.session.execute(
            select(
                SorRecordModel.id,
                SorRecordModel.canonical_entity_kind,
                SorRecordModel.vendor_object_key,
                SorRecordModel.vendor_external_id,
            )
            .where(
                SorRecordModel.organization_id == context.source.organization_id,
                SorRecordModel.source_id == context.source.id,
                SorRecordModel.vendor_object_key == context.stream.vendor_object_key,
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                SorRecordModel.projected_at <= scan_started_at,
                SorRecordModel.last_successful_sync_run_id.is_distinct_from(
                    context.run.id
                ),
            )
            .order_by(SorRecordModel.id.asc())
            .limit(limit)
            .with_for_update()
        )
        deleted_records = result.all()
        if not deleted_records:
            return 0

        now = datetime.now(timezone.utc)
        record_ids = tuple(row.id for row in deleted_records)
        await self.session.execute(
            update(SorRecordModel)
            .where(SorRecordModel.id.in_(record_ids))
            .values(
                tombstoned_at=now,
                deletion_reason="Missing from complete source scan",
                projected_at=now,
            )
        )
        await SorProjectionService(self.session).tombstone_relations_for_records(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            record_ids=record_ids,
            relation_external_ids=tuple(
                row.vendor_external_id
                for row in deleted_records
                if row.canonical_entity_kind == "relation"
            ),
            tombstoned_at=now,
        )
        relationships = SorRelationshipService(self.session)
        await relationships.tombstone_origin_records(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            record_ids=record_ids,
        )
        for deleted_record in deleted_records:
            await relationships.resolve_for_endpoint(
                organization_id=context.source.organization_id,
                source_id=context.source.id,
                vendor_object_key=deleted_record.vendor_object_key,
                vendor_external_id=deleted_record.vendor_external_id,
            )
        _add_counts(context.run, SorSyncCounts(tombstoned=len(record_ids)))
        register_records_tombstoned(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            stream_id=context.stream.id,
            sync_run_id=context.run.id,
            record_ids=record_ids,
        )
        await self.session.flush()
        return len(record_ids)

    async def mark_failure(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        error_code: str,
        requires_reauthorization: bool,
    ) -> None:
        """Project terminal operational failure without mutating the checkpoint."""
        identity = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
        )
        if identity is None or identity.stream_id is None:
            return
        await self.sources.get(
            organization_id=organization_id,
            source_id=identity.source_id,
            for_update=True,
        )
        run = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
            for_update=True,
        )
        if (
            run is None
            or run.stream_id is None
            or run.source_id != identity.source_id
        ):
            return
        stream = await self.repository.get_stream(
            organization_id=organization_id,
            source_id=run.source_id,
            stream_id=run.stream_id,
            for_update=True,
        )
        if stream is None:
            return
        stream.state = SorStreamState.DEGRADED
        stream.last_failure_at = datetime.now(timezone.utc)
        stream.last_error_code = error_code[:128]
        transition = (
            SorSourceTransition.REAUTHORIZATION_REQUIRED
            if requires_reauthorization
            else (
                SorSourceTransition.BOOTSTRAP_FAILED
                if run.kind is SorSyncRunKind.BOOTSTRAP
                else SorSourceTransition.SYNC_FAILED
            )
        )
        await self.sources.transition(
            organization_id=organization_id,
            source_id=run.source_id,
            transition=transition,
            error_code=error_code,
            error_summary="SOR synchronization failed.",
        )

    @staticmethod
    def _require_runnable(
        *,
        source: SorSourceModel,
        stream: SorSourceStreamModel,
        kind: SorSyncRunKind,
    ) -> None:
        if stream.state not in {SorStreamState.ACTIVE, SorStreamState.DEGRADED}:
            raise SorConfigurationError("SOR source stream is paused.")
        if (
            stream.strategy is SorChangeStrategy.FULL_RECONCILE
            and kind is SorSyncRunKind.INCREMENTAL
        ):
            raise SorConfigurationError(
                "Full-reconcile streams cannot create incremental runs."
            )
        if kind is SorSyncRunKind.BOOTSTRAP:
            allowed = {
                SorSourceState.BOOTSTRAPPING,
                SorSourceState.DEGRADED,
            }
        else:
            allowed = {SorSourceState.ACTIVE, SorSourceState.DEGRADED}
        if source.state not in allowed:
            raise SorConfigurationError(
                f"Source cannot run {kind.value} while {source.state.value}."
            )


def _add_counts(row: SorSourceStreamModel | SorSyncRunModel, counts: SorSyncCounts) -> None:
    row.records_added += counts.added
    row.records_updated += counts.updated
    row.records_tombstoned += counts.tombstoned
    row.records_unchanged += counts.unchanged
    row.records_rejected += counts.rejected


def _set_counts(row: SorSourceStreamModel | SorSyncRunModel, counts: SorSyncCounts) -> None:
    row.records_added = counts.added
    row.records_updated = counts.updated
    row.records_tombstoned = counts.tombstoned
    row.records_unchanged = counts.unchanged
    row.records_rejected = counts.rejected


__all__ = [
    "SorStreamRunContext",
    "SorStreamService",
    "SorSyncCounts",
    "SorSyncRunService",
]
