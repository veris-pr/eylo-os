"""Agent-visible telephony outcomes and validated scheduled-call payloads."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from eylo.common.contracts.json_values import JsonObject


class CallToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    SCHEDULED = "scheduled"


class CallTransferFailureCode(StrEnum):
    UNCONFIRMED = "call_transfer_unconfirmed"
    REJECTED = "call_transfer_rejected"


class _ToolValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )


class CallToolError(_ToolValue):
    status: Literal[CallToolStatus.ERROR] = CallToolStatus.ERROR
    message: str


class CallToolSuccess(_ToolValue):
    status: Literal[CallToolStatus.SUCCESS] = CallToolStatus.SUCCESS
    message: str
    call_sid: str


class CallToolScheduled(_ToolValue):
    status: Literal[CallToolStatus.SCHEDULED] = CallToolStatus.SCHEDULED
    scheduled_time: str
    to_number: str


class ScheduledCallKind(StrEnum):
    OUTBOUND_CALL = "outbound_call"


_JSON_OBJECT = TypeAdapter(JsonObject)


class AgentScheduledCallPayload(_ToolValue):
    """Flat custom context cannot override explicit call inputs or runtime identity."""

    kind: Literal[ScheduledCallKind.OUTBOUND_CALL] = ScheduledCallKind.OUTBOUND_CALL
    to_number: str
    agent_id: UUID
    org_id: UUID
    initial_message: str
    call_at: str
    metadata: JsonObject = Field(default_factory=dict, exclude=True, repr=False)

    @classmethod
    def for_call(
        cls,
        *,
        to_number: str,
        agent_id: UUID,
        organization_id: UUID,
        initial_message: str,
        call_at: str,
        metadata: JsonObject | None,
    ) -> AgentScheduledCallPayload:
        return cls(
            to_number=to_number,
            agent_id=agent_id,
            org_id=organization_id,
            initial_message=initial_message,
            call_at=call_at,
            metadata=metadata if metadata is not None else {},
        )

    def as_payload(self) -> JsonObject:
        """Validate custom context again at the scheduler's finite-JSON boundary."""
        return _JSON_OBJECT.validate_python(
            {**self.metadata, **self.model_dump(mode="json")}
        )
