"""Validated human answers and detached wait snapshots for durable agent runs."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from eylo.modules.agent_runs.domain import (
    AgentApprovalDecision,
    AgentInputRequestKind,
    AgentInputRequestStatus,
)


def _finite_json(value: JsonValue) -> JsonValue:
    """Enforce finite numbers even when union schema reuse loses model config."""
    json.dumps(value, allow_nan=False)
    return value


_FiniteJsonValue = Annotated[JsonValue, AfterValidator(_finite_json)]


class AgentApprovalResponse(BaseModel):
    """Closed approval answer; arbitrary user input uses its requested JSON schema."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    decision: AgentApprovalDecision
    comment: StrictStr | None = None


class _AgentRunWaitState(BaseModel):
    """Product identity and JSON snapshot; pipelines own continuation semantics."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    request_id: UUID
    status: Literal[AgentInputRequestStatus.PENDING, AgentInputRequestStatus.ANSWERED]
    event_name: StrictStr
    resume_step_key: StrictStr
    continuation: dict[str, _FiniteJsonValue]

    def require_answered(self) -> None:
        """Reject pending snapshots before a resume consumer performs work."""
        if self.status is not AgentInputRequestStatus.ANSWERED:
            raise ValueError("AgentRun input request has not been answered.")


class AgentInputWaitState(_AgentRunWaitState):
    """A dynamic JSON answer; answered JSON null differs from an unanswered wait."""

    kind: Literal[AgentInputRequestKind.INPUT] = AgentInputRequestKind.INPUT
    response: _FiniteJsonValue

    @model_validator(mode="after")
    def validate_pending_response(self) -> AgentInputWaitState:
        if self.status is AgentInputRequestStatus.PENDING and self.response is not None:
            raise ValueError("Pending input request cannot contain an answer.")
        return self


class AgentApprovalWaitState(_AgentRunWaitState):
    """A pending approval or an answered approval with a validated decision."""

    kind: Literal[AgentInputRequestKind.APPROVAL] = AgentInputRequestKind.APPROVAL
    response: AgentApprovalResponse | None

    @model_validator(mode="after")
    def validate_response_status(self) -> AgentApprovalWaitState:
        answered = self.status is AgentInputRequestStatus.ANSWERED
        if answered != (self.response is not None):
            raise ValueError("Approval response does not match its request status.")
        return self

    def require_response(self) -> AgentApprovalResponse:
        """Return the checked decision only for an answered request."""
        self.require_answered()
        if self.response is None:
            raise ValueError("Answered approval request has no response.")
        return self.response


AgentRunWaitState = Annotated[
    AgentInputWaitState | AgentApprovalWaitState, Field(discriminator="kind")
]
_WAIT_STATE_ADAPTER = TypeAdapter(AgentRunWaitState)


def parse_agent_run_wait_state(value: object) -> AgentRunWaitState:
    """Validate persistence readback before exposing it to resume consumers."""
    return _WAIT_STATE_ADAPTER.validate_python(value)


class AgentRunInputEvent(BaseModel):
    """Wake notification for a committed answer; the answer itself stays in the DB."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    run_id: UUID
    request_id: UUID

    def as_json(self) -> dict[str, str]:
        return {
            "organization_id": str(self.organization_id),
            "run_id": str(self.run_id),
            "request_id": str(self.request_id),
        }

    def require_matching_payload(self, payload: object) -> None:
        """Keep exact canonical wire identity; UUID coercion must not widen a wake."""
        event = AgentRunInputEvent.model_validate(payload)
        if event != self or payload != event.as_json():
            raise ValueError(
                "Durable input event does not match the identified request."
            )
