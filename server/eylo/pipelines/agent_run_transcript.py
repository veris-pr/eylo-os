"""Private durable replay history for non-conversation AgentRuns."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import ClassVar, Final, Generic
from uuid import UUID

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError
from sqlalchemy import func, select

from eylo.common.database import get_transaction
from eylo.framework.agents.common import FrameworkMetadata
from eylo.framework.agents.context import RunContext, RunInput, RunMessage
from eylo.framework.agents.history import tool_exchange_messages
from eylo.framework.agents.model import (
    Model,
    ModelBlockKind,
    ModelResponse,
    ModelSettings,
    ModelStopReason,
    ModelToolCallBlock,
    ModelUsage,
)
from eylo.framework.agents.tool import ToolCall, ToolResult
from eylo.modules.agent_runs.domain import AgentRunTranscriptKind
from eylo.modules.agent_runs.models import (
    AgentRunModel,
    AgentRunTranscriptItemModel,
)
from eylo.pipelines.agent_execution_context import ContextT, PlatformRunState
from eylo.pipelines.agent_run_tools import bind_agent_run_tool_command

_MAX_PAYLOAD_BYTES: Final = 65_536
_REPLAY_REQUEST_ID = TypeAdapter(UUID, config=ConfigDict(hide_input_in_errors=True))


class AgentRunTranscriptError(ValueError):
    """Private replay history is invalid or exceeds its whole-item ceiling."""


class _TranscriptPayload(BaseModel):
    """Owned row envelope; dynamic vendor/tool fields remain inside their payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TranscriptAssistantText(_TranscriptPayload):
    """Model text stored before its accompanying tool calls execute."""

    kind: ClassVar[AgentRunTranscriptKind] = AgentRunTranscriptKind.ASSISTANT_TEXT
    text: str
    response_id: str


class TranscriptToolCall(_TranscriptPayload):
    """Exact model command retained for replay and durable-effect correlation."""

    kind: ClassVar[AgentRunTranscriptKind] = AgentRunTranscriptKind.TOOL_CALL
    tool_call: ToolCall
    response_id: str


class TranscriptToolResult(_TranscriptPayload):
    """Completed command result; pause/approval signals are not completion."""

    kind: ClassVar[AgentRunTranscriptKind] = AgentRunTranscriptKind.TOOL_RESULT
    tool_result: ToolResult


type TranscriptPayload = (
    TranscriptAssistantText | TranscriptToolCall | TranscriptToolResult
)


class TranscriptMessageMetadata(FrameworkMetadata):
    """Marks a message reconstructed from private durable history."""

    agent_run_transcript: bool = True
    request_id: UUID | None = None


class TranscriptCallMessageMetadata(TranscriptMessageMetadata):
    """Replay tool calls retain their framework-owned request contract."""

    tool_call: ToolCall


class TranscriptResultMessageMetadata(TranscriptMessageMetadata):
    """Replay tool results retain their framework-owned response contract."""

    tool_result: ToolResult


class AgentRunToolCapture(BaseModel):
    """Transient last-response calls used to correlate pauses and completion.

    None means no response was captured; an empty tuple is a captured response
    without tool calls. Durable replay remains owned by AgentRunTranscript.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_calls: tuple[ToolCall, ...] | None = None


class AgentRunTranscriptReplay(BaseModel):
    """Validated private history and the exact commands still awaiting results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: tuple[RunMessage, ...]
    pending_calls: tuple[ToolCall, ...]
    command_ids: dict[str, UUID]


