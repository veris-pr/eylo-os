"""Validate Sarvam SDK responses and assemble complete, executable tool calls."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sarvamai.types.chat_completion_chunk import ChatCompletionChunk
from sarvamai.types.completion_usage import CompletionUsage
from sarvamai.types.create_chat_completion_response import CreateChatCompletionResponse

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

SARVAM_VENDOR = "sarvam"


class SarvamResponseErrorKind(StrEnum):
    """Adapter failures, without retaining vendor payloads or tool arguments."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"


class SarvamResponseError(RuntimeError):
    """Reject unsafe output before the platform can execute any tool call."""

    def __init__(self, kind: SarvamResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"Sarvam response rejected: {kind.value}")


class SarvamFinishReason(StrEnum):
    """Sarvam terminal reasons; deprecated function calls are not requested."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"


class SarvamResponseMetadata(BaseModel):
    """Vendor-owned completion details; serialized before crossing the socket."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = SARVAM_VENDOR
    finish_reason: SarvamFinishReason
    system_fingerprint: str | None = None


_STOP_REASONS = {
    SarvamFinishReason.STOP: LLMStopReason.END_TURN,
    SarvamFinishReason.LENGTH: LLMStopReason.MAX_TOKENS,
    SarvamFinishReason.TOOL_CALLS: LLMStopReason.TOOL_USE,
    SarvamFinishReason.CONTENT_FILTER: LLMStopReason.CONTENT_FILTER,
}


def _finish_reason(value: object) -> SarvamFinishReason:
    """The SDK allows Any in this field; narrow it before using it as a state."""
    if not isinstance(value, str):
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
    try:
        return SarvamFinishReason(value)
    except ValueError:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE) from None


def _usage(value: CompletionUsage | None) -> LLMUsageInfo | None:
    if value is None:
        return None
    try:
        return LLMUsageInfo(
            input_tokens=value.prompt_tokens,
            output_tokens=value.completion_tokens,
        )
    except ValidationError:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE) from None


def _text_blocks(text: str) -> list[LLMContentBlock]:
    return [LLMTextContent(content=LLMTextBlock(text=text))] if text else []


def _completed_tools(
    reason: SarvamFinishReason, calls: list[ToolCallBuffer]
) -> list[LLMToolContent]:
    if reason == SarvamFinishReason.FUNCTION_CALL:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_TOOL_CALL)
    if (reason == SarvamFinishReason.TOOL_CALLS) != bool(calls):
        raise SarvamResponseError(SarvamResponseErrorKind.INCOMPLETE_RESPONSE)
    try:
        return complete_tool_calls(calls)
    except ToolCallAssemblyError:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_TOOL_CALL) from None


def completion_response(value: CreateChatCompletionResponse) -> LLMResponse:
    """Validate SDK-constructed data instead of trusting its type annotation."""
    try:
        value = CreateChatCompletionResponse.model_validate(
            value.model_dump(warnings=False), strict=True
        )
    except ValidationError:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE) from None
    if not value.id or not value.model or len(value.choices) != 1:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
    choice = value.choices[0]
    if choice.index != 0:
        raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
    reason = _finish_reason(choice.finish_reason)
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
            SarvamResponseMetadata(
                finish_reason=reason,
                system_fingerprint=value.system_fingerprint,
            ).model_dump(mode="json")
        ),
    )


class SarvamStream(BaseModel):
    """Text may stream early; tools become executable only after terminal validation."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    model: str = ""
    text: str = ""
    calls: dict[int, ToolCallBuffer] = Field(default_factory=dict)
    finish_reason: SarvamFinishReason | None = None
    usage: LLMUsageInfo | None = None

    def accept(self, chunk: ChatCompletionChunk) -> LLMResponse | None:
        try:
            chunk = ChatCompletionChunk.model_validate(
                chunk.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise SarvamResponseError(
                SarvamResponseErrorKind.INVALID_RESPONSE
            ) from None
        if self.id and chunk.id and chunk.id != self.id:
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
        if self.model and chunk.model and chunk.model != self.model:
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
        usage = chunk.usage
        if usage is not None:
            self.usage = _usage(usage)
        if not chunk.choices:
            return None
        if len(chunk.choices) != 1 or self.finish_reason is not None:
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
        choice = chunk.choices[0]
        if choice.index != 0 or not chunk.id or not chunk.model:
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
        self.id, self.model = chunk.id, chunk.model
        delta = choice.delta
        if delta.role is not None and delta.role != "assistant":
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_RESPONSE)
        if delta.function_call is not None:
            raise SarvamResponseError(SarvamResponseErrorKind.INVALID_TOOL_CALL)
        for call in delta.tool_calls or ():
            if call.index < 0:
                raise SarvamResponseError(SarvamResponseErrorKind.INVALID_TOOL_CALL)
            try:
                self.calls.setdefault(call.index, ToolCallBuffer()).append(
                    call_id=call.id,
                    name=None if call.function is None else call.function.name,
                    arguments=None
                    if call.function is None
                    else call.function.arguments,
                )
            except ToolCallAssemblyError:
                raise SarvamResponseError(
                    SarvamResponseErrorKind.INVALID_TOOL_CALL
                ) from None
        if choice.finish_reason is not None:
            self.finish_reason = _finish_reason(choice.finish_reason)
        if not delta.content:
            return None
        self.text += delta.content
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text),
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=SARVAM_VENDOR,
                streaming=True,
                delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=delta.content),
            ),
        )

    def complete(self) -> LLMResponse:
        if not self.id or self.finish_reason is None:
            raise SarvamResponseError(SarvamResponseErrorKind.INCOMPLETE_RESPONSE)
        calls = [value for _, value in sorted(self.calls.items())]
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text)
            + _completed_tools(self.finish_reason, calls),
            stop_reason=_STOP_REASONS[self.finish_reason],
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=SARVAM_VENDOR, streaming=True, final=True
            ),
        )
