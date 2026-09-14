"""Durable AgentRun-scoped execution for published sandbox system tools.

Every call gets fresh compute, restores the latest workspace checkpoint,
performs one bounded action, stores raw model-facing output only beside the
private workspace checkpoint, then destroys compute. Absurd checkpoints carry
only a small receipt; AgentRun step/API projections carry only safe metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    model_validator,
)
from sqlalchemy import select

from eylo.common.contracts.sandbox import SandboxError, SandboxSession
from eylo.common.database import start_transaction
from eylo.modules.agent_runs.budgets import current_agent_run_id
from eylo.modules.agent_runs.domain import AgentRunStepKind, AgentRunStepStatus
from eylo.modules.agent_runs.models import AgentRunStepModel
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.sandbox.access import SandboxAccessError
from eylo.pipelines.outbound.durable_execution import CommandStepContext
from eylo.pipelines.sandbox.sessions import (
    acquire,
    discard_live_run_sessions,
    export_and_destroy_workspace,
    store_workspace_checkpoint_in_transaction,
    workspace_checkpoint_for_step,
)
from eylo.pipelines.sandbox.tool_contracts import (
    SandboxCanonicalToolResult,
    SandboxCheckpointDisposition,
    SandboxCompletedReceipt,
    SandboxExecEvidence,
    SandboxExecIntent,
    SandboxExecToolResult,
    SandboxFailedReceipt,
    SandboxFileIntent,
    SandboxReadEvidence,
    SandboxReadToolResult,
    SandboxStepFailureEvidence,
    SandboxToolActionKind,
    SandboxToolEvidence,
    SandboxToolExecutionOutcome,
    SandboxToolFailure,
    SandboxToolFailureCode,
    SandboxToolMetadata,
    SandboxWorkspaceReference,
    SandboxWriteEvidence,
    SandboxWriteToolResult,
    parse_sandbox_receipt,
    parse_sandbox_tool_result,
)
from eylo.sockets.sandbox.base import SandboxVendorAdapter

logger = logging.getLogger(__name__)

SANDBOX_EXEC_TOOL_SLUG = "sandbox_exec"
SANDBOX_READ_TOOL_SLUG = "sandbox_read"
SANDBOX_WRITE_TOOL_SLUG = "sandbox_write"
SANDBOX_TOOL_SLUGS = frozenset(
    {
        SANDBOX_EXEC_TOOL_SLUG,
        SANDBOX_READ_TOOL_SLUG,
        SANDBOX_WRITE_TOOL_SLUG,
    }
)

_DEFAULT_TIMEOUT_SECONDS = 60
_MAX_TIMEOUT_SECONDS = 300
_MAX_COMMAND_CHARS = 2_000
_MAX_PATH_CHARS = 512
_MAX_MODEL_OUTPUT_BYTES = 4_000
_STEP_VERSION = 1


class SandboxToolInputError(ValueError):
    """The model supplied an invalid sandbox tool payload."""


class SandboxToolAction(BaseModel):
    """Validated operation; command/file contents are excluded from snapshots."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: SandboxToolActionKind
    command: str | None = Field(
        default=None, repr=False, exclude=True, max_length=_MAX_COMMAND_CHARS
    )
    path: str | None = Field(default=None, max_length=_MAX_PATH_CHARS)
    content: str | None = Field(default=None, repr=False, exclude=True)
    timeout_seconds: int = Field(
        default=_DEFAULT_TIMEOUT_SECONDS, ge=1, le=_MAX_TIMEOUT_SECONDS
    )

    @model_validator(mode="after")
    def require_action_fields(self) -> SandboxToolAction:
        """No constructor may create a mixed or incomplete executable operation."""
        if self.kind is SandboxToolActionKind.EXEC:
            valid = (
                bool(self.command and self.command.strip())
                and self.path is None
                and self.content is None
            )
        else:
            valid = bool(self.path and self.path.strip()) and self.command is None
            valid = valid and (
                (self.content is not None)
                if self.kind is SandboxToolActionKind.WRITE
                else self.content is None
            )
        if not valid:
            raise ValueError("Sandbox action has missing or incompatible fields.")
        return self

    @classmethod
    def from_call(cls, slug: str, arguments: dict[str, JsonValue]) -> SandboxToolAction:
        if slug == SANDBOX_EXEC_TOOL_SLUG:
            _require_fields(arguments, allowed={"command", "timeout_seconds"})
            command = _required_text(
                arguments,
                "command",
                max_chars=_MAX_COMMAND_CHARS,
            )
            timeout = arguments.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or not 1 <= timeout <= _MAX_TIMEOUT_SECONDS
            ):
                raise SandboxToolInputError(
                    "timeout_seconds must be an integer between 1 and 300."
                )
            return cls(
                kind=SandboxToolActionKind.EXEC,
                command=command,
                timeout_seconds=timeout,
            )
        if slug == SANDBOX_READ_TOOL_SLUG:
            _require_fields(arguments, allowed={"path"})
            return cls(
                kind=SandboxToolActionKind.READ,
                path=_required_text(arguments, "path", max_chars=_MAX_PATH_CHARS),
            )
        if slug == SANDBOX_WRITE_TOOL_SLUG:
            _require_fields(arguments, allowed={"path", "content"})
            return cls(
                kind=SandboxToolActionKind.WRITE,
                path=_required_text(arguments, "path", max_chars=_MAX_PATH_CHARS),
                content=_required_text(arguments, "content", allow_empty=True),
            )
        raise SandboxToolInputError("Sandbox tool is not supported.")

    @property
    def safe_intent(self) -> dict[str, JsonValue]:
        if self.kind is SandboxToolActionKind.EXEC:
            assert self.command is not None
            return SandboxExecIntent(
                command_sha256=_digest(self.command.encode("utf-8"))
            ).model_dump(mode="json")
        assert self.path is not None
        return SandboxFileIntent(action=self.kind, path=self.path).model_dump(
            mode="json"
        )


