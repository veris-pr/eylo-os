"""Product pause snapshots joining framework requests with exact tool identity."""

from __future__ import annotations

from typing import Annotated, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.framework.agents.approval import ApprovalRequest
from eylo.framework.agents.durable import InputRequestDetails
from eylo.framework.agents.interruptions import (
    ToolApprovalContinuation,
    ToolInputContinuation,
)
from eylo.framework.agents.tool import ToolCall
from eylo.modules.agent_runs.domain import AgentInputRequestKind
from eylo.modules.agent_runs.waits import AgentRunWaitState


class _ContinuationSnapshot(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class RunToolCallSnapshot(_ContinuationSnapshot):
    """Exact persisted invocation needed by non-conversation runners."""

    tool_call: ToolCall


class RunResumeReceipt(BaseModel):
    """Checkpoint fact only; the canonical tool result remains in the transcript."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    recorded: bool
    is_error: bool

    @field_validator("recorded")
    @classmethod
    def require_recorded(cls, value: bool) -> bool:
        """Only a completed transcript write may produce a resume checkpoint."""
        if not value:
            raise ValueError("Resume receipt requires a recorded tool result.")
        return value


class RunContinuation(_ContinuationSnapshot):
    """Common pause identity; conversations resolve tools from same-run messages."""

    framework: Annotated[
        ToolApprovalContinuation | ToolInputContinuation, Field(discriminator="type")
    ]
    request: ApprovalRequest | InputRequestDetails

    @model_validator(mode="after")
    def validate_request_kind(self) -> RunContinuation:
        approval = isinstance(self.framework, ToolApprovalContinuation)
        if approval != isinstance(self.request, ApprovalRequest):
            raise ValueError("Continuation request and tool pause kind differ.")
        return self


class ObjectiveRunContinuation(RunContinuation):
    """Direct-objective pause with its exact captured invocation."""

    objective: RunToolCallSnapshot

    @model_validator(mode="after")
    def validate_tool_identity(self) -> ObjectiveRunContinuation:
        if self.objective.tool_call.id != self.framework.tool_call_id:
            raise ValueError("Objective continuation tool identities differ.")
        return self


class ScheduledRunContinuation(RunContinuation):
    """Scheduled pause with its exact captured invocation."""

    scheduled: RunToolCallSnapshot

    @model_validator(mode="after")
    def validate_tool_identity(self) -> ScheduledRunContinuation:
        if self.scheduled.tool_call.id != self.framework.tool_call_id:
            raise ValueError("Scheduled continuation tool identities differ.")
        return self


_ContinuationT = TypeVar("_ContinuationT", bound=RunContinuation)


def parse_run_continuation(
    wait: AgentRunWaitState, model: type[_ContinuationT]
) -> _ContinuationT:
    """Validate JSON readback and bind the framework pause to the product kind."""
    continuation = model.model_validate(wait.continuation)
    approval = isinstance(continuation.framework, ToolApprovalContinuation)
    if approval != (wait.kind is AgentInputRequestKind.APPROVAL):
        raise ValueError("Continuation does not match the product request kind.")
    return continuation
