"""Immutable schedule-occurrence context used at AgentRun filing and readback."""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from eylo.common.contracts.json_values import JsonObject


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
    payload: JsonObject = Field(repr=False)
    misfired_count: int = Field(ge=0)

    @field_serializer("scheduled_for", when_used="json")
    def serialize_scheduled_for(self, value: datetime) -> str:
        """Preserve the original ISO offset spelling used by the context digest."""
        return value.isoformat()