async def execute_agent_sandbox_tool(
    *,
    tool_slug: str,
    tool_input: dict[str, JsonValue],
    organization_id: UUID,
    agent_id: UUID,
    agent_run_id: UUID,
    tool_command_id: UUID,
    durable_context: CommandStepContext,
) -> SandboxToolExecutionOutcome:
    """Execute one published sandbox tool under the current AgentRun."""
    active_run_id = current_agent_run_id()
    if active_run_id is None or active_run_id != agent_run_id:
        return _failure_outcome(
            SandboxToolFailureCode.DURABLE_RUN_REQUIRED,
            message=(
                "Sandbox work requires a durable agent run and is unavailable "
                "inside the live voice path."
            ),
        )
    try:
        action = SandboxToolAction.from_call(tool_slug, tool_input)
    except SandboxToolInputError:
        return _failure_outcome(
            SandboxToolFailureCode.INPUT_INVALID,
            message="Sandbox tool input is invalid.",
        )

    product_step_key = f"sandbox:tool:{tool_command_id}"
    receipt = await durable_context.step(
        key=product_step_key,
        version=_STEP_VERSION,
        operation=lambda: _execute_and_project(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            product_step_key=product_step_key,
            action=action,
        ),
    )
    return await _outcome_from_receipt(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
        product_step_key=product_step_key,
        receipt=receipt,
    )


