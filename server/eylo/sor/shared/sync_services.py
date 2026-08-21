"""Domain policy for source streams, serialized runs, and committed checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import update
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
from .events import register_records_tombstoned, register_sync_completed
from .models import (
    SorRecordModel,
    SorSourceModel,
    SorSourceStreamModel,
    SorSyncRunModel,
)
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
        elif entity != stream_spec.canonical_entity:
            raise SorConfigurationError(
                "Stream canonical entity does not match the adapter contract."
            )
        elif strategy not in stream_spec.change_strategies:
            raise SorConfigurationError(
                "Adapter does not implement that strategy for this stream."
            )

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
            strategy=strategy,
            lookback_seconds=lookback_seconds,
            schedule=schedule.strip() if schedule else None,
            state=SorStreamState.ACTIVE,
        )
        self.session.add(stream)
        await self.session.flush()
        return stream

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
        if kind not in {
            SorSyncRunKind.BOOTSTRAP,
            SorSyncRunKind.INCREMENTAL,
            SorSyncRunKind.RECONCILIATION,
        }:
            raise SorConfigurationError("This sync run kind is not stream-based.")
        if not 1 <= max_attempts <= 10:
            raise SorConfigurationError("Sync max attempts must be between 1 and 10.")
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
        mapping_revision_id = source.active_mapping_revision_id
        if mapping_revision_id is None:
            raise SorConfigurationError(
                "SOR source has no published mapping for synchronization."
            )
        active = await self.repository.get_active_sync_run(
            organization_id=organization_id,
            stream_id=stream_id,
            for_update=True,
        )
        if active is not None:
            return active, False

        run = SorSyncRunModel(
            organization_id=organization_id,
            source_id=source_id,
            stream_id=stream_id,
            mapping_revision_id=mapping_revision_id,
            kind=kind,
            state=SorWorkState.PENDING,
            max_attempts=max_attempts,
            checkpoint_before=(
                None if kind is SorSyncRunKind.RECONCILIATION else stream.checkpoint
            ),
        )
        self.session.add(run)
        await self.session.flush()
        return run, True

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
        """Lock and validate the shared authority for a stream run write."""
        run = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
            for_update=True,
        )
        if run is None or run.stream_id is None:
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
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=run.source_id,
            for_update=True,
        )
        self._require_runnable(source=source, stream=stream, kind=run.kind)
        if run.mapping_revision_id != source.active_mapping_revision_id:
            raise SorConflictError(
                "SOR source mapping changed after the sync run was created."
            )
        current_checkpoint = (
            run.checkpoint_after
            if run.kind is SorSyncRunKind.RECONCILIATION
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
    ) -> int:
        """Finalize source freshness; infer deletions only after a complete scan."""
        now = datetime.now(timezone.utc)
        tombstoned = 0
        tombstoned_record_ids: tuple[UUID, ...] = ()
        if context.run.kind is SorSyncRunKind.RECONCILIATION:
            scan_started_at = context.run.started_at
            if scan_started_at is None:
                raise SorConfigurationError(
                    "A reconciliation cannot finish before its run has started."
                )
            result = await self.session.execute(
                update(SorRecordModel)
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
                .values(
                    tombstoned_at=now,
                    deletion_reason="Missing from complete reconciliation",
                    projected_at=now,
                )
                .returning(
                    SorRecordModel.id,
                    SorRecordModel.canonical_entity_kind,
                    SorRecordModel.vendor_external_id,
                )
            )
            deleted_records = result.all()
            tombstoned = len(deleted_records)
            tombstoned_record_ids = tuple(row.id for row in deleted_records)
            if deleted_records:
                await SorProjectionService(
                    self.session
                ).tombstone_relations_for_records(
                    organization_id=context.source.organization_id,
                    source_id=context.source.id,
                    record_ids=tuple(row.id for row in deleted_records),
                    relation_external_ids=tuple(
                        row.vendor_external_id
                        for row in deleted_records
                        if row.canonical_entity_kind == "relation"
                    ),
                    tombstoned_at=now,
                )
        final = counts.add(SorSyncCounts(tombstoned=tombstoned))
        _set_counts(context.run, final)
        _set_counts(context.stream, final)
        context.stream.last_success_at = now
        context.stream.last_failure_at = None
        context.stream.last_error_code = None
        context.stream.next_due_at = now + timedelta(
            seconds=context.source.required_sync_interval_seconds
        )
        context.stream.state = SorStreamState.ACTIVE
        if context.run.kind is SorSyncRunKind.RECONCILIATION:
            context.source.last_reconciliation_at = now
        if context.run.kind is SorSyncRunKind.BOOTSTRAP:
            streams = await self.repository.list_streams(
                organization_id=context.source.organization_id,
                source_id=context.source.id,
            )
            bootstrap_complete = all(
                stream.state is SorStreamState.PAUSED
                or stream.last_success_at is not None
                for stream in streams
            )
            if bootstrap_complete:
                await self.sources.transition(
                    organization_id=context.source.organization_id,
                    source_id=context.source.id,
                    transition=SorSourceTransition.BOOTSTRAP_SUCCEEDED,
                )
        else:
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
        register_records_tombstoned(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            stream_id=context.stream.id,
            sync_run_id=context.run.id,
            record_ids=tombstoned_record_ids,
        )
        register_sync_completed(
            organization_id=context.source.organization_id,
            source_id=context.source.id,
            stream_id=context.stream.id,
            sync_run_id=context.run.id,
            kind=context.run.kind,
            records_added=final.added,
            records_updated=final.updated,
            records_tombstoned=final.tombstoned,
            records_unchanged=final.unchanged,
            records_rejected=final.rejected,
        )
        return tombstoned

    async def mark_failure(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        error_code: str,
        requires_reauthorization: bool,
    ) -> None:
        """Project terminal operational failure without mutating the checkpoint."""
        run = await self.repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
            for_update=True,
        )
        if run is None or run.stream_id is None:
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
