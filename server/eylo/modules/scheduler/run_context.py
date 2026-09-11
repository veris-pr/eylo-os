"""Immutable schedule-occurrence context used at AgentRun filing and readback."""

import json
from datetime import datetime
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)


class ScheduleRunContext(BaseModel):
    """Occurrence snapshot; arbitrary task inputs stay finite JSON, not authority."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    schedule_id: UUID
    schedule_revision: int = Field(gt=0)
    schedule_run_id: UUID
    scheduled_for: AwareDatetime
    action: str
    payload: dict[str, JsonValue] = Field(repr=False)
    misfired_count: int = Field(ge=0)

    @field_validator("payload")
    @classmethod
    def validate_payload_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """JsonValue validates structure; separately refuse non-finite numbers."""
        json.dumps(value, allow_nan=False)
        return value

    @field_serializer("scheduled_for", when_used="json")
    def serialize_scheduled_for(self, value: datetime) -> str:
        """Preserve the original ISO offset spelling used by the context digest."""
        return value.isoformat()
