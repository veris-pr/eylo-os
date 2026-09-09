"""Validate OpenAI chat SDK responses and assemble complete, executable tool calls."""

from enum import StrEnum

from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sockets.llm.schemas import (
    LLMContentBlock,
    LLMContentType,
    LLMDeltaKind,
    LLMResponse,
    LLMResponseMetadata,
    LLMTextBlock,
    LLMTextContent,
    LLMTextDelta,
    LLMToolContent,
    LLMToolDelta,
    LLMToolUseBlock,
    LLMUsageInfo,
)
from eylo.sockets.llm.tool_content import (
    ToolCallAssemblyError,
    ToolCallBuffer,
    complete_tool_calls,
)

OPENAI_VENDOR = "openai"


class OpenAIChatResponseErrorKind(StrEnum):
    """Adapter failures, without retaining vendor payloads or tool arguments."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"


class OpenAIChatResponseError(RuntimeError):
    """Reject unsafe output before the platform can execute any tool call."""

    def __init__(self, kind: OpenAIChatResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"OpenAI chat response rejected: {kind.value}")


class OpenAIChatFinishReason(StrEnum):
    """OpenAI chat terminal reasons; deprecated function calls are not requested."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"


class OpenAIChatResponseMetadata(BaseModel):
    """Vendor-owned completion details; serialized before crossing the socket."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = OPENAI_VENDOR
    finish_reason: OpenAIChatFinishReason
    system_fingerprint: str | None = None


_STOP_REASONS = {
    OpenAIChatFinishReason.STOP: "end_turn",
    OpenAIChatFinishReason.LENGTH: "max_tokens",
    OpenAIChatFinishReason.TOOL_CALLS: "tool_use",
    OpenAIChatFinishReason.CONTENT_FILTER: "content_filter",
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
        raise OpenAIChatResponseError(
            OpenAIChatResponseErrorKind.INVALID_RESPONSE
        ) from None


def _text_blocks(text: str) -> list[LLMContentBlock]:
    return [LLMTextContent(content=LLMTextBlock(text=text))] if text else []


def _refusal_blocks(refusal: str) -> list[LLMContentBlock]:
    """Use the existing Responses adapter's human-readable refusal representation."""
    return _text_blocks(f"[Refusal] {refusal}") if refusal else []


def _completed_tools(
    reason: OpenAIChatFinishReason, calls: list[ToolCallBuffer], refusal: str
) -> list[LLMToolContent]:
    if refusal and calls:
        raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_TOOL_CALL)
    if reason == OpenAIChatFinishReason.FUNCTION_CALL:
        raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_TOOL_CALL)
    if (reason == OpenAIChatFinishReason.TOOL_CALLS) != bool(calls):
        raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INCOMPLETE_RESPONSE)
    try:
        return complete_tool_calls(calls)
    except ToolCallAssemblyError:
        raise OpenAIChatResponseError(
            OpenAIChatResponseErrorKind.INVALID_TOOL_CALL
        ) from None


def completion_response(value: ChatCompletion) -> LLMResponse:
    """Validate SDK-constructed data instead of trusting its type annotation."""
    try:
        value = ChatCompletion.model_validate(
            value.model_dump(warnings=False), strict=True
        )
    except ValidationError:
        raise OpenAIChatResponseError(
            OpenAIChatResponseErrorKind.INVALID_RESPONSE
        ) from None
    if not value.id or not value.model or len(value.choices) != 1:
        raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
    choice = value.choices[0]
    if choice.index != 0 or choice.message.function_call is not None:
        raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
    reason = OpenAIChatFinishReason(choice.finish_reason)
    calls: list[ToolCallBuffer] = []
    for call in choice.message.tool_calls or ():
        if call.type != "function":
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_TOOL_CALL)
        calls.append(
            ToolCallBuffer(
                id=call.id, name=call.function.name, arguments=call.function.arguments
            )
        )
    refusal = choice.message.refusal or ""
    return LLMResponse(
        id=value.id,
        model=value.model,
        content=_text_blocks(choice.message.content or "")
        + _refusal_blocks(refusal)
        + _completed_tools(reason, calls, refusal),
        stop_reason=_STOP_REASONS[reason],
        usage=_usage(value.usage),
        metadata=LLMResponseMetadata.model_validate(
            OpenAIChatResponseMetadata(
                finish_reason=reason,
                system_fingerprint=value.system_fingerprint,
            ).model_dump(mode="json")
        ),
    )


