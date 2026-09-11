"""Objective-owned execution bounds persisted in generic AgentRun context."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

OBJECTIVE_MAX_STEPS = 200


class ObjectiveRunContextKind(StrEnum):
    """Stable persisted direct-objective discriminator."""

    OBJECTIVE = "objective"


class ObjectiveRunContext(BaseModel):
    """Required loop and time bounds, restored before any objective execution."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[ObjectiveRunContextKind.OBJECTIVE]
    max_steps: int = Field(ge=1, le=OBJECTIVE_MAX_STEPS)
    deadline: AwareDatetime

    @field_serializer("deadline", when_used="json")
    def serialize_deadline(self, value: datetime) -> str:
        """Keep stored offsets unchanged so existing idempotency digests match."""
        return value.isoformat()
