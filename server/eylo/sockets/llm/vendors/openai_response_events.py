"""Validate native Responses output; only the terminal snapshot authorizes tools."""

from enum import StrEnum
from typing import Annotated

from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseCreatedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseFunctionCallArgumentsDeltaEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseFunctionToolCall,
    ResponseInProgressEvent,
    ResponseIncompleteEvent,
    ResponseOutputItem,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseQueuedEvent,
    ResponseReasoningItem,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseStreamEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
    ResponseUsage,
)
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

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
    LLMToolDelta,
    LLMToolUseBlock,
    LLMUsageInfo,
)
from eylo.sockets.llm.tool_content import (
    ToolCallAssemblyError,
    ToolCallBuffer,
    complete_tool_calls,
)

OPENAI_RESPONSES_VENDOR = "openai_responses"
_STREAM_EVENT = TypeAdapter(Annotated[ResponseStreamEvent, Field(discriminator="type")])
_PASSIVE_PROGRESS_EVENTS = (
    ResponseContentPartAddedEvent,
    ResponseContentPartDoneEvent,
    ResponseTextDoneEvent,
    ResponseOutputTextAnnotationAddedEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryTextDoneEvent,
    ResponseReasoningTextDeltaEvent,
    ResponseReasoningTextDoneEvent,
)
type ConversationOutput = (
    ResponseOutputMessage | ResponseFunctionToolCall | ResponseReasoningItem
)


class OpenAIResponseErrorKind(StrEnum):
    """Payload-free adapter failures, not provider error-message strings."""

    INVALID_RESPONSE = "invalid_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    INCOMPLETE_RESPONSE = "incomplete_response"
    PROVIDER_ERROR = "provider_error"
    UNSUPPORTED_OUTPUT = "unsupported_output"


class OpenAIResponseError(RuntimeError):
    """Do not retain model output, credentials, or tool arguments in errors."""

    def __init__(self, kind: OpenAIResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"OpenAI Responses output rejected: {kind.value}")


class OpenAIResponseStatus(StrEnum):
    """Native response/item states; only completed output can authorize tools."""

    COMPLETED = "completed"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    CANCELLED = "cancelled"
    QUEUED = "queued"
    INCOMPLETE = "incomplete"


