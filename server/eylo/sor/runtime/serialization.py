"""Typed SOR work receipts and explicit durable vendor serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)

from eylo.sor.shared.contracts import (
    SorChangeStrategy,
    SorCommandResult,
    SorExternalRecord,
    SorRecordPage,
    SorSourcePayload,
    SorSyncRunKind,
    SorWebhookReceiptState,
    SorWorkState,
)
from eylo.sor.shared.json_values import SorJsonValue, SorJsonValueError, to_json_value
from eylo.sor.shared.services import SorProjectionError
from eylo.sor.shared.sync_services import SorSyncCounts


def _task_id(value: object) -> UUID:
    """Accept UUID objects internally and UUID strings from durable JSON only."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError("SOR task IDs must be UUID strings or UUID objects.")


TaskId = Annotated[UUID, BeforeValidator(_task_id)]


class SorSyncTaskParams(BaseModel):
    """The only authority allowed in a persisted sync-task request."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: TaskId
    run_id: TaskId


class SorWebhookTaskParams(BaseModel):
    """The only authority allowed in a persisted webhook-task request."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: TaskId
    receipt_id: TaskId


class SorCommandTaskParams(BaseModel):
    """Resolve a committed command; never persist credentials or mutation input."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: TaskId
    command_id: TaskId


class SorSyncWorkReceipt(BaseModel):
    """Exact durable result shape; counters retain their existing flat wire names."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    run_id: UUID
    source_id: UUID
    kind: SorSyncRunKind
    state: SorWorkState
    terminal: bool
    records_added: int = Field(ge=0)
    records_updated: int = Field(ge=0)
    records_tombstoned: int = Field(ge=0)
    records_unchanged: int = Field(ge=0)
    records_rejected: int = Field(ge=0)

    @property
    def counts(self) -> SorSyncCounts:
        return SorSyncCounts(
            added=self.records_added,
            updated=self.records_updated,
            tombstoned=self.records_tombstoned,
            unchanged=self.records_unchanged,
            rejected=self.records_rejected,
        )


class SorSyncAttempt(BaseModel):
    """Detached resume state, never persisted as the public completion receipt."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    receipt: SorSyncWorkReceipt
    stream_id: UUID
    stream_key: str
    strategy: SorChangeStrategy
    cursor_version: int = Field(gt=0)
    checkpoint: str | None = Field(repr=False, exclude=True)
    scan_complete: bool


class SorWebhookWorkReceipt(BaseModel):
    """Retain raw JSON signals even when malformed input caused a terminal result."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    receipt_id: UUID
    source_id: UUID
    state: SorWebhookReceiptState
    signals: list[SorJsonValue] = Field(repr=False)
    terminal: bool


def _aware_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("SOR source timestamps must include a timezone.")
    return value


StoredTimestamp = Annotated[str, AfterValidator(_aware_timestamp)]


class SorStoredCommandResult(BaseModel):
    """Exact mutation checkpoint; raw response is explicit durable data, not a snapshot."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor_object_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    external_request_id: str | None
    source_revision: str | None
    source_url: str | None
    response: dict[str, SorJsonValue] = Field(repr=False)

    @classmethod
    def from_result(cls, result: SorCommandResult) -> SorStoredCommandResult:
        return cls(
            vendor_object_key=result.vendor_object_key,
            external_id=result.external_id,
            external_request_id=result.external_request_id,
            source_revision=result.source_revision,
            source_url=result.source_url,
            response=result.response,
        )

    def to_result(self) -> SorCommandResult:
        return SorCommandResult(
            vendor_object_key=self.vendor_object_key,
            external_id=self.external_id,
            external_request_id=self.external_request_id,
            source_revision=self.source_revision,
            source_url=self.source_url,
            response=self.response,
        )


class SorStoredRecord(BaseModel):
    """Exact existing durable JSON shape, separate from the live vendor payload."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor_object_key: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(repr=False)
    source_created_at: StoredTimestamp | None
    source_updated_at: StoredTimestamp | None
    source_revision: str | None
    source_url: str | None

    @field_validator("payload")
    @classmethod
    def require_json_fields(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if not all(value):
            raise ValueError("SOR source payload keys must be non-empty strings.")
        normalized = to_json_value(value)
        if not isinstance(normalized, dict):
            raise ValueError("SOR source payload must be a JSON object.")
        return normalized

    @classmethod
    def from_record(cls, record: SorExternalRecord) -> SorStoredRecord:
        return cls(
            vendor_object_key=record.vendor_object_key,
            external_id=record.external_id,
            payload=json_safe_payload(record.payload),
            source_created_at=record.source_created_at.isoformat()
            if record.source_created_at is not None
            else None,
            source_updated_at=record.source_updated_at.isoformat()
            if record.source_updated_at is not None
            else None,
            source_revision=record.source_revision,
            source_url=record.source_url,
        )

    def to_record(self) -> SorExternalRecord:
        return SorExternalRecord(
            vendor_object_key=self.vendor_object_key,
            external_id=self.external_id,
            payload=SorSourcePayload.from_mapping(self.payload),
            source_created_at=datetime.fromisoformat(self.source_created_at)
            if self.source_created_at is not None
            else None,
            source_updated_at=datetime.fromisoformat(self.source_updated_at)
            if self.source_updated_at is not None
            else None,
            source_revision=self.source_revision,
            source_url=self.source_url,
        )


class SorStoredPage(BaseModel):
    """Validated checkpoint page; byte and page-count budgets remain sync policy."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    records: list[SorStoredRecord]
    next_cursor: str | None = Field(min_length=1)
    has_more: bool

    def to_page(self) -> SorRecordPage:
        return SorRecordPage(
            records=tuple(record.to_record() for record in self.records),
            next_cursor=self.next_cursor,
            has_more=self.has_more,
        )


def encode_external_record(record: SorExternalRecord) -> dict[str, JsonValue]:
    """Persist only the explicit wire schema, never a generic runtime snapshot."""
    if not isinstance(record, SorExternalRecord):
        raise SorProjectionError("SOR adapter returned an invalid source record.")
    try:
        return SorStoredRecord.from_record(record).model_dump(mode="json")
    except ValidationError as error:
        raise SorProjectionError("SOR source record is malformed.") from error


def decode_external_record(value: object) -> SorExternalRecord:
    """Read one persisted record with no coercion or ignored unknown fields."""
    try:
        return SorStoredRecord.model_validate(value).to_record()
    except ValidationError as error:
        raise SorProjectionError("Durable SOR source record is malformed.") from error


def json_safe_payload(payload: SorSourcePayload) -> dict[str, JsonValue]:
    """Return a recursively JSON-native payload or reject an unsafe value."""
    try:
        result = to_json_value(payload.to_wire())
    except SorJsonValueError as error:
        raise SorProjectionError("Source payload contains a non-JSON value.") from error
    if not isinstance(result, dict):
        raise SorProjectionError("Source payload is not a JSON object.")
    return result


__all__ = [
    "SorStoredPage",
    "SorStoredRecord",
    "decode_external_record",
    "encode_external_record",
    "json_safe_payload",
]
