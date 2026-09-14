"""Content-free local event contracts for System of Record boundaries."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from eylo.events.schema.py_events.base import BaseEvent
from eylo.sor.shared.contracts import (
    SorProfile,
    SorProjectionDisposition,
    SorSourceState,
    SorSyncRunKind,
)

BoundedCount = Annotated[int, Field(ge=0, le=2_147_483_647)]
SafeCode = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


class _SorEvent(BaseEvent):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization_id: UUID


class SorSourceActivatedEvent(_SorEvent):
    event_type: Literal["sor.source.activated"] = "sor.source.activated"
    source_id: UUID
    profile: SorProfile
    vendor_key: str = Field(min_length=1, max_length=64)
    config_revision: int = Field(ge=1, le=2_147_483_647)
    previous_state: SorSourceState


class SorSourceDegradedEvent(_SorEvent):
    event_type: Literal["sor.source.degraded"] = "sor.source.degraded"
    source_id: UUID
    profile: SorProfile
    vendor_key: str = Field(min_length=1, max_length=64)
    config_revision: int = Field(ge=1, le=2_147_483_647)
    previous_state: SorSourceState
    error_code: SafeCode


class SorSchemaChangedEvent(_SorEvent):
    event_type: Literal["sor.schema.changed"] = "sor.schema.changed"
    source_id: UUID
    previous_schema_revision_id: UUID
    schema_revision_id: UUID
    added_count: BoundedCount
    removed_count: BoundedCount
    renamed_count: BoundedCount
    type_changed_count: BoundedCount


class SorMappingPublishedEvent(_SorEvent):
    event_type: Literal["sor.mapping.published"] = "sor.mapping.published"
    source_id: UUID
    mapping_revision_id: UUID
    mapping_revision: int = Field(ge=1, le=2_147_483_647)


class SorRecordProjectedEvent(_SorEvent):
    event_type: Literal["sor.record.projected"] = "sor.record.projected"
    source_id: UUID
    record_id: UUID
    profile: SorProfile
    entity: str = Field(min_length=1, max_length=128)
    disposition: SorProjectionDisposition
    sync_run_id: UUID | None = None


class SorRecordsTombstonedEvent(_SorEvent):
    event_type: Literal["sor.record.tombstoned"] = "sor.record.tombstoned"
    source_id: UUID
    stream_id: UUID
    sync_run_id: UUID | None = None
    record_ids: tuple[UUID, ...] = Field(min_length=1, max_length=200)


class SorSyncCompletedEvent(_SorEvent):
    event_type: Literal["sor.sync.completed"] = "sor.sync.completed"
    source_id: UUID
    stream_id: UUID
    sync_run_id: UUID
    kind: SorSyncRunKind
    records_added: BoundedCount
    records_updated: BoundedCount
    records_tombstoned: BoundedCount
    records_unchanged: BoundedCount
    records_rejected: BoundedCount


SorPostCommitEvent = (
    SorSourceActivatedEvent
    | SorSourceDegradedEvent
    | SorSchemaChangedEvent
    | SorMappingPublishedEvent
    | SorRecordProjectedEvent
    | SorRecordsTombstonedEvent
    | SorSyncCompletedEvent
)


__all__ = [
    "SorMappingPublishedEvent",
    "SorPostCommitEvent",
    "SorRecordProjectedEvent",
    "SorRecordsTombstonedEvent",
    "SorSchemaChangedEvent",
    "SorSourceActivatedEvent",
    "SorSourceDegradedEvent",
    "SorSyncCompletedEvent",
]
