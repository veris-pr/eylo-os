"""Normalize native Cerebras completions/chunks/errors without OpenAI SDK types."""

from enum import StrEnum

from cerebras.cloud.sdk.types.chat.chat_completion import (
    ChatChunkResponse,
    ChatChunkResponseUsage,
    ChatCompletion,
    ChatCompletionResponse,
    ChatCompletionResponseTimeInfo,
    ChatCompletionResponseUsage,
    ErrorChunkResponse,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sockets.llm.schemas import (
    LLMContentBlock,
    LLMDeltaKind,
    LLMResponse,
    LLMResponseMetadata,
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

CEREBRAS_VENDOR = "cerebras"


class CerebrasResponseErrorKind(StrEnum):
    """Typed failures; vendor text and tool arguments do not enter diagnostics."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"
    VENDOR_ERROR = "vendor_error"


class CerebrasResponseError(RuntimeError):
    """Refuse unsafe native output without retaining its payload in diagnostics."""

    def __init__(self, kind: CerebrasResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"Cerebras response rejected: {kind.value}")


class CerebrasFinishReason(StrEnum):
    """Terminal reasons supported by the native chat API, not platform states."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"


class CerebrasResponseMetadata(BaseModel):
    """Native timing and terminal details remain owned by Cerebras."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = CEREBRAS_VENDOR
    finish_reason: CerebrasFinishReason
    system_fingerprint: str | None
    time_info: ChatCompletionResponseTimeInfo


_STOP_REASONS = {
    CerebrasFinishReason.STOP: "end_turn",
    CerebrasFinishReason.LENGTH: "max_tokens",
    CerebrasFinishReason.TOOL_CALLS: "tool_use",
    CerebrasFinishReason.CONTENT_FILTER: "content_filter",
}


class CerebrasReasoningUsage(BaseModel):
    """Documented completion-details extension missing from SDK 1.67.0's fields."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)
    reasoning_tokens: int | None = Field(default=None, ge=0)


def _usage(
    value: ChatCompletionResponseUsage | ChatChunkResponseUsage | None,
) -> LLMUsageInfo | None:
    if value is None:
        return None
    cached_tokens = (
        value.prompt_tokens_details.cached_tokens
        if value.prompt_tokens_details is not None
        else None
    )
    counts = (value.prompt_tokens, value.completion_tokens, cached_tokens)
    if any(
        count is not None and (type(count) is not int or count < 0) for count in counts
    ):
        raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
    reasoning_tokens = None
    if value.completion_tokens_details is not None:
        try:
            extension = CerebrasReasoningUsage.model_validate(
                value.completion_tokens_details.model_dump(warnings=False)
            )
        except ValidationError:
            raise CerebrasResponseError(
                CerebrasResponseErrorKind.INVALID_RESPONSE
            ) from None
        reasoning_tokens = extension.reasoning_tokens
    if value.prompt_tokens is None or value.completion_tokens is None:
        return None
    try:
        return LLMUsageInfo(
            input_tokens=value.prompt_tokens,
            output_tokens=value.completion_tokens,
            cache_read_input_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
        )
    except ValidationError:
        raise CerebrasResponseError(
            CerebrasResponseErrorKind.INVALID_RESPONSE
        ) from None


def _text_blocks(text: str) -> list[LLMContentBlock]:
    if not text:
        return []
    return [LLMTextContent(content=LLMTextBlock(text=text))]


def _completed_tools(
    reason: CerebrasFinishReason, calls: list[ToolCallBuffer]
) -> list[LLMToolContent]:
    if (reason == CerebrasFinishReason.TOOL_CALLS) != bool(calls):
        raise CerebrasResponseError(CerebrasResponseErrorKind.INCOMPLETE_RESPONSE)
    try:
        return complete_tool_calls(calls)
    except ToolCallAssemblyError:
        raise CerebrasResponseError(
            CerebrasResponseErrorKind.INVALID_TOOL_CALL
        ) from None


def completion_response(value: ChatCompletion) -> LLMResponse:
    if isinstance(value, ErrorChunkResponse):
        raise CerebrasResponseError(CerebrasResponseErrorKind.VENDOR_ERROR)
    if not isinstance(value, ChatCompletionResponse):
        raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
    try:
        value = ChatCompletionResponse.model_validate(
            value.model_dump(warnings=False), strict=True
        )
    except ValidationError:
        raise CerebrasResponseError(
            CerebrasResponseErrorKind.INVALID_RESPONSE
        ) from None
    if not value.id or not value.model or len(value.choices) != 1:
        raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
    choice = value.choices[0]
    if choice.index != 0 or choice.message.role != "assistant":
        raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
    reason = CerebrasFinishReason(choice.finish_reason)
    calls = [
        ToolCallBuffer(
            id=call.id,
            name=call.function.name,
            arguments=call.function.arguments,
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
            CerebrasResponseMetadata(
                finish_reason=reason,
                system_fingerprint=value.system_fingerprint,
                time_info=value.time_info,
            ).model_dump(mode="json")
        ),
    )


class CerebrasStream(BaseModel):
    """Own Cerebras terminal semantics; never execute a partial tool-call batch."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    model: str = ""
    text: str = ""
    calls: dict[int, ToolCallBuffer] = Field(default_factory=dict)
    finish_reason: CerebrasFinishReason | None = None
    usage: LLMUsageInfo | None = None

    def accept(self, chunk: ChatCompletion) -> LLMResponse | None:
        if isinstance(chunk, ErrorChunkResponse):
            raise CerebrasResponseError(CerebrasResponseErrorKind.VENDOR_ERROR)
        if not isinstance(chunk, ChatChunkResponse):
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        try:
            chunk = ChatChunkResponse.model_validate(
                chunk.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise CerebrasResponseError(
                CerebrasResponseErrorKind.INVALID_RESPONSE
            ) from None
        if chunk.object != "chat.completion.chunk":
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        if self.id and chunk.id and chunk.id != self.id:
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        if self.model and chunk.model and chunk.model != self.model:
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        if chunk.usage is not None:
            self.usage = _usage(chunk.usage)
        if not chunk.choices:
            return None
        if len(chunk.choices) != 1 or self.finish_reason is not None:
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        choice = chunk.choices[0]
        if choice.index != 0 or not chunk.id or not chunk.model:
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        self.id, self.model = chunk.id, chunk.model
        if choice.finish_reason is not None:
            self.finish_reason = CerebrasFinishReason(choice.finish_reason)
        delta = choice.delta
        if delta is None:
            return None
        if delta.role not in (None, "assistant"):
            raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_RESPONSE)
        for call in delta.tool_calls or ():
            if call.index is None or call.index < 0:
                raise CerebrasResponseError(CerebrasResponseErrorKind.INVALID_TOOL_CALL)
            try:
                self.calls.setdefault(call.index, ToolCallBuffer()).append(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=call.function.arguments,
                )
            except ToolCallAssemblyError:
                raise CerebrasResponseError(
                    CerebrasResponseErrorKind.INVALID_TOOL_CALL
                ) from None
        if not delta.content:
            return None
        self.text += delta.content
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text),
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=CEREBRAS_VENDOR,
                streaming=True,
                delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=delta.content),
            ),
        )

    def complete(self) -> LLMResponse:
        if not self.id or self.finish_reason is None:
            raise CerebrasResponseError(CerebrasResponseErrorKind.INCOMPLETE_RESPONSE)
        calls = [value for _, value in sorted(self.calls.items())]
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text)
            + _completed_tools(self.finish_reason, calls),
            stop_reason=_STOP_REASONS[self.finish_reason],
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=CEREBRAS_VENDOR, streaming=True, final=True
            ),
        )
