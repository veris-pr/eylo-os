"""Private sandbox tool results and bounded durable receipt contracts."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from eylo.modules.agent_runs.domain import AgentRunStepStatus

SandboxDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SandboxToolActionKind(StrEnum):
    """Actions represented by sandbox intents and their safe execution evidence."""

    EXEC = "exec"
    READ = "read"
    WRITE = "write"


class SandboxToolFailureCode(StrEnum):
    """Stable tool-facing failures; vendor exception text is never persisted."""

    DURABLE_RUN_REQUIRED = "durable_agent_run_required"
    INPUT_INVALID = "sandbox_input_invalid"
    NOT_CONFIGURED = "sandbox_not_configured"
    ACCESS_DENIED = "sandbox_access_denied"
    COMMAND_TIMED_OUT = "sandbox_command_timed_out"
    EXECUTION_FAILED = "sandbox_execution_failed"


class SandboxCheckpointDisposition(StrEnum):
    """Whether a finished action has a workspace eligible for checkpointing."""

    RETAIN = "retain"
    DISCARD = "discard"


class SandboxArtifactKind(StrEnum):
    """Safe step projection identifies a private workspace, never its bytes."""

    WORKSPACE_CHECKPOINT = "sandbox_workspace_checkpoint"


class _SandboxToolValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class SandboxExecIntent(_SandboxToolValue):
    """Command identity without the command or its potentially private arguments."""

    action: Literal[SandboxToolActionKind.EXEC] = SandboxToolActionKind.EXEC
    command_sha256: SandboxDigest


class SandboxFileIntent(_SandboxToolValue):
    """Workspace-relative target without file contents."""

    action: Literal[SandboxToolActionKind.READ, SandboxToolActionKind.WRITE]
    path: str


class SandboxExecEvidence(SandboxExecIntent):
    """Complete command outcome metadata, never stdout or stderr bodies."""

    exit_code: int
    stdout_bytes: int = Field(ge=0)
    stdout_sha256: SandboxDigest
    stderr_bytes: int = Field(ge=0)
    stderr_sha256: SandboxDigest
    timed_out: bool
    output_rejected: Literal[True] | None = None


class SandboxReadEvidence(SandboxFileIntent):
    """File fingerprint and optional text/refusal facts emitted by the read path."""

    action: Literal[SandboxToolActionKind.READ] = SandboxToolActionKind.READ
    content_bytes: int = Field(ge=0)
    content_sha256: SandboxDigest
    text: bool | None = None
    output_rejected: Literal[True] | None = None


class SandboxWriteEvidence(SandboxFileIntent):
    """Written byte fingerprint without the submitted content."""

    action: Literal[SandboxToolActionKind.WRITE] = SandboxToolActionKind.WRITE
    content_bytes: int = Field(ge=0)
    content_sha256: SandboxDigest


SandboxToolEvidence = SandboxExecEvidence | SandboxReadEvidence | SandboxWriteEvidence


class SandboxStepFailureEvidence(_SandboxToolValue):
    """Safe terminal failure field added to any available action evidence."""

    failure_code: SandboxToolFailureCode


class SandboxExecToolResult(_SandboxToolValue):
    """Bounded command output; rejected output stays empty, never truncated."""

    success: bool
    exit_code: int
    stdout: str = Field(repr=False)
    stderr: str = Field(repr=False)
    timed_out: bool
    message: str


class SandboxReadToolResult(_SandboxToolValue):
    """UTF-8 read outcome, including complete refusal of non-text/large files."""

    success: bool
    content: str = Field(repr=False)
    message: str


class SandboxWriteToolResult(_SandboxToolValue):
    """Write acknowledgement without retaining submitted file contents."""

    success: bool
    path: str
    message: str


SandboxCanonicalToolResult = (
    SandboxExecToolResult | SandboxReadToolResult | SandboxWriteToolResult
)
_CANONICAL_RESULT = TypeAdapter(SandboxCanonicalToolResult)


def parse_sandbox_tool_result(value: object) -> SandboxCanonicalToolResult:
    """Restore only the known private result shapes from a workspace checkpoint."""
    return _CANONICAL_RESULT.validate_python(value)


class SandboxToolFailure(_SandboxToolValue):
    """Safe failure returned without a usable workspace checkpoint."""

    success: Literal[False] = False
    error: SandboxToolFailureCode
    message: str


class SandboxCompletedReceipt(_SandboxToolValue):
    """Reference to the exact privately stored output/workspace pair."""

    status: Literal[AgentRunStepStatus.COMPLETED] = AgentRunStepStatus.COMPLETED
    checkpoint_revision: int = Field(gt=0)
    workspace_digest: SandboxDigest


class SandboxWorkspaceReference(_SandboxToolValue):
    """Persisted step artifact reference from which a receipt is reconstructed."""

    kind: Literal[SandboxArtifactKind.WORKSPACE_CHECKPOINT] = (
        SandboxArtifactKind.WORKSPACE_CHECKPOINT
    )
    revision: int = Field(gt=0)
    digest: SandboxDigest


class SandboxFailedReceipt(_SandboxToolValue):
    """Terminal refusal; missing historical failure codes retain their fallback."""

    status: Literal[AgentRunStepStatus.FAILED] = AgentRunStepStatus.FAILED
    failure_code: SandboxToolFailureCode = SandboxToolFailureCode.EXECUTION_FAILED


SandboxToolReceipt = Annotated[
    SandboxCompletedReceipt | SandboxFailedReceipt, Field(discriminator="status")
]
_RECEIPT = TypeAdapter(SandboxToolReceipt)


def parse_sandbox_receipt(
    value: object,
) -> SandboxCompletedReceipt | SandboxFailedReceipt:
    """Restore the exact JSON receipt shape and enum strings stored by Absurd."""
    # JSON readback accepts enum wire values without relaxing numeric/boolean types.
    return _RECEIPT.validate_json(json.dumps(value, allow_nan=False))


class SandboxToolMetadata(_SandboxToolValue):
    """Safe execution provenance; no workspace archive or model-facing output."""

    sandbox_execution: Literal[True] = True
    sandbox_step_key: str | None = None
    sandbox_checkpoint_revision: int | None = Field(default=None, gt=0)
    sandbox_workspace_digest: SandboxDigest | None = None
    sandbox_failure_code: SandboxToolFailureCode | None = None


class SandboxToolExecutionOutcome(_SandboxToolValue):
    """Live tool result; explicit content projection is the only raw output path."""

    content: SandboxCanonicalToolResult | SandboxToolFailure = Field(
        repr=False, exclude=True
    )
    is_error: bool
    metadata: SandboxToolMetadata

    @model_validator(mode="after")
    def require_consistent_outcome(self) -> SandboxToolExecutionOutcome:
        """Presentation cannot mark a refused canonical result as successful."""
        if self.is_error == self.content.success:
            raise ValueError("Sandbox outcome differs from its canonical result.")
        return self
