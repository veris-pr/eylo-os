"""Validate native Claude responses and assemble streams before exposing tool calls."""

import json
from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated

from anthropic.types import (
    ContentBlock,
    Message,
    RawContentBlockDeltaEvent,
    RawMessageStreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from eylo.sockets.llm.schemas import (
    LLMContentBlock,
    LLMContentType,
    LLMDeltaKind,
    LLMResponse,
    LLMResponseMetadata,
    LLMStopReason,
    LLMTextBlock,
    LLMTextContent,
    LLMTextDelta,
    LLMThinkingContent,
    LLMThinkingDelta,
    LLMToolDelta,
    LLMToolUseBlock,
    LLMUsageInfo,
)
from eylo.sockets.llm.tool_content import (
    ToolCallAssemblyError,
    ToolCallBuffer,
    complete_tool_calls,
)

ANTHROPIC_VENDOR = "anthropic"
_RAW_EVENT = TypeAdapter(Annotated[RawMessageStreamEvent, Field(discriminator="type")])
_TOOL_INPUT = TypeAdapter(dict[str, JsonValue])


class AnthropicResponseErrorKind(StrEnum):
    """Stable failure categories without retaining vendor output."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"
    UNSUPPORTED_CONTENT = "unsupported_content"


class AnthropicResponseError(RuntimeError):
    """Fail closed before any call from an invalid batch can execute."""

    def __init__(self, kind: AnthropicResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"Anthropic response rejected: {kind.value}")


class AnthropicStopReason(StrEnum):
    """Terminal outcomes in the pinned Claude Messages protocol."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"


class AnthropicStreamPhase(StrEnum):
    """Vendor stream lifecycle, separate from the platform message lifecycle."""

    WAITING = "waiting"
    CONTENT = "content"
    TAIL = "tail"
    STOPPED = "stopped"


def _invalid() -> AnthropicResponseError:
    return AnthropicResponseError(AnthropicResponseErrorKind.INVALID_RESPONSE)


def _incomplete() -> AnthropicResponseError:
    return AnthropicResponseError(AnthropicResponseErrorKind.INCOMPLETE_RESPONSE)


def _usage(value: Usage) -> LLMUsageInfo:
    try:
        return LLMUsageInfo(
            input_tokens=value.input_tokens,
            output_tokens=value.output_tokens,
            cache_creation_input_tokens=value.cache_creation_input_tokens,
            cache_read_input_tokens=value.cache_read_input_tokens,
        )
    except ValidationError:
        raise AnthropicResponseError(
            AnthropicResponseErrorKind.INVALID_RESPONSE
        ) from None


def _validated_message(value: Message) -> Message:
    if not isinstance(value, Message):
        raise _invalid()
    try:
        parsed = Message.model_validate(value.model_dump(warnings=False), strict=True)
    except ValidationError:
        raise _invalid() from None
    if not parsed.id.strip() or not parsed.model.strip():
        raise _invalid()
    _usage(parsed.usage)
    return parsed


def _text_content(block: TextBlock | ThinkingBlock) -> LLMContentBlock:
    if block.type == "text":
        return LLMTextContent(content=LLMTextBlock(text=block.text))
    return LLMThinkingContent(content=LLMTextBlock(text=block.thinking))


def message_response(value: Message) -> LLMResponse:
    """Validate SDK-constructed data and the complete tool batch, not just annotations."""
    value = _validated_message(value)
    if value.stop_reason is None:
        raise _incomplete()
    reason = AnthropicStopReason(value.stop_reason)
    calls: list[ToolCallBuffer] = []
    for block in value.content:
        if block.type == "tool_use":
            try:
                arguments = _TOOL_INPUT.validate_python(block.input, strict=True)
                serialized = json.dumps(arguments, allow_nan=False)
            except (TypeError, ValueError):
                raise AnthropicResponseError(
                    AnthropicResponseErrorKind.INVALID_TOOL_CALL
                ) from None
            calls.append(
                ToolCallBuffer(id=block.id, name=block.name, arguments=serialized)
            )
        elif block.type not in ("text", "thinking", "redacted_thinking"):
            # Hosted tools are not configured by this platform adapter.
            raise AnthropicResponseError(AnthropicResponseErrorKind.UNSUPPORTED_CONTENT)
    if reason is AnthropicStopReason.PAUSE_TURN:
        raise _incomplete()
    if (reason is AnthropicStopReason.TOOL_USE) != bool(calls):
        raise _incomplete()
    try:
        tools = iter(complete_tool_calls(calls))
    except ToolCallAssemblyError:
        raise AnthropicResponseError(
            AnthropicResponseErrorKind.INVALID_TOOL_CALL
        ) from None
    content: list[LLMContentBlock] = []
    for block in value.content:
        if isinstance(block, TextBlock | ThinkingBlock):
            content.append(_text_content(block))
        elif block.type == "tool_use":
            content.append(next(tools))
        # Redacted thinking is opaque, not user text or executable content.
    return LLMResponse(
        id=value.id,
        model=value.model,
        content=content,
        stop_reason=LLMStopReason(reason.value),
        usage=_usage(value.usage),
        metadata=LLMResponseMetadata(vendor=ANTHROPIC_VENDOR),
    )


class AnthropicMessageStream(BaseModel):
    """Text/thinking snapshots contain no tools; message_stop seals the tool batch."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    phase: AnthropicStreamPhase = AnthropicStreamPhase.WAITING
    message: Message | None = None
    blocks: dict[int, ContentBlock] = Field(default_factory=dict)
    open_blocks: set[int] = Field(default_factory=set)
    calls: dict[int, ToolCallBuffer] = Field(default_factory=dict)

    def accept(self, event: RawMessageStreamEvent) -> LLMResponse | None:
        try:
            # An unknown event can be returned as a dict by the SDK's permissive
            # constructor. Validate that boundary instead of reflecting on it.
            payload: object = (
                event.model_dump(warnings=False)
                if isinstance(event, BaseModel)
                else event
            )
            event = _RAW_EVENT.validate_python(payload, strict=True)
        except ValidationError:
            raise _invalid() from None
        if self.phase is AnthropicStreamPhase.STOPPED:
            raise _invalid()
        if event.type == "message_start":
            if self.phase is not AnthropicStreamPhase.WAITING:
                raise _invalid()
            message = _validated_message(event.message)
            if message.content or message.stop_reason is not None:
                raise _invalid()
            self.message = message
            self.phase = AnthropicStreamPhase.CONTENT
            return None
        message = self.message
        if message is None:
            raise _invalid()
        if event.type == "content_block_start":
            if self.phase is not AnthropicStreamPhase.CONTENT or event.index != len(
                self.blocks
            ):
                raise _invalid()
            block = event.content_block
            if block.type == "tool_use":
                # The start input is a placeholder, never authoritative arguments.
                if block.input != {} or not block.id.strip() or not block.name.strip():
                    raise AnthropicResponseError(
                        AnthropicResponseErrorKind.INVALID_TOOL_CALL
                    )
                self.calls[event.index] = ToolCallBuffer(id=block.id, name=block.name)
            elif block.type not in ("text", "thinking", "redacted_thinking"):
                raise AnthropicResponseError(
                    AnthropicResponseErrorKind.UNSUPPORTED_CONTENT
                )
            self.blocks[event.index] = block
            self.open_blocks.add(event.index)
        elif event.type == "content_block_delta":
            return self._content_delta(event)
        elif event.type == "content_block_stop":
            if (
                self.phase is not AnthropicStreamPhase.CONTENT
                or event.index not in self.open_blocks
            ):
                raise _invalid()
            self.open_blocks.remove(event.index)
        elif event.type == "message_delta":
            if self.open_blocks:
                raise _invalid()
            if self.phase not in (
                AnthropicStreamPhase.CONTENT,
                AnthropicStreamPhase.TAIL,
            ):
                raise _invalid()
            if event.delta.stop_reason is not None:
                if (
                    message.stop_reason is not None
                    and message.stop_reason != event.delta.stop_reason
                ):
                    raise _invalid()
                message.stop_reason = event.delta.stop_reason
            message.stop_sequence = event.delta.stop_sequence
            usage = event.usage
            message.usage.output_tokens = usage.output_tokens
            if usage.input_tokens is not None:
                message.usage.input_tokens = usage.input_tokens
            if usage.cache_creation_input_tokens is not None:
                message.usage.cache_creation_input_tokens = (
                    usage.cache_creation_input_tokens
                )
            if usage.cache_read_input_tokens is not None:
                message.usage.cache_read_input_tokens = usage.cache_read_input_tokens
            _usage(message.usage)
            self.phase = AnthropicStreamPhase.TAIL
        elif event.type == "message_stop":
            if (
                self.phase is not AnthropicStreamPhase.TAIL
                or message.stop_reason is None
            ):
                raise _incomplete()
            self.phase = AnthropicStreamPhase.STOPPED
        return None

    def _content_delta(self, event: RawContentBlockDeltaEvent) -> LLMResponse | None:
        if (
            self.phase is not AnthropicStreamPhase.CONTENT
            or event.index not in self.open_blocks
        ):
            raise _invalid()
        block = self.blocks[event.index]
        delta = event.delta
        if delta.type == "text_delta" and block.type == "text":
            block.text += delta.text
            return self._progress(
                LLMTextDelta(
                    type=LLMDeltaKind.TEXT, block_index=event.index, text=delta.text
                )
            )
        if delta.type == "thinking_delta" and block.type == "thinking":
            block.thinking += delta.thinking
            return self._progress(
                LLMThinkingDelta(
                    type=LLMDeltaKind.THINKING,
                    block_index=event.index,
                    text=delta.thinking,
                )
            )
        if delta.type == "signature_delta" and block.type == "thinking":
            block.signature += delta.signature
        elif delta.type == "input_json_delta" and block.type == "tool_use":
            self.calls[event.index].append(
                call_id=None, name=None, arguments=delta.partial_json
            )
        elif delta.type == "citations_delta" and block.type == "text":
            block.citations = [*(block.citations or ()), delta.citation]
        else:
            raise _invalid()
        return None

    def _progress(self, delta: LLMTextDelta | LLMThinkingDelta) -> LLMResponse:
        message = self.message
        if message is None:
            raise _invalid()
        return LLMResponse(
            id=message.id,
            model=message.model,
            content=[
                _text_content(block)
                for block in self.blocks.values()
                if isinstance(block, TextBlock | ThinkingBlock)
            ],
            usage=_usage(message.usage),
            metadata=LLMResponseMetadata(
                vendor=ANTHROPIC_VENDOR, streaming=True, delta=delta
            ),
        )

    def finish(self) -> LLMResponse:
        """Called after stream/client cleanup; no EOF fallback can authorize tools."""
        message = self.message
        if self.phase is not AnthropicStreamPhase.STOPPED or message is None:
            raise _incomplete()
        try:
            completed = complete_tool_calls(list(self.calls.values()))
        except ToolCallAssemblyError:
            raise AnthropicResponseError(
                AnthropicResponseErrorKind.INVALID_TOOL_CALL
            ) from None
        for index, completed_block in zip(self.calls, completed, strict=True):
            call = completed_block.content
            if not isinstance(call, LLMToolUseBlock):
                raise _invalid()
            self.blocks[index] = ToolUseBlock(
                type="tool_use", id=call.id, name=call.name, input=call.input
            )
        message.content = list(self.blocks.values())
        final = message_response(message)
        final.metadata = LLMResponseMetadata(vendor=ANTHROPIC_VENDOR, streaming=False)
        return final

    def tool_completions(self, final: LLMResponse) -> Iterator[LLMResponse]:
        """Preserve existing completion envelopes, but only for an already sealed batch."""
        tools = [
            block for block in final.content if block.type is LLMContentType.TOOL_USE
        ]
        prefix: list[LLMContentBlock] = [
            block
            for block in final.content
            if block.type is not LLMContentType.TOOL_USE
        ]
        for index, block in zip(self.calls, tools, strict=True):
            call = block.content
            if not isinstance(call, LLMToolUseBlock):
                raise _invalid()
            prefix.append(block)
            yield LLMResponse(
                id=final.id,
                model=final.model,
                content=list(prefix),
                usage=final.usage,
                metadata=LLMResponseMetadata(
                    vendor=ANTHROPIC_VENDOR,
                    streaming=True,
                    delta=LLMToolDelta(
                        type=LLMDeltaKind.TOOL_USE_COMPLETE,
                        block_index=index,
                        tool_id=call.id,
                        tool_name=call.name,
                        tool_input=call.input,
                    ),
                ),
            )