class OpenAIChatStream(BaseModel):
    """Text may stream early; tools become executable only after terminal validation."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    model: str = ""
    text: str = ""
    refusal: str = ""
    calls: dict[int, ToolCallBuffer] = Field(default_factory=dict)
    finish_reason: OpenAIChatFinishReason | None = None
    usage: LLMUsageInfo | None = None

    def accept(self, chunk: ChatCompletionChunk) -> LLMResponse | None:
        try:
            chunk = ChatCompletionChunk.model_validate(
                chunk.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise OpenAIChatResponseError(
                OpenAIChatResponseErrorKind.INVALID_RESPONSE
            ) from None
        if self.id and chunk.id and chunk.id != self.id:
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
        if self.model and chunk.model and chunk.model != self.model:
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
        usage = chunk.usage
        if usage is not None:
            self.usage = _usage(usage)
        if not chunk.choices:
            return None
        if len(chunk.choices) != 1 or self.finish_reason is not None:
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
        choice = chunk.choices[0]
        if choice.index != 0 or not chunk.id or not chunk.model:
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
        self.id, self.model = chunk.id, chunk.model
        delta = choice.delta
        if delta.role is not None and delta.role != "assistant":
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_RESPONSE)
        if delta.refusal:
            self.refusal += delta.refusal
        if delta.function_call is not None:
            raise OpenAIChatResponseError(OpenAIChatResponseErrorKind.INVALID_TOOL_CALL)
        for call in delta.tool_calls or ():
            if call.index < 0:
                raise OpenAIChatResponseError(
                    OpenAIChatResponseErrorKind.INVALID_TOOL_CALL
                )
            try:
                self.calls.setdefault(call.index, ToolCallBuffer()).append(
                    call_id=call.id,
                    name=None if call.function is None else call.function.name,
                    arguments=None
                    if call.function is None
                    else call.function.arguments,
                )
            except ToolCallAssemblyError:
                raise OpenAIChatResponseError(
                    OpenAIChatResponseErrorKind.INVALID_TOOL_CALL
                ) from None
        if choice.finish_reason is not None:
            self.finish_reason = OpenAIChatFinishReason(choice.finish_reason)
        if not delta.content:
            return None
        self.text += delta.content
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text),
            usage=self.usage,
            metadata=LLMResponseMetadata(
                vendor=OPENAI_VENDOR,
                streaming=True,
                delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=delta.content),
            ),
        )

    def complete(self) -> LLMResponse:
        if not self.id or self.finish_reason is None:
            raise OpenAIChatResponseError(
                OpenAIChatResponseErrorKind.INCOMPLETE_RESPONSE
            )
        calls = [value for _, value in sorted(self.calls.items())]
        return LLMResponse(
            id=self.id,
            model=self.model,
            content=_text_blocks(self.text)
            + _refusal_blocks(self.refusal)
            + _completed_tools(self.finish_reason, calls, self.refusal),
            stop_reason=_STOP_REASONS[self.finish_reason],
            usage=self.usage,
            metadata=LLMResponseMetadata.model_validate(
                OpenAIChatResponseMetadata(finish_reason=self.finish_reason).model_dump(
                    mode="json", exclude={"system_fingerprint"}
                )
            ).model_copy(update={"streaming": False}),
        )

    def tool_completions(self, final: LLMResponse) -> list[LLMResponse]:
        """Preserve progress envelopes only after the entire final batch is validated."""
        tool_blocks = [
            block for block in final.content if block.type == LLMContentType.TOOL_USE
        ]
        prefix: list[LLMContentBlock] = [
            block for block in final.content if block.type != LLMContentType.TOOL_USE
        ]
        responses: list[LLMResponse] = []
        for index, block in zip(sorted(self.calls), tool_blocks, strict=True):
            tool = block.content
            if not isinstance(tool, LLMToolUseBlock):
                raise OpenAIChatResponseError(
                    OpenAIChatResponseErrorKind.INVALID_TOOL_CALL
                )
            prefix.append(block)
            responses.append(
                LLMResponse(
                    id=final.id,
                    model=final.model,
                    content=list(prefix),
                    usage=final.usage,
                    metadata=LLMResponseMetadata(
                        vendor=OPENAI_VENDOR,
                        streaming=True,
                        delta=LLMToolDelta(
                            type=LLMDeltaKind.TOOL_CALL_COMPLETE,
                            index=index,
                            tool_id=tool.id,
                            tool_name=tool.name,
                            tool_input=tool.input,
                        ),
                    ),
                )
            )
        return responses
