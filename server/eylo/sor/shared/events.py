"""Best-effort post-commit publication for SOR domain changes."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from eylo.common.database import register_ephemeral_event_post_txn
from eylo.events.schema.py_events.sor import (
    SorMappingPublishedEvent,
    SorPostCommitEvent,
    SorRecordProjectedEvent,
    SorRecordsTombstonedEvent,
    SorSchemaChangedEvent,
    SorSourceActivatedEvent,
    SorSourceDegradedEvent,
    SorSyncCompletedEvent,
)
from eylo.sor.shared.contracts import (
    SorProfile,
    SorProjectionDisposition,
    SorSchemaDifference,
    SorSourceState,
    SorSyncRunKind,
)

logger = logging.getLogger(__name__)
_TOMBSTONE_EVENT_BATCH_SIZE = 200


def register_source_transition(
    *,
    organization_id: UUID,
    source_id: UUID,
    profile: SorProfile,
    vendor_key: str,
    config_revision: int,
    previous_state: SorSourceState,
    current_state: SorSourceState,
    error_code: str | None,
) -> bool:
    """Publish only source transitions promised by the SOR event contract."""
    if previous_state is current_state:
        return False
    if current_state is SorSourceState.ACTIVE:
        event: SorPostCommitEvent = SorSourceActivatedEvent(
            organization_id=organization_id,
            source_id=source_id,
            profile=profile,
            vendor_key=vendor_key,
            config_revision=config_revision,
            previous_state=previous_state,
        )
    elif current_state is SorSourceState.DEGRADED and error_code is not None:
        event = SorSourceDegradedEvent(
            organization_id=organization_id,
            source_id=source_id,
            profile=profile,
            vendor_key=vendor_key,
            config_revision=config_revision,
            previous_state=previous_state,
            error_code=error_code,
        )
    else:
        return False
    return _register(event)


def register_schema_changed(
    *,
    organization_id: UUID,
    source_id: UUID,
    previous_schema_revision_id: UUID,
    schema_revision_id: UUID,
    difference: SorSchemaDifference,
) -> bool:
    if not difference.changed:
        return False
    return _register(
        SorSchemaChangedEvent(
            organization_id=organization_id,
            source_id=source_id,
            previous_schema_revision_id=previous_schema_revision_id,
            schema_revision_id=schema_revision_id,
            added_count=len(difference.added),
            removed_count=len(difference.removed),
            renamed_count=len(difference.renamed),
            type_changed_count=len(difference.type_changed),
        )
    )


def register_mapping_published(
    *,
    organization_id: UUID,
    source_id: UUID,
    mapping_revision_id: UUID,
    mapping_revision: int,
) -> bool:
    return _register(
        SorMappingPublishedEvent(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=mapping_revision_id,
            mapping_revision=mapping_revision,
        )
    )


def register_record_projected(
    *,
    organization_id: UUID,
    source_id: UUID,
    record_id: UUID,
    profile: SorProfile,
    entity: str,
    disposition: SorProjectionDisposition,
    sync_run_id: UUID | None,
) -> bool:
    if disposition is SorProjectionDisposition.UNCHANGED:
        return False
    return _register(
        SorRecordProjectedEvent(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            profile=profile,
            entity=entity,
            disposition=disposition,
            sync_run_id=sync_run_id,
        )
    )


def register_records_tombstoned(
    *,
    organization_id: UUID,
    source_id: UUID,
    stream_id: UUID,
    sync_run_id: UUID | None,
    record_ids: Sequence[UUID],
) -> int:
    """Register bounded batches so large reconciliation cannot exceed event limits."""
    registered = 0
    for offset in range(0, len(record_ids), _TOMBSTONE_EVENT_BATCH_SIZE):
        batch = tuple(record_ids[offset : offset + _TOMBSTONE_EVENT_BATCH_SIZE])
        if batch and _register(
            SorRecordsTombstonedEvent(
                organization_id=organization_id,
                source_id=source_id,
                stream_id=stream_id,
                sync_run_id=sync_run_id,
                record_ids=batch,
            )
        ):
            registered += 1
    return registered


def register_sync_completed(
    *,
    organization_id: UUID,
    source_id: UUID,
    stream_id: UUID,
    sync_run_id: UUID,
    kind: SorSyncRunKind,
    records_added: int,
    records_updated: int,
    records_tombstoned: int,
    records_unchanged: int,
    records_rejected: int,
) -> bool:
    return _register(
        SorSyncCompletedEvent(
            organization_id=organization_id,
            source_id=source_id,
            stream_id=stream_id,
            sync_run_id=sync_run_id,
            kind=kind,
            records_added=records_added,
            records_updated=records_updated,
            records_tombstoned=records_tombstoned,
            records_unchanged=records_unchanged,
            records_rejected=records_rejected,
        )
    )


def _register(event: SorPostCommitEvent) -> bool:
    """Keep local observability outside canonical transaction authority."""
    try:
        register_ephemeral_event_post_txn(event)
    except Exception as error:  # noqa: BLE001 - product commit remains authority
        logger.warning(
            "SOR local event unavailable name=%s error_type=%s",
            type(event).__name__,
            type(error).__name__,
        )
        return False
    return True


__all__ = [
    "register_mapping_published",
    "register_record_projected",
    "register_records_tombstoned",
    "register_schema_changed",
    "register_source_transition",
    "register_sync_completed",
]
