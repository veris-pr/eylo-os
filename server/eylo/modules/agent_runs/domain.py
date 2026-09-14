"""Domain vocabulary for one durable agent execution."""

from __future__ import annotations

from enum import Enum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InitiatingPrincipalKind(str, Enum):
    """Durable authority kinds that may initiate agent work."""

    MEMBER = "member"
    CONTACT = "contact"
    API_KEY = "api_key"
    WIDGET = "widget"
    WORKER = "worker"


class AgentRunOriginKind(str, Enum):
    """Immutable V1 origins for an agent run."""

    MESSAGE = "message"
    SCHEDULE_OCCURRENCE = "schedule_occurrence"
    OBJECTIVE = "objective"


class AgentRunLifecycle(str, Enum):
    """Execution/export lifecycle, separate from goal achievement."""

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_TOOL = "waiting_for_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunOutcome(str, Enum):
    """Typed conclusion about whether the run achieved its goal."""

    ACHIEVED = "achieved"
    UNACHIEVABLE = "unachievable"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"


class AgentRunStepKind(str, Enum):
    """Safe product projection kinds for workflow steps."""

    AGENT_TURN = "agent_turn"
    MODEL_INFERENCE = "model_inference"
    TOOL = "tool"
    SANDBOX = "sandbox"
    ARTIFACT_EXPORT = "artifact_export"


class AgentRunTranscriptKind(str, Enum):
    """Private replay row kinds; values preserve the persisted JSON contract."""

    ASSISTANT_TEXT = "assistant_text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class AgentRunStepStatus(str, Enum):
    """Product/audit state for one run step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentInputRequestKind(str, Enum):
    """Kinds of explicit human response a run may await."""

    INPUT = "input"
    APPROVAL = "approval"


class AgentApprovalDecision(str, Enum):
    """A human's decision about one persisted product approval request."""

    APPROVE = "approve"
    REJECT = "reject"


class AgentInputRequestStatus(str, Enum):
    """No expiry exists: a request resolves only by answer or cancellation."""

    PENDING = "pending"
    ANSWERED = "answered"
    CANCELLED = "cancelled"


class ExecutionBudgetDimension(str, Enum):
    """The exact organization execution boundary that rejected a run."""

    CONCURRENCY = "concurrency"
    TOKENS = "tokens"
    ACTIVE_TIME = "active_time"
    COST = "cost"


class ExecutionTokenUsage(BaseModel):
    """Exact input/output consumption validated before budget storage changes."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)

    @property
    def total_tokens(self) -> int:
        """Keep reservation accounting independent of vendor detail counters."""
        return self.input_tokens + self.output_tokens


class ExecutionBudgetError(Exception):
    """Base failure for explicit organization execution budgets."""


class ExecutionBudgetNotConfigured(ExecutionBudgetError):
    """The organization has not configured an execution budget."""


class ExecutionBudgetConflict(ExecutionBudgetError):
    """A budget command conflicts with active durable reservations."""


class ExecutionBudgetUnavailable(ExecutionBudgetError):
    """A complete reservation cannot fit inside an organization boundary."""

    def __init__(self, dimension: ExecutionBudgetDimension) -> None:
        self.dimension = dimension
        super().__init__(
            f"Organization {dimension.value} execution capacity is unavailable."
        )


class ExecutionBudgetExceeded(ExecutionBudgetError):
    """A running agent crossed a pinned limit and cannot return partial output."""

    def __init__(self, dimension: ExecutionBudgetDimension) -> None:
        self.dimension = dimension
        super().__init__(f"Agent run exceeded its {dimension.value} limit.")


class ExecutionUsageNotReported(ExecutionBudgetError):
    """A provider response omitted usage required by an active run budget."""


_LEGAL_TERMINAL_OUTCOMES = {
    AgentRunLifecycle.COMPLETED: frozenset(
        {
            AgentRunOutcome.ACHIEVED,
            AgentRunOutcome.UNACHIEVABLE,
            AgentRunOutcome.EXHAUSTED,
        }
    ),
    AgentRunLifecycle.FAILED: frozenset({AgentRunOutcome.FAILED}),
    AgentRunLifecycle.CANCELLED: frozenset({AgentRunOutcome.CANCELLED}),
}


def validate_lifecycle_outcome(
    lifecycle: AgentRunLifecycle,
    outcome: AgentRunOutcome | None,
) -> None:
    """Reject inferred or contradictory achievement state."""
    legal = _LEGAL_TERMINAL_OUTCOMES.get(lifecycle)
    if legal is None:
        if outcome is not None:
            raise ValueError(f"{lifecycle.value} AgentRun cannot have an outcome.")
        return
    if outcome not in legal:
        allowed = ", ".join(sorted(candidate.value for candidate in legal))
        raise ValueError(
            f"{lifecycle.value} AgentRun requires one of these outcomes: {allowed}."
        )


class InitiatingPrincipalRef(BaseModel):
    """Organization-bearing authority reloaded on every work claim."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    kind: InitiatingPrincipalKind
    principal_id: UUID


class AgentRunOrigin(BaseModel):
    """One immutable external origin, or an explicitly filed objective."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: AgentRunOriginKind
    message_id: UUID | None = None
    schedule_run_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_origin(self) -> Self:
        message_origin = self.message_id is not None and self.schedule_run_id is None
        schedule_origin = self.schedule_run_id is not None and self.message_id is None
        if self.kind is AgentRunOriginKind.MESSAGE and message_origin:
            return self
        if self.kind is AgentRunOriginKind.SCHEDULE_OCCURRENCE and schedule_origin:
            return self
        if (
            self.kind is AgentRunOriginKind.OBJECTIVE
            and self.message_id is None
            and self.schedule_run_id is None
        ):
            return self
        raise ValueError(f"Invalid {self.kind.value} AgentRun origin fields.")

    @classmethod
    def message(cls, message_id: UUID) -> AgentRunOrigin:
        return cls(kind=AgentRunOriginKind.MESSAGE, message_id=message_id)

    @classmethod
    def schedule_occurrence(cls, schedule_run_id: UUID) -> AgentRunOrigin:
        return cls(
            kind=AgentRunOriginKind.SCHEDULE_OCCURRENCE,
            schedule_run_id=schedule_run_id,
        )

    @classmethod
    def objective(cls) -> AgentRunOrigin:
        return cls(kind=AgentRunOriginKind.OBJECTIVE)


class AgentRunTerminalResult(BaseModel):
    """One validated immutable lifecycle/outcome pair."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    lifecycle: AgentRunLifecycle
    outcome: AgentRunOutcome
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_outcome(self) -> Self:
        validate_lifecycle_outcome(self.lifecycle, self.outcome)
        return self
