"""Run result contracts."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    SerializeAsAny,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .agent import AgentSpec
from .common import FrameworkMetadata, FrozenFrameworkModel
from .interruptions import RunApprovalInterruption, RunInputInterruption
from .items import RunItem
from .model import ModelResponse, ModelUsage
from .tool import CompletionMetadata, ToolCompletionMode, ToolIdentity


class RunStatus(str, Enum):
    """Terminal or interrupted state of a framework run."""

    COMPLETED = "completed"
    FAILED = "failed"
    GUARDRAIL_TRIPPED = "guardrail_tripped"
    TIMED_OUT = "timed_out"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    CANCELLED = "cancelled"


class RunFailureCode(str, Enum):
    """Framework-owned failure categories, independent of provider error codes."""

    RUN_FAILED = "run_failed"
    GUARDRAIL_BLOCKED = "guardrail_blocked"


class RunFailureMetadata(FrameworkMetadata):
    """Safe exception classification, never exception text or vendor payloads."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    failure_code: RunFailureCode
    error_type: StrictStr = Field(min_length=1)


class RunTerminalMetadata(CompletionMetadata):
    """Completed tool identity; a continue directive cannot conclude a run."""

    terminal_tool_call_id: ToolIdentity

    @model_validator(mode="after")
    def require_completion(self) -> RunTerminalMetadata:
        if self.terminal_response is not ToolCompletionMode.COMPLETE:
            raise ValueError("Terminal run metadata requires completion.")
        return self


def run_metadata_from(status: RunStatus, value: object) -> FrameworkMetadata:
    """Restore status-owned metadata on native or persisted-result boundaries."""
    fields = dict(value) if isinstance(value, FrameworkMetadata) else value
    if status is RunStatus.WAITING_FOR_APPROVAL:
        return RunApprovalInterruption.model_validate(fields)
    if status is RunStatus.WAITING_FOR_INPUT:
        return RunInputInterruption.model_validate(fields)
    if isinstance(value, (RunApprovalInterruption, RunInputInterruption)) or (
        isinstance(fields, dict)
        and fields.keys()
        & (
            RunApprovalInterruption.model_fields.keys()
            | RunInputInterruption.model_fields.keys()
        )
    ):
        raise ValueError(
            "Run interruption metadata requires its matching pause status."
        )
    if isinstance(fields, dict) and "failure_code" in fields:
        if fields.keys() & RunTerminalMetadata.model_fields.keys():
            raise ValueError(
                "Run metadata cannot contain failure and completion controls."
            )
        if isinstance(value, RunFailureMetadata):
            failure = type(value).model_validate(fields)
        else:
            failure = RunFailureMetadata.model_validate(
                value.model_dump() if isinstance(value, FrameworkMetadata) else fields
            )
        expected = (
            RunStatus.GUARDRAIL_TRIPPED
            if failure.failure_code is RunFailureCode.GUARDRAIL_BLOCKED
            else RunStatus.FAILED
        )
        if status is not expected:
            raise ValueError("Run failure category must match its status.")
        return failure
    if (
        isinstance(fields, dict)
        and fields.keys() & RunTerminalMetadata.model_fields.keys()
    ):
        if status is not RunStatus.COMPLETED:
            raise ValueError("Terminal tool metadata requires completed run status.")
        if isinstance(value, RunTerminalMetadata):
            return type(value).model_validate(value)
        return RunTerminalMetadata.model_validate(
            value.model_dump() if isinstance(value, FrameworkMetadata) else fields
        )
    return FrameworkMetadata.model_validate(value)


class RunResult(FrozenFrameworkModel):
    """Immutable outcome of a framework run."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    run_id: UUID
    status: RunStatus
    final_output: str | None = None
    final_message_id: UUID | None = None
    items: tuple[RunItem, ...] = ()
    model_responses: tuple[ModelResponse, ...] = ()
    usage: ModelUsage = Field(default_factory=ModelUsage)
    starting_agent: AgentSpec | None = None
    final_agent: AgentSpec | None = None
    error_message: str | None = None
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata, validate_default=True
    )

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_status_metadata(cls, value: object, info: ValidationInfo) -> object:
        """Restore owned pause/failure contracts from their existing wire fields."""
        status = info.data.get("status")
        if not isinstance(status, RunStatus):
            return value  # The status field reports its own validation failure.
        return run_metadata_from(status, value)

    @property
    def is_success(self) -> bool:
        """Return whether the run completed successfully."""
        return self.status == RunStatus.COMPLETED
