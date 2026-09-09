"""ID-only task inputs and content-free receipts for Memory durable workflows."""

from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_serializer,
    field_validator,
)

from eylo.absurd_work import DurableState
from eylo.common.contracts.memory import MemoryError as MemoryProviderError
from eylo.common.contracts.memory import MemoryOutcomeCounts
from eylo.modules.memory.reconciliation_service import ReconciliationCounts


class MemoryTaskKind(StrEnum):
    FORMATION = "formation"
    RECONCILIATION = "reconciliation"
    REINDEX = "reindex"


class MemoryJobParams(BaseModel):
    """Accept UUIDs or their wire strings; never stringify arbitrary objects."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    job_id: UUID

    @field_validator("organization_id", "job_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @classmethod
    def from_payload(cls, payload: object, *, kind: MemoryTaskKind) -> Self:
        if not isinstance(payload, dict) or payload.keys() != cls.model_fields.keys():
            raise ValueError(f"Memory {kind.value} task params must contain IDs only.")
        try:
            return cls.model_validate(payload)
        except ValidationError:
            raise ValueError(
                f"Memory {kind.value} task params contain an invalid UUID."
            ) from None


class MemoryMessagePosition(BaseModel):
    """A complete message watermark, ordered by timestamp then UUID."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    created_at: AwareDatetime
    message_id: UUID

    @property
    def order_key(self) -> tuple[datetime, UUID]:
        return self.created_at, self.message_id

    @field_serializer("created_at", when_used="json")
    def timestamp_json(self, value: datetime) -> str:
        """Preserve persisted ISO offsets, including +00:00 rather than Z."""
        return value.isoformat()

    @classmethod
    def from_optional(
        cls, created_at: datetime | None, message_id: UUID | None
    ) -> Self | None:
        if created_at is None and message_id is None:
            return None
        if created_at is None or message_id is None:
            raise MemoryProviderError("Memory formation watermark is incomplete.")
        return cls(created_at=created_at, message_id=message_id)


class MemoryFormationRange(BaseModel):
    """Receipt projection; filing owns the page limit and advancing-range policy."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    after: MemoryMessagePosition | None
    through: MemoryMessagePosition
    message_count: int = Field(ge=0)


class _MemoryReceipt(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    job_id: UUID
    state: DurableState

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class MemoryFormationReceipt(_MemoryReceipt):
    organization_id: UUID
    generation: int = Field(gt=0)
    range: MemoryFormationRange
    outcomes: MemoryOutcomeCounts


class MemoryReconciliationReceipt(_MemoryReceipt):
    organization_id: UUID
    generation: int = Field(gt=0)
    change_count: int = Field(ge=0)
    outcomes: ReconciliationCounts


class MemoryReindexReceipt(_MemoryReceipt):
    organization_id: UUID
    source_fact_count: int = Field(ge=0)
    indexed_fact_count: int = Field(ge=0)


class MemoryReindexFailureReceipt(_MemoryReceipt):
    """The existing minimal failure result; no invented counters or tenant field."""