class AgentRunTranscript:
    """Append and replay canonical model/tool exchange for one AgentRun."""

    def __init__(self, *, organization_id: UUID, agent_run_id: UUID) -> None:
        self.organization_id = organization_id
        self.agent_run_id = agent_run_id

    async def replay(self) -> AgentRunTranscriptReplay:
        rows = list(
            (
                await get_transaction().execute(
                    select(AgentRunTranscriptItemModel)
                    .where(
                        AgentRunTranscriptItemModel.organization_id
                        == self.organization_id,
                        AgentRunTranscriptItemModel.run_id == self.agent_run_id,
                        AgentRunTranscriptItemModel.deleted.is_(False),
                    )
                    .order_by(
                        AgentRunTranscriptItemModel.sequence,
                        AgentRunTranscriptItemModel.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        resolved = {
            row.correlation_id
            for row in rows
            if row.kind == AgentRunTranscriptKind.TOOL_RESULT
            and row.correlation_id is not None
        }
        recorded_calls = {
            row.correlation_id
            for row in rows
            if row.kind == AgentRunTranscriptKind.TOOL_CALL
        }
        if not resolved.issubset(recorded_calls):
            raise AgentRunTranscriptError("AgentRun history contains an orphan result.")
        pending_rows = [
            row
            for row in rows
            if row.kind == AgentRunTranscriptKind.TOOL_CALL
            and row.correlation_id not in resolved
        ]
        pending_ids = {row.id for row in pending_rows}
        messages = tuple(
            _message_from_row(row) for row in rows if row.id not in pending_ids
        )
        pending_calls = tuple(_tool_call_from_row(row) for row in pending_rows)
        command_ids = {
            _tool_call_from_row(row).id: UUID(str(row.id))
            for row in rows
            if row.kind == AgentRunTranscriptKind.TOOL_CALL
        }
        return AgentRunTranscriptReplay(
            messages=messages,
            pending_calls=pending_calls,
            command_ids=command_ids,
        )

    async def record_model_response(
        self,
        response: ModelResponse,
        tool_calls: tuple[ToolCall, ...],
    ) -> dict[str, UUID]:
        text = "\n".join(
            block.content
            for block in response.blocks
            if block.kind is ModelBlockKind.TEXT and block.content
        )
        if text:
            await self._append(
                correlation_id=_correlation(f"{response.id}:text"),
                payload=TranscriptAssistantText(text=text, response_id=response.id),
            )

        command_ids: dict[str, UUID] = {}
        for call in tool_calls:
            row = await self._append(
                correlation_id=_correlation(call.id),
                payload=TranscriptToolCall(tool_call=call, response_id=response.id),
            )
            command_ids[call.id] = UUID(str(row.id))
        await get_transaction().commit()
        return command_ids

    async def record_tool_result(
        self,
        call: ToolCall,
        result: ToolResult,
    ) -> AgentRunTranscriptItemModel | None:
        if result.tool_call_id != call.id:
            raise AgentRunTranscriptError(
                "AgentRun result does not belong to the invocation being completed."
            )
        if _is_pause_result(result):
            return None
        row = await self._append(
            correlation_id=_correlation(call.id),
            payload=TranscriptToolResult(tool_result=result),
        )
        await get_transaction().commit()
        return row

    async def tool_result(self, call: ToolCall) -> ToolResult | None:
        row = await get_transaction().scalar(
            select(AgentRunTranscriptItemModel).where(
                AgentRunTranscriptItemModel.organization_id == self.organization_id,
                AgentRunTranscriptItemModel.run_id == self.agent_run_id,
                AgentRunTranscriptItemModel.kind
                == AgentRunTranscriptKind.TOOL_RESULT.value,
                AgentRunTranscriptItemModel.correlation_id == _correlation(call.id),
                AgentRunTranscriptItemModel.deleted.is_(False),
            )
        )
        if row is None:
            return None
        payload = _payload_from_row(row)
        if not isinstance(payload, TranscriptToolResult):
            raise AgentRunTranscriptError("AgentRun transcript result kind is invalid.")
        if payload.tool_result.tool_call_id != call.id:
            raise AgentRunTranscriptError("AgentRun result identity is invalid.")
        await self._require_tool_call(row.correlation_id)
        return payload.tool_result

    async def _require_tool_call(self, correlation_id: str | None) -> ToolCall:
        """Read one same-owner command; never create or repair missing history."""
        row = await get_transaction().scalar(
            select(AgentRunTranscriptItemModel).where(
                AgentRunTranscriptItemModel.organization_id == self.organization_id,
                AgentRunTranscriptItemModel.run_id == self.agent_run_id,
                AgentRunTranscriptItemModel.kind
                == AgentRunTranscriptKind.TOOL_CALL.value,
                AgentRunTranscriptItemModel.correlation_id == correlation_id,
                AgentRunTranscriptItemModel.deleted.is_(False),
            )
        )
        if row is None:
            raise AgentRunTranscriptError("AgentRun result has no persisted tool call.")
        return _tool_call_from_row(row)

    async def _append(
        self,
        *,
        correlation_id: str | None,
        payload: TranscriptPayload,
    ) -> AgentRunTranscriptItemModel:
        try:
            stored_payload = payload.model_dump(mode="json")
            _require_finite_numbers(payload.model_dump(mode="python"))
        except (PydanticSerializationError, ValueError):
            raise AgentRunTranscriptError(
                "AgentRun transcript payload is not JSON-safe."
            ) from None
        _require_bounded_payload(stored_payload)
        kind = payload.kind
        session = get_transaction()
        # Lock before the identity lookup: concurrent retries must see the
        # previous writer's committed item, not both decide to insert it.
        run = await session.scalar(
            select(AgentRunModel)
            .where(
                AgentRunModel.id == self.agent_run_id,
                AgentRunModel.organization_id == self.organization_id,
                AgentRunModel.deleted.is_(False),
            )
            .with_for_update()
        )
        if run is None:
            raise AgentRunTranscriptError("AgentRun transcript owner is unavailable.")
        if isinstance(payload, TranscriptToolResult):
            await self._require_tool_call(correlation_id)
        existing = None
        if correlation_id is not None:
            existing = await session.scalar(
                select(AgentRunTranscriptItemModel).where(
                    AgentRunTranscriptItemModel.organization_id == self.organization_id,
                    AgentRunTranscriptItemModel.run_id == self.agent_run_id,
                    AgentRunTranscriptItemModel.kind == kind.value,
                    AgentRunTranscriptItemModel.correlation_id == correlation_id,
                    AgentRunTranscriptItemModel.deleted.is_(False),
                )
            )
        if existing is not None:
            if existing.payload != stored_payload:
                raise AgentRunTranscriptError(
                    "AgentRun transcript identity has different content."
                )
            return existing

        sequence = (
            await session.scalar(
                select(
                    func.coalesce(func.max(AgentRunTranscriptItemModel.sequence), 0)
                ).where(
                    AgentRunTranscriptItemModel.organization_id == self.organization_id,
                    AgentRunTranscriptItemModel.run_id == self.agent_run_id,
                    AgentRunTranscriptItemModel.deleted.is_(False),
                )
            )
            or 0
        ) + 1
        row = AgentRunTranscriptItemModel(
            organization_id=self.organization_id,
            run_id=self.agent_run_id,
            sequence=sequence,
            kind=kind.value,
            correlation_id=correlation_id,
            payload=stored_payload,
        )
        session.add(row)
        await session.flush()
        return row


class AgentRunTranscriptBridge(Generic[ContextT]):
    """Framework callbacks that make non-conversation tool loops replayable."""

    def __init__(
        self,
        *,
        transcript: AgentRunTranscript,
        local_context: PlatformRunState[ContextT],
        command_ids: dict[str, UUID],
    ) -> None:
        self.transcript = transcript
        self.local_context = local_context
        self.command_ids = command_ids

    async def after_model_response(
        self,
        _context: RunContext,
        _run_input: RunInput,
        response: ModelResponse,
        tool_calls: tuple[ToolCall, ...],
    ) -> None:
        new_tool_calls = tuple(
            call for call in tool_calls if call.id not in self.command_ids
        )
        if not new_tool_calls:
            return
        self.command_ids.update(
            await self.transcript.record_model_response(response, new_tool_calls)
        )

    async def before_tool_call(
        self,
        _context: RunContext,
        call: ToolCall,
        _response: ModelResponse,
    ) -> None:
        command_id = self.command_ids.get(call.id)
        if command_id is None:
            raise AgentRunTranscriptError(
                "Tool call has no persisted AgentRun command identity."
            )
        bind_agent_run_tool_command(
            self.local_context,
            call=call,
            command_id=command_id,
        )

    async def after_tool_result(
        self,
        _context: RunContext,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        await self.transcript.record_tool_result(call, result)


class PendingToolCallsModel:
    """Replay unresolved persisted calls once, then delegate to the real model."""

    def __init__(
        self,
        delegate: Model,
        *,
        agent_run_id: UUID,
        pending_calls: tuple[ToolCall, ...],
    ) -> None:
        self._delegate = delegate
        self._agent_run_id = agent_run_id
        self._pending_calls = pending_calls

    async def generate(
        self,
        run_input: RunInput,
        settings: ModelSettings,
    ) -> ModelResponse:
        if self._pending_calls:
            calls = self._pending_calls
            self._pending_calls = ()
            return ModelResponse(
                id=f"agent-run-replay-{self._agent_run_id}",
                model=settings.model or "agent-run-replay",
                blocks=tuple(
                    ModelToolCallBlock(
                        content=call,
                    )
                    for call in calls
                ),
                usage=ModelUsage(),
                stop_reason=ModelStopReason.TOOL_USE,
            )
        return await self._delegate.generate(run_input, settings)


def with_replay_messages(
    run_input: RunInput, replay: AgentRunTranscriptReplay
) -> RunInput:
    """Attach private history to this input's request, preserving command identity.

    The transcript belongs to a durable run, not a conversation request. The
    caller supplies that correlation at execution time; inventing it per replay
    message would split tool calls from results in vendor history grouping.
    """
    messages = replay.messages
    if messages:
        try:
            request_id = _REPLAY_REQUEST_ID.validate_python(
                run_input.metadata.get("request_id")
            )
        except ValidationError as error:
            raise AgentRunTranscriptError(
                "AgentRun replay requires a valid request identity."
            ) from error
        messages = tuple(
            message.model_copy(
                update={
                    "metadata": message.metadata.model_copy(
                        update={"request_id": request_id}
                    )
                }
            )
            for message in messages
        )
    return run_input.model_copy(update={"messages": (*run_input.messages, *messages)})


def append_resumed_tool_exchange(
    run_input: RunInput, call: ToolCall, result: ToolResult
) -> RunInput:
    """Append one resumed exchange without changing replay or transient ownership."""
    raw_request_id = run_input.metadata.get("request_id")
    request_id = (
        None
        if raw_request_id is None or raw_request_id == ""
        else _REPLAY_REQUEST_ID.validate_python(raw_request_id)
    )
    content = (
        result.content
        if isinstance(result.content, str)
        else json.dumps(result.content, ensure_ascii=False, separators=(",", ":"))
    )
    messages = tool_exchange_messages(
        call, result, request_id=request_id, result_text=content
    )
    return run_input.model_copy(update={"messages": (*run_input.messages, *messages)})


def _payload_from_row(row: AgentRunTranscriptItemModel) -> TranscriptPayload:
    """Validate an owned row before accessing fields; never guess a payload kind."""
    try:
        kind = AgentRunTranscriptKind(row.kind)
        if kind is AgentRunTranscriptKind.ASSISTANT_TEXT:
            text_payload = TranscriptAssistantText.model_validate(row.payload)
            expected_correlation = _correlation(f"{text_payload.response_id}:text")
            payload: TranscriptPayload = text_payload
        elif kind is AgentRunTranscriptKind.TOOL_CALL:
            payload = TranscriptToolCall.model_validate(row.payload)
            expected_correlation = _correlation(payload.tool_call.id)
        else:
            payload = TranscriptToolResult.model_validate(row.payload)
            expected_correlation = _correlation(payload.tool_result.tool_call_id)
        if row.correlation_id != expected_correlation:
            raise AgentRunTranscriptError("AgentRun transcript correlation is invalid.")
        return payload
    except ValueError:
        raise AgentRunTranscriptError(
            "AgentRun transcript payload is invalid."
        ) from None


def _tool_call_from_row(row: AgentRunTranscriptItemModel) -> ToolCall:
    payload = _payload_from_row(row)
    if not isinstance(payload, TranscriptToolCall):
        raise AgentRunTranscriptError("AgentRun transcript call kind is invalid.")
    return payload.tool_call


def _message_from_row(row: AgentRunTranscriptItemModel) -> RunMessage:
    payload = _payload_from_row(row)
    if isinstance(payload, TranscriptAssistantText):
        return RunMessage(
            id=row.id,
            role="assistant",
            content=payload.text,
            metadata=TranscriptMessageMetadata(),
        )
    if isinstance(payload, TranscriptToolCall):
        call = payload.tool_call
        return RunMessage(
            id=row.id,
            role="assistant",
            content=f"Tool call: {call.name}",
            metadata=TranscriptCallMessageMetadata(tool_call=call),
        )
    result = payload.tool_result
    content = (
        result.content
        if isinstance(result.content, str)
        else json.dumps(
            result.content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return RunMessage(
        id=row.id,
        role="tool",
        content=content,
        metadata=TranscriptResultMessageMetadata(tool_result=result),
    )


def _is_pause_result(result: ToolResult) -> bool:
    return bool(
        result.metadata.get("tool_execution_paused")
        or result.metadata.get("approval_request")
        or result.metadata.get("input_request")
        or result.metadata.get("tool_execution_failed")
    )


def _correlation(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_finite_numbers(value: object) -> None:
    """Refuse lossy null conversion, including independently serialized metadata."""
    if isinstance(value, float) and not math.isfinite(value):
        raise AgentRunTranscriptError("AgentRun transcript payload is not JSON-safe.")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_finite_numbers(key)
            _require_finite_numbers(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _require_finite_numbers(item)


def _require_bounded_payload(payload: object) -> None:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AgentRunTranscriptError(
            "AgentRun transcript payload is not JSON-safe."
        ) from error
    if len(encoded) > _MAX_PAYLOAD_BYTES:
        raise AgentRunTranscriptError(
            f"AgentRun transcript item exceeds {_MAX_PAYLOAD_BYTES} encoded bytes."
        )


__all__ = [
    "AgentRunToolCapture",
    "AgentRunTranscript",
    "AgentRunTranscriptBridge",
    "AgentRunTranscriptError",
    "AgentRunTranscriptReplay",
    "PendingToolCallsModel",
    "with_replay_messages",
]