async def _execute_and_project(
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_run_id: UUID,
    product_step_key: str,
    action: SandboxToolAction,
) -> dict[str, JsonValue]:
    existing = await _load_step(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
        step_key=product_step_key,
    )
    if existing is not None:
        return _receipt_from_step(existing)

    try:
        await discard_live_run_sessions(
            organization_id=organization_id,
            agent_run_id=agent_run_id,
        )
        adapter, session = await acquire(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
        )
        result, evidence, checkpointable = await _perform_action(
            adapter,
            session,
            action,
        )
        if checkpointable is SandboxCheckpointDisposition.DISCARD:
            await discard_live_run_sessions(
                organization_id=organization_id,
                agent_run_id=agent_run_id,
            )
            return await _record_failed_step(
                organization_id=organization_id,
                agent_run_id=agent_run_id,
                step_key=product_step_key,
                action=action,
                failure_code=SandboxToolFailureCode.COMMAND_TIMED_OUT,
                evidence=evidence,
            )

        exported = await export_and_destroy_workspace(session)
        async with start_transaction() as db:
            existing = await db.scalar(
                select(AgentRunStepModel).where(
                    AgentRunStepModel.organization_id == organization_id,
                    AgentRunStepModel.run_id == agent_run_id,
                    AgentRunStepModel.step_key == product_step_key,
                    AgentRunStepModel.deleted.is_(False),
                )
            )
            if existing is not None:
                return _receipt_from_step(existing)
            checkpoint = await store_workspace_checkpoint_in_transaction(
                db,
                organization_id=organization_id,
                source_step_key=product_step_key,
                exported=exported,
                tool_result=result.model_dump(mode="json"),
            )
            now = datetime.now(timezone.utc)
            db.add(
                AgentRunStepModel(
                    organization_id=organization_id,
                    run_id=agent_run_id,
                    step_key=product_step_key,
                    kind=AgentRunStepKind.SANDBOX,
                    status=AgentRunStepStatus.COMPLETED,
                    intent=action.safe_intent,
                    safe_summary=_safe_summary(evidence),
                    evidence=evidence.model_dump(mode="json", exclude_none=True),
                    artifact_refs=[
                        SandboxWorkspaceReference(
                            revision=checkpoint.revision,
                            digest=checkpoint.workspace_digest,
                        ).model_dump(mode="json")
                    ],
                    started_at=now,
                    completed_at=now,
                )
            )
            await db.flush()
            return SandboxCompletedReceipt(
                checkpoint_revision=checkpoint.revision,
                workspace_digest=checkpoint.workspace_digest,
            ).model_dump(mode="json")
    except asyncio.CancelledError:
        await discard_live_run_sessions(
            organization_id=organization_id,
            agent_run_id=agent_run_id,
        )
        raise
    except NotConfiguredError:
        failure_code = SandboxToolFailureCode.NOT_CONFIGURED
    except SandboxAccessError:
        failure_code = SandboxToolFailureCode.ACCESS_DENIED
    except (SandboxError, ValidationError) as error:
        logger.warning(
            "Sandbox tool action failed error_type=%s",
            type(error).__name__,
        )
        failure_code = SandboxToolFailureCode.EXECUTION_FAILED

    await discard_live_run_sessions(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
    )
    return await _record_failed_step(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
        step_key=product_step_key,
        action=action,
        failure_code=failure_code,
    )


async def _perform_action(
    adapter: SandboxVendorAdapter,
    session: SandboxSession,
    action: SandboxToolAction,
) -> tuple[
    SandboxCanonicalToolResult, SandboxToolEvidence, SandboxCheckpointDisposition
]:
    if action.kind is SandboxToolActionKind.WRITE:
        assert action.path is not None and action.content is not None
        encoded = action.content.encode("utf-8")
        await adapter.write(session, action.path, encoded)
        return (
            SandboxWriteToolResult(
                success=True, path=action.path, message=f"Wrote {action.path}."
            ),
            SandboxWriteEvidence(
                path=action.path,
                content_bytes=len(encoded),
                content_sha256=_digest(encoded),
            ),
            SandboxCheckpointDisposition.RETAIN,
        )

    if action.kind is SandboxToolActionKind.READ:
        assert action.path is not None
        raw = await adapter.read(session, action.path)
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return (
                SandboxReadToolResult(
                    success=False, content="", message="Sandbox file is not UTF-8 text."
                ),
                _read_evidence(action.path, raw, text=False),
                SandboxCheckpointDisposition.RETAIN,
            )
        if len(raw) > _MAX_MODEL_OUTPUT_BYTES:
            return (
                SandboxReadToolResult(
                    success=False,
                    content="",
                    message=(
                        "Sandbox file exceeds the model-output ceiling; no "
                        "partial content was returned."
                    ),
                ),
                _read_evidence(action.path, raw, output_rejected=True),
                SandboxCheckpointDisposition.RETAIN,
            )
        return (
            SandboxReadToolResult(success=True, content=content, message=""),
            _read_evidence(action.path, raw, text=True),
            SandboxCheckpointDisposition.RETAIN,
        )

    assert action.command is not None
    execution = await adapter.exec(
        session,
        action.command,
        timeout_seconds=action.timeout_seconds,
    )
    stdout_bytes = execution.stdout.encode("utf-8")
    stderr_bytes = execution.stderr.encode("utf-8")
    evidence = SandboxExecEvidence(
        command_sha256=_digest(action.command.encode("utf-8")),
        exit_code=execution.exit_code,
        stdout_bytes=len(stdout_bytes),
        stdout_sha256=_digest(stdout_bytes),
        stderr_bytes=len(stderr_bytes),
        stderr_sha256=_digest(stderr_bytes),
        timed_out=execution.timed_out,
        output_rejected=(
            True
            if not execution.timed_out
            and len(stdout_bytes) + len(stderr_bytes) > _MAX_MODEL_OUTPUT_BYTES
            else None
        ),
    )
    if execution.timed_out:
        return (
            SandboxExecToolResult(
                success=False,
                exit_code=execution.exit_code,
                stdout="",
                stderr="",
                timed_out=True,
                message="Sandbox command timed out and compute was destroyed.",
            ),
            evidence,
            SandboxCheckpointDisposition.DISCARD,
        )
    if len(stdout_bytes) + len(stderr_bytes) > _MAX_MODEL_OUTPUT_BYTES:
        return (
            SandboxExecToolResult(
                success=False,
                exit_code=execution.exit_code,
                stdout="",
                stderr="",
                timed_out=False,
                message=(
                    "Sandbox command output exceeds the model-output ceiling; "
                    "no partial output was returned."
                ),
            ),
            evidence,
            SandboxCheckpointDisposition.RETAIN,
        )
    return (
        SandboxExecToolResult(
            success=execution.ok,
            exit_code=execution.exit_code,
            stdout=execution.stdout,
            stderr=execution.stderr,
            timed_out=False,
            message="",
        ),
        evidence,
        SandboxCheckpointDisposition.RETAIN,
    )