class OpenAIResponsesMetadata(BaseModel):
    """Native response status is not a platform stream-lifecycle state."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = OPENAI_RESPONSES_VENDOR
    status: OpenAIResponseStatus | None


def _validated_response(value: Response) -> Response:
    try:
        result = Response.model_validate(value.model_dump(warnings=False), strict=True)
    except ValidationError:
        raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE) from None
    if not result.id.strip() or not result.model.strip():
        raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
    return result


def _conversation_output(value: ResponseOutputItem) -> ConversationOutput:
    if isinstance(
        value, ResponseOutputMessage | ResponseFunctionToolCall | ResponseReasoningItem
    ):
        return value
    # This adapter only requests platform function tools, never hosted tools/audio.
    raise OpenAIResponseError(OpenAIResponseErrorKind.UNSUPPORTED_OUTPUT)


def _usage(value: ResponseUsage | None) -> LLMUsageInfo | None:
    if value is None:
        return None
    try:
        return LLMUsageInfo(
            input_tokens=value.input_tokens,
            output_tokens=value.output_tokens,
            cache_read_input_tokens=value.input_tokens_details.cached_tokens,
            reasoning_tokens=value.output_tokens_details.reasoning_tokens,
        )
    except ValidationError:
        raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE) from None


def _text(text: str) -> list[LLMContentBlock]:
    return [LLMTextContent(content=LLMTextBlock(text=text))] if text else []


def _stop_reason(value: Response) -> LLMStopReason:
    if value.error is not None or value.status in (
        OpenAIResponseStatus.FAILED,
        OpenAIResponseStatus.CANCELLED,
    ):
        raise OpenAIResponseError(OpenAIResponseErrorKind.PROVIDER_ERROR)
    if value.status == OpenAIResponseStatus.COMPLETED:
        if (
            value.incomplete_details is not None
            and value.incomplete_details.reason is not None
        ):
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        return LLMStopReason.END_TURN
    if (
        value.status == OpenAIResponseStatus.INCOMPLETE
        and value.incomplete_details is not None
    ):
        match value.incomplete_details.reason:
            case "max_output_tokens":
                return LLMStopReason.MAX_TOKENS
            case "content_filter":
                return LLMStopReason.CONTENT_FILTER
    raise OpenAIResponseError(OpenAIResponseErrorKind.INCOMPLETE_RESPONSE)


def response_to_platform(value: Response) -> LLMResponse:
    """Normalize one native terminal snapshot after validating its entire tool batch."""
    value = _validated_response(value)
    stop_reason = _stop_reason(value)
    output = [_conversation_output(item) for item in value.output]
    calls: list[ToolCallBuffer] = []
    has_refusal = False
    ids: set[str] = set()
    for item in output:
        if item.id is not None:
            if not item.id.strip() or item.id in ids:
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
            ids.add(item.id)
        if item.status == OpenAIResponseStatus.IN_PROGRESS or (
            value.status == OpenAIResponseStatus.COMPLETED
            and item.status == OpenAIResponseStatus.INCOMPLETE
        ):
            raise OpenAIResponseError(OpenAIResponseErrorKind.INCOMPLETE_RESPONSE)
        if isinstance(item, ResponseFunctionToolCall):
            calls.append(
                ToolCallBuffer(
                    id=item.call_id, name=item.name, arguments=item.arguments
                )
            )
        elif isinstance(item, ResponseOutputMessage):
            has_refusal |= any(part.type == "refusal" for part in item.content)
    if calls and (has_refusal or value.status != OpenAIResponseStatus.COMPLETED):
        raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL)
    try:
        tool_blocks = iter(complete_tool_calls(calls))
    except ToolCallAssemblyError:
        raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL) from None
    content: list[LLMContentBlock] = []
    for item in output:
        if isinstance(item, ResponseFunctionToolCall):
            content.append(next(tool_blocks))
        elif isinstance(item, ResponseOutputMessage):
            for part in item.content:
                if part.type == "output_text":
                    content.extend(_text(part.text))
                else:
                    content.extend(_text(f"[Refusal] {part.refusal}"))
        # Reasoning output is not user-visible text; its usage remains accounted.
    return LLMResponse(
        id=value.id,
        model=value.model,
        content=content,
        stop_reason=stop_reason,
        usage=_usage(value.usage),
        metadata=LLMResponseMetadata.model_validate(
            OpenAIResponsesMetadata(
                status=OpenAIResponseStatus(value.status) if value.status else None,
            ).model_dump(mode="json")
        ),
    )


def tool_completions(final: LLMResponse) -> list[LLMResponse]:
    """Retain existing progress envelopes after full validation and resource cleanup."""
    prefix: list[LLMContentBlock] = []
    responses: list[LLMResponse] = []
    for block in final.content:
        prefix.append(block)
        if block.type != LLMContentType.TOOL_USE:
            continue
        tool = block.content
        if not isinstance(tool, LLMToolUseBlock):
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL)
        responses.append(
            LLMResponse(
                id=final.id,
                model=final.model,
                content=list(prefix),
                usage=final.usage,
                metadata=LLMResponseMetadata(
                    vendor=OPENAI_RESPONSES_VENDOR,
                    streaming=True,
                    delta=LLMToolDelta(
                        type=LLMDeltaKind.TOOL_CALL_COMPLETE,
                        tool_id=tool.id,
                        tool_name=tool.name,
                        tool_input=tool.input,
                    ),
                ),
            )
        )
    return responses


class OpenAIResponseStream(BaseModel):
    """Text deltas drive progress; the complete native response owns final output."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    model: str = ""
    text: str = ""
    sequence: int = -1
    items: dict[int, ConversationOutput] = Field(default_factory=dict)
    final: LLMResponse | None = None

    def _identity(self, response: Response) -> None:
        if response.id != self.id or response.model != self.model:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)

    def _same_item(
        self, expected: ConversationOutput, actual: ConversationOutput
    ) -> None:
        if expected.type != actual.type or expected.id != actual.id:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        if isinstance(expected, ResponseFunctionToolCall) and isinstance(
            actual, ResponseFunctionToolCall
        ):
            if expected.call_id != actual.call_id or expected.name != actual.name:
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL)

    def _target(self, index: int, item_id: str) -> ConversationOutput:
        item = self.items.get(index)
        if item is None or item.id != item_id:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        return item

    def accept(self, value: ResponseStreamEvent) -> LLMResponse | None:
        try:
            event = _STREAM_EVENT.validate_python(
                value.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise OpenAIResponseError(
                OpenAIResponseErrorKind.INVALID_RESPONSE
            ) from None
        if event.sequence_number <= self.sequence or self.final is not None:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        self.sequence = event.sequence_number
        if isinstance(event, ResponseErrorEvent | ResponseFailedEvent):
            raise OpenAIResponseError(OpenAIResponseErrorKind.PROVIDER_ERROR)
        if isinstance(event, ResponseCreatedEvent):
            if self.id or event.response.status not in (
                OpenAIResponseStatus.IN_PROGRESS,
                OpenAIResponseStatus.QUEUED,
            ):
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
            response = _validated_response(event.response)
            self.id, self.model = response.id, response.model
            return None
        if not self.id:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INCOMPLETE_RESPONSE)
        if isinstance(event, ResponseCompletedEvent | ResponseIncompleteEvent):
            self._identity(event.response)
            expected_status = (
                OpenAIResponseStatus.COMPLETED
                if isinstance(event, ResponseCompletedEvent)
                else OpenAIResponseStatus.INCOMPLETE
            )
            if event.response.status != expected_status:
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
            for index, item in self.items.items():
                if index >= len(event.response.output):
                    raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
                self._same_item(
                    item, _conversation_output(event.response.output[index])
                )
            self.final = response_to_platform(event.response)
            self.final.metadata = self.final.metadata.model_copy(
                update={"streaming": False}
            )
        elif isinstance(event, ResponseInProgressEvent | ResponseQueuedEvent):
            self._identity(event.response)
            expected_status = (
                OpenAIResponseStatus.IN_PROGRESS
                if isinstance(event, ResponseInProgressEvent)
                else OpenAIResponseStatus.QUEUED
            )
            if event.response.status != expected_status:
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        elif isinstance(
            event, ResponseOutputItemAddedEvent | ResponseOutputItemDoneEvent
        ):
            item = _conversation_output(event.item)
            if event.output_index < 0 or not item.id or not item.id.strip():
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
            previous = self.items.get(event.output_index)
            if previous is not None:
                if isinstance(event, ResponseOutputItemAddedEvent):
                    raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
                self._same_item(previous, item)
            self.items[event.output_index] = item
        elif isinstance(event, ResponseTextDeltaEvent):
            if event.content_index < 0 or not isinstance(
                self._target(event.output_index, event.item_id), ResponseOutputMessage
            ):
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
            self.text += event.delta
            if event.delta:
                return LLMResponse(
                    id=self.id,
                    model=self.model,
                    content=_text(self.text),
                    metadata=LLMResponseMetadata(
                        vendor=OPENAI_RESPONSES_VENDOR,
                        streaming=True,
                        delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=event.delta),
                    ),
                )
        elif isinstance(
            event,
            ResponseFunctionCallArgumentsDeltaEvent
            | ResponseFunctionCallArgumentsDoneEvent,
        ):
            item = self._target(event.output_index, event.item_id)
            if not isinstance(item, ResponseFunctionToolCall):
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL)
            if (
                isinstance(event, ResponseFunctionCallArgumentsDoneEvent)
                and event.name != item.name
            ):
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_TOOL_CALL)
            # Never reconstruct executable calls from these advisory fragments.
        elif isinstance(event, ResponseRefusalDeltaEvent | ResponseRefusalDoneEvent):
            if not isinstance(
                self._target(event.output_index, event.item_id), ResponseOutputMessage
            ):
                raise OpenAIResponseError(OpenAIResponseErrorKind.INVALID_RESPONSE)
        elif not isinstance(event, _PASSIVE_PROGRESS_EVENTS):
            raise OpenAIResponseError(OpenAIResponseErrorKind.UNSUPPORTED_OUTPUT)
        return None

    def complete(self) -> LLMResponse:
        if self.final is None:
            raise OpenAIResponseError(OpenAIResponseErrorKind.INCOMPLETE_RESPONSE)
        return self.final
