"""Validate Groq SDK responses and assemble complete, executable tool calls."""

from enum import StrEnum

from groq.types.chat import ChatCompletion, ChatCompletionChunk
from groq.types.completion_usage import CompletionUsage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sockets.llm.schemas import (
    LLMContentBlock,
    LLMDeltaKind,
    LLMResponse,
    LLMResponseMetadata,
    LLMStopReason,
    LLMTextBlock,
    LLMTextContent,
    LLMTextDelta,
    LLMToolContent,
    LLMUsageInfo,
)
from eylo.sockets.llm.tool_content import (
    ToolCallAssemblyError,
    ToolCallBuffer,
    complete_tool_calls,
)

GROQ_VENDOR = "groq"


class GroqResponseErrorKind(StrEnum):
    """Adapter failures, without retaining vendor payloads or tool arguments."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"
    STREAM_FAILED = "stream_failed"


class GroqResponseError(RuntimeError):
    """Reject unsafe output before the platform can execute any tool call."""

    def __init__(self, kind: GroqResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"Groq response rejected: {kind.value}")


class GroqFinishReason(StrEnum):
    """Groq terminal reasons; deprecated function calls are not requested."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"


class GroqResponseMetadata(BaseModel):
    """Vendor-owned completion details; serialized before crossing the socket."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = GROQ_VENDOR
    finish_reason: GroqFinishReason
    system_fingerprint: str | None = None


_STOP_REASONS = {
    GroqFinishReason.STOP: LLMStopReason.END_TURN,
    GroqFinishReason.LENGTH: LLMStopReason.MAX_TOKENS,
    GroqFinishReason.TOOL_CALLS: LLMStopReason.TOOL_USE,
    GroqFinishReason.CONTENT_FILTER: LLMStopReason.CONTENT_FILTER,
}


def _usage(value: CompletionUsage | None) -> LLMUsageInfo | None:
    if value is None:
        return None
    try:
        return LLMUsageInfo(
            input_tokens=value.prompt_tokens,
            output_tokens=value.completion_tokens,
            cache_read_input_tokens=(
                value.prompt_tokens_details.cached_tokens
                if value.prompt_tokens_details is not None
                else None
            ),
            reasoning_tokens=(
                value.completion_tokens_details.reasoning_tokens
                if value.completion_tokens_details is not None
                else None
            ),
        )
    except ValidationError:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE) from None


def _text_blocks(text: str) -> list[LLMContentBlock]:
    return [LLMTextContent(content=LLMTextBlock(text=text))] if text else []


def _completed_tools(
    reason: GroqFinishReason, calls: list[ToolCallBuffer]
) -> list[LLMToolContent]:
    if reason == GroqFinishReason.FUNCTION_CALL:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_TOOL_CALL)
    if (reason == GroqFinishReason.TOOL_CALLS) != bool(calls):
        raise GroqResponseError(GroqResponseErrorKind.INCOMPLETE_RESPONSE)
    try:
        return complete_tool_calls(calls)
    except ToolCallAssemblyError:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_TOOL_CALL) from None


def completion_response(value: ChatCompletion) -> LLMResponse:
    """Validate SDK-constructed data instead of trusting its type annotation."""
    try:
        value = ChatCompletion.model_validate(
            value.model_dump(warnings=False), strict=True
        )
    except ValidationError:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE) from None
    if not value.id or not value.model or len(value.choices) != 1:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
    choice = value.choices[0]
    if choice.index != 0 or choice.message.function_call is not None:
        raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
    reason = GroqFinishReason(choice.finish_reason)
    calls = [
        ToolCallBuffer(
            id=call.id, name=call.function.name, arguments=call.function.arguments
        )
        for call in choice.message.tool_calls or ()
    ]
    return LLMResponse(
        id=value.id,
        model=value.model,
        content=_text_blocks(choice.message.content or "")
        + _completed_tools(reason, calls),
        stop_reason=_STOP_REASONS[reason],
        usage=_usage(value.usage),
        metadata=LLMResponseMetadata.model_validate(
            GroqResponseMetadata(
                finish_reason=reason,
                system_fingerprint=value.system_fingerprint,
            ).model_dump(mode="json")
        ),
    )


class GroqStream(BaseModel):
    """Text may stream early; tools become executable only after terminal validation."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    model: str = ""
    text: str = ""
    calls: dict[int, ToolCallBuffer] = Field(default_factory=dict)
    finish_reason: GroqFinishReason | None = None
    usage: LLMUsageInfo | None = None

    def accept(self, chunk: ChatCompletionChunk) -> LLMResponse | None:
        try:
            chunk = ChatCompletionChunk.model_validate(
                chunk.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE) from None
        if chunk.x_groq is not None and chunk.x_groq.error is not None:
            raise GroqResponseError(GroqResponseErrorKind.STREAM_FAILED)
        if self.id and chunk.id and chunk.id != self.id:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
        if self.model and chunk.model and chunk.model != self.model:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
        usage = chunk.usage
        if usage is None and chunk.x_groq is not None:
            usage = chunk.x_groq.usage
        if usage is not None:
            self.usage = _usage(usage)
        if not chunk.choices:
            return None
        if len(chunk.choices) != 1 or self.finish_reason is not None:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
        choice = chunk.choices[0]
        if choice.index != 0 or not chunk.id or not chunk.model:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_RESPONSE)
        self.id, self.model = chunk.id, chunk.model
        delta = choice.delta
        if delta.function_call is not None:
            raise GroqResponseError(GroqResponseErrorKind.INVALID_TOOL_CALL)
        for call in delta.tool_calls or ():
            if call.index < 0:
                raise GroqResponseError(GroqResponseErrorKind.INVALID_TOOL_CALL)
            try:
                self.calls.setdefault(call.index, ToolCallBuffer()).append(
                    call_id=call.id,
                    name=None if call.function is None else call.function.name,
                    arguments=None
                    if call.function is None
                    else call.function.arguments,
                )
            except ToolCallAssemblyError:
                raise GroqResponseError(
                    GroqResponseErrorKind.INVALID_TOOL_CALL
                ) from None
        if choice.finish_reason is not None:
            self.finish_reason = GroqFinishReason(choice.finish_reason)
        if not delta.content:
            return None
        self.text += delta.content
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text),
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=GROQ_VENDOR,
                streaming=True,
                delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=delta.content),
            ),
        )

    def complete(self) -> LLMResponse:
        if not self.id or self.finish_reason is None:
            raise GroqResponseError(GroqResponseErrorKind.INCOMPLETE_RESPONSE)
        calls = [value for _, value in sorted(self.calls.items())]
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text)
            + _completed_tools(self.finish_reason, calls),
            stop_reason=_STOP_REASONS[self.finish_reason],
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=GROQ_VENDOR, streaming=True, final=True
            ),
        )