async def _record_failed_step(
    *,
    organization_id: UUID,
    agent_run_id: UUID,
    step_key: str,
    action: SandboxToolAction,
    failure_code: SandboxToolFailureCode,
    evidence: SandboxToolEvidence | None = None,
) -> dict[str, JsonValue]:
    safe_evidence = {
        **(
            evidence.model_dump(mode="json", exclude_none=True)
            if evidence is not None
            else {}
        ),
        **SandboxStepFailureEvidence(failure_code=failure_code).model_dump(mode="json"),
    }
    async with start_transaction() as db:
        existing = await db.scalar(
            select(AgentRunStepModel).where(
                AgentRunStepModel.organization_id == organization_id,
                AgentRunStepModel.run_id == agent_run_id,
                AgentRunStepModel.step_key == step_key,
                AgentRunStepModel.deleted.is_(False),
            )
        )
        if existing is not None:
            return _receipt_from_step(existing)
        now = datetime.now(timezone.utc)
        db.add(
            AgentRunStepModel(
                organization_id=organization_id,
                run_id=agent_run_id,
                step_key=step_key,
                kind=AgentRunStepKind.SANDBOX,
                status=AgentRunStepStatus.FAILED,
                intent=action.safe_intent,
                safe_summary="Sandbox action failed without retained compute.",
                evidence=safe_evidence,
                artifact_refs=[],
                started_at=now,
                completed_at=now,
            )
        )
        await db.flush()
    return SandboxFailedReceipt(failure_code=failure_code).model_dump(mode="json")


async def _outcome_from_receipt(
    *,
    organization_id: UUID,
    agent_run_id: UUID,
    product_step_key: str,
    receipt: object,
) -> SandboxToolExecutionOutcome:
    try:
        restored = parse_sandbox_receipt(receipt)
    except (ValueError, TypeError) as error:
        raise SandboxError("Sandbox durable receipt is invalid.") from error
    if isinstance(restored, SandboxFailedReceipt):
        code = restored.failure_code
        return _failure_outcome(code, message=_failure_message(code))

    checkpoint = await workspace_checkpoint_for_step(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
        source_step_key=product_step_key,
    )
    if checkpoint is None or not isinstance(checkpoint.tool_result, dict):
        raise SandboxError("Sandbox checkpoint is missing its canonical tool result.")
    if (
        checkpoint.revision != restored.checkpoint_revision
        or checkpoint.workspace_digest != restored.workspace_digest
    ):
        raise SandboxError("Sandbox receipt does not match its workspace checkpoint.")
    try:
        content = parse_sandbox_tool_result(checkpoint.tool_result)
    except ValidationError as error:
        raise SandboxError("Sandbox canonical tool result is invalid.") from error
    return SandboxToolExecutionOutcome(
        content=content,
        is_error=not content.success,
        metadata=SandboxToolMetadata(
            sandbox_step_key=product_step_key,
            sandbox_checkpoint_revision=checkpoint.revision,
            sandbox_workspace_digest=checkpoint.workspace_digest,
        ),
    )


