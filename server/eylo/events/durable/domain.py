"""Validated vocabulary for unordered durable event facts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

EVENT_PAYLOAD_MAX_BYTES = 65_536
MAX_DELIVERY_ATTEMPTS = 3
MAX_EVENT_VERSION = 32_767
_QUALIFIED_NAME_PATTERN = r"^[a-z][a-z0-9_.-]*$"
_QUALIFIED_NAME = re.compile(_QUALIFIED_NAME_PATTERN)


class EventDeliveryState(str, Enum):
    """Persistence state for one explicit event consumer."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class EventDeliveryFailureCode(StrEnum):
    """Persisted safe failure codes; only execution failures are retryable."""

    CONSUMER_NOT_REGISTERED = "consumer_not_registered"
    CONSUMER_REJECTED = "consumer_rejected"
    DELIVERY_FAILED = "delivery_failed"

    @property
    def permanent(self) -> bool:
        return self is not EventDeliveryFailureCode.DELIVERY_FAILED


class EventDeliveryTaskParams(BaseModel):
    """Detached delivery authority shared by task filing and worker parsing."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    delivery_id: UUID

    @classmethod
    def from_wire(cls, params: Mapping[str, object]) -> EventDeliveryTaskParams:
        if set(params) != {"organization_id", "delivery_id"}:
            raise ValueError(
                "Event delivery task requires only organization_id and delivery_id."
            )
        values: dict[str, UUID] = {}
        for key, value in params.items():
            if isinstance(value, UUID):
                values[key] = value
            elif isinstance(value, str):
                try:
                    values[key] = UUID(value)
                except ValueError as error:
                    raise ValueError(
                        "Event delivery task IDs must be UUIDs."
                    ) from error
            else:
                raise ValueError("Event delivery task IDs must be UUIDs.")
        return cls.model_validate(values)


class EventDeliveryResult(BaseModel):
    """Payload-free worker receipt, explicitly serialized at the Absurd boundary."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    state: EventDeliveryState
    attempts: int = Field(ge=0)


class DurableEventEnvelope(BaseModel):
    """One immutable, tenant-owned fact with no ordering promise."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: UUID
    organization_id: UUID
    subject_type: str = Field(
        min_length=1,
        max_length=128,
        pattern=_QUALIFIED_NAME_PATTERN,
    )
    subject_id: UUID
    event_type: str = Field(
        min_length=1,
        max_length=192,
        pattern=_QUALIFIED_NAME_PATTERN,
    )
    event_version: int = Field(ge=1, le=MAX_EVENT_VERSION)
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_fact(self) -> DurableEventEnvelope:
        for field_name in ("occurred_at", "recorded_at"):
            value = getattr(self, field_name)
            if value.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be an aware UTC datetime.")
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at.")
        if self.causation_id == self.event_id:
            raise ValueError("An event cannot cause itself.")

        encoded_payload = json.dumps(
            self.payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(encoded_payload) > EVENT_PAYLOAD_MAX_BYTES:
            raise ValueError(
                f"payload exceeds {EVENT_PAYLOAD_MAX_BYTES} encoded bytes."
            )
        return self


def _validate_qualified_name(value: str, *, field_name: str) -> str:
    if not 1 <= len(value) <= 192 or _QUALIFIED_NAME.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a qualified lowercase name.")
    return value


def validate_consumer_name(value: str) -> str:
    """Validate one stable consumer identity without normalizing it."""
    return _validate_qualified_name(value, field_name="consumer_name")


def validate_event_type(value: str) -> str:
    """Validate one versioned fact type without normalizing it."""
    return _validate_qualified_name(value, field_name="event_type")