async def _load_step(
    *,
    organization_id: UUID,
    agent_run_id: UUID,
    step_key: str,
) -> AgentRunStepModel | None:
    async with start_transaction(ro=True) as db:
        return await db.scalar(
            select(AgentRunStepModel).where(
                AgentRunStepModel.organization_id == organization_id,
                AgentRunStepModel.run_id == agent_run_id,
                AgentRunStepModel.step_key == step_key,
                AgentRunStepModel.deleted.is_(False),
            )
        )


def _receipt_from_step(step: AgentRunStepModel) -> dict[str, JsonValue]:
    if step.status is AgentRunStepStatus.FAILED:
        evidence = step.evidence or {}
        try:
            raw_code = (
                evidence.get("failure_code") or SandboxToolFailureCode.EXECUTION_FAILED
            )
            if not isinstance(raw_code, str):
                raise ValueError("Sandbox step failure code must be text.")
            code = SandboxToolFailureCode(raw_code)
        except ValueError as error:
            raise SandboxError("Sandbox step failure code is invalid.") from error
        return SandboxFailedReceipt(failure_code=code).model_dump(mode="json")
    if step.status is not AgentRunStepStatus.COMPLETED or not step.artifact_refs:
        raise SandboxError("Sandbox product step is incomplete.")
    try:
        artifact = SandboxWorkspaceReference.model_validate_json(
            json.dumps(step.artifact_refs[0], allow_nan=False)
        )
        return SandboxCompletedReceipt(
            checkpoint_revision=artifact.revision,
            workspace_digest=artifact.digest,
        ).model_dump(mode="json")
    except (ValueError, TypeError) as error:
        raise SandboxError("Sandbox step checkpoint reference is invalid.") from error


def _read_evidence(
    path: str,
    raw: bytes,
    *,
    text: bool | None = None,
    output_rejected: Literal[True] | None = None,
) -> SandboxReadEvidence:
    """Fingerprint the complete file without retaining its raw body."""
    return SandboxReadEvidence(
        path=path,
        content_bytes=len(raw),
        content_sha256=_digest(raw),
        text=text,
        output_rejected=output_rejected,
    )


def _safe_summary(evidence: SandboxToolEvidence) -> str:
    if isinstance(evidence, SandboxExecEvidence):
        return f"Sandbox command exited with code {evidence.exit_code}."
    return f"Sandbox {evidence.action.value} completed."


def _failure_outcome(
    code: SandboxToolFailureCode, *, message: str
) -> SandboxToolExecutionOutcome:
    return SandboxToolExecutionOutcome(
        content=SandboxToolFailure(error=code, message=message),
        is_error=True,
        metadata=SandboxToolMetadata(sandbox_failure_code=code),
    )


def _failure_message(code: SandboxToolFailureCode) -> str:
    return {
        SandboxToolFailureCode.NOT_CONFIGURED: "No sandbox is configured for this organization.",
        SandboxToolFailureCode.ACCESS_DENIED: "Sandbox access is not granted to this agent.",
        SandboxToolFailureCode.COMMAND_TIMED_OUT: "Sandbox command timed out.",
    }.get(code, "Sandbox action failed.")


def _require_fields(arguments: dict[str, JsonValue], *, allowed: set[str]) -> None:
    if set(arguments) - allowed:
        raise SandboxToolInputError("Sandbox tool input has unsupported fields.")


def _required_text(
    arguments: dict[str, JsonValue],
    key: str,
    *,
    max_chars: int | None = None,
    allow_empty: bool = False,
) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SandboxToolInputError(f"{key} must be text.")
    if max_chars is not None and len(value) > max_chars:
        raise SandboxToolInputError(f"{key} exceeds its character ceiling.")
    return value


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "SANDBOX_TOOL_SLUGS",
    "SandboxToolExecutionOutcome",
    "execute_agent_sandbox_tool",
]
