"""Normalize native Gemini output; retain signed parts without rewriting them."""

import json
from enum import StrEnum
from uuid import uuid4

from google.genai import types
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_serializer,
)

from eylo.common.contracts.messages import MessageInDb, MessageKind
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
    LLMToolContent,
    LLMToolUseBlock,
    LLMUsageInfo,
)
from eylo.sockets.llm.tool_content import (
    ToolCallAssemblyError,
    ToolCallBuffer,
    complete_tool_calls,
)

GEMINI_VENDOR = "gemini"


class GeminiResponseErrorKind(StrEnum):
    """Diagnostic kinds never include vendor payloads, signatures, or arguments."""

    INVALID_RESPONSE = "invalid_response"
    INCOMPLETE_RESPONSE = "incomplete_response"
    INVALID_TOOL_CALL = "invalid_tool_call"
    UNSUPPORTED_CONTENT = "unsupported_content"
    INVALID_HISTORY = "invalid_history"


class GeminiResponseError(RuntimeError):
    """Refuse an unrepresentable or incomplete native response atomically."""

    def __init__(self, kind: GeminiResponseErrorKind) -> None:
        self.kind = kind
        super().__init__(f"Gemini response rejected: {kind.value}")


class GeminiReplayBlock(BaseModel):
    """One canonical block, with its original unmerged native parts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: LLMContentType
    parts: tuple[types.Part, ...]
    tool_call: LLMToolUseBlock | None = None

    @property
    def text(self) -> str:
        return "".join(part.text or "" for part in self.parts)


class GeminiReplay(BaseModel):
    """Adapter-owned JSON contract; native Part owns base64 byte serialization."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    blocks: tuple[GeminiReplayBlock, ...]


_SAFETY_JSON = TypeAdapter(list[dict[str, JsonValue]])


class GeminiResponseMetadata(BaseModel):
    """Native replay and safety fields are serialized before leaving the adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vendor: str = GEMINI_VENDOR
    streaming: bool
    final: bool
    finish_reason: types.FinishReason | None
    blocked_reason: types.BlockedReason | None
    gemini_replay: GeminiReplay
    safety_ratings: list[types.SafetyRating]

    @field_serializer("safety_ratings")
    def safety_json(
        self, value: list[types.SafetyRating]
    ) -> list[dict[str, JsonValue]]:
        return _SAFETY_JSON.validate_python(
            [rating.model_dump(mode="json", exclude_none=True) for rating in value]
        )


class _ResponseMetadata(BaseModel):
    """Read only this adapter's extension of the canonical response metadata."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    gemini_replay: GeminiReplay | None = None


class _SavedResponse(BaseModel):
    """Other adapters' partial metadata does not imply Gemini replay authority."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    id: str = ""
    metadata: _ResponseMetadata = Field(default_factory=_ResponseMetadata)


class _SavedMessage(BaseModel):
    """Producer-owned block identity independent of SDK and persistence schemas."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    llm_response: _SavedResponse | None = None
    response_block_index: int | None = None


class GeminiMessageReplay(BaseModel):
    """A retained message's verified parts and their model-turn identity."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, hide_input_in_errors=True
    )

    response_id: str
    parts: tuple[types.Part, ...]


def message_replay(message: MessageInDb) -> GeminiMessageReplay | None:
    """Never replay absent/filtered rows or attach a signature to regenerated text."""
    if message.meta is None:
        return None
    try:
        saved = _SavedMessage.model_validate(message.meta.model_dump(mode="json"))
        response = saved.llm_response
        if response is None or response.metadata.gemini_replay is None:
            return None
        if not response.id.strip():
            raise ValueError
        blocks = response.metadata.gemini_replay.blocks
        index = saved.response_block_index
        if index is None:
            # Whole-response replay is reserved for an unchanged final text row.
            if message.kind != MessageKind.ASSISTANT or any(
                block.kind == LLMContentType.TOOL_USE for block in blocks
            ):
                raise ValueError
            selected = list(blocks)
        else:
            if index < 0 or index >= len(blocks):
                raise ValueError
            selected = [blocks[index]]
            # Reasoning is not stored as transcript rows. Retain only the thoughts
            # immediately preceding this retained block, not other tool calls.
            prior = index - 1
            while prior >= 0 and blocks[prior].kind == LLMContentType.THINKING:
                selected.insert(0, blocks[prior])
                prior -= 1
        if message.kind == MessageKind.TOOL_USE:
            expected = message.get_tool_use_content().content
            actual = selected[-1].tool_call
            if actual is None or (
                actual.id != expected.id
                or actual.name != expected.name
                or actual.input != expected.input
            ):
                raise ValueError
        elif message.kind == MessageKind.ASSISTANT:
            if any(block.kind == LLMContentType.TOOL_USE for block in selected):
                raise ValueError
            text = "".join(
                block.text for block in selected if block.kind == LLMContentType.TEXT
            )
            if text != message.get_text_content():
                raise ValueError
        else:
            raise ValueError
        for block in selected:
            _validate_replay_block(block)
        return GeminiMessageReplay(
            response_id=response.id,
            parts=tuple(
                part.model_copy(deep=True) for block in selected for part in block.parts
            ),
        )
    except (ValidationError, ValueError, TypeError):
        raise GeminiResponseError(GeminiResponseErrorKind.INVALID_HISTORY) from None


def _validate_replay_block(block: GeminiReplayBlock) -> None:
    """The retained native parts must still describe the canonical message."""
    kinds = [_part_kind(part) for part in block.parts]
    if not kinds or any(kind not in (None, block.kind) for kind in kinds):
        raise ValueError
    calls = [
        part.function_call for part in block.parts if part.function_call is not None
    ]
    if block.kind != LLMContentType.TOOL_USE:
        if calls or block.tool_call is not None:
            raise ValueError
        return
    if len(calls) != 1 or block.tool_call is None:
        raise ValueError
    native = calls[0]
    canonical = block.tool_call
    parsed = _tool_call(native)
    if (
        (native.id is not None and native.id != canonical.id)
        or parsed.name != canonical.name
        or parsed.input != canonical.input
    ):
        raise ValueError


def _part_kind(part: types.Part) -> LLMContentType | None:
    if any(
        value is not None
        for value in (
            part.media_resolution,
            part.code_execution_result,
            part.executable_code,
            part.file_data,
            part.function_response,
            part.inline_data,
            part.video_metadata,
        )
    ):
        raise GeminiResponseError(GeminiResponseErrorKind.UNSUPPORTED_CONTENT)
    if part.function_call is not None:
        if part.text is not None or part.thought:
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        return LLMContentType.TOOL_USE
    if part.text:
        return LLMContentType.THINKING if part.thought else LLMContentType.TEXT
    # Gemini can end a text stream with an empty signed Part.
    if part.thought_signature is not None or part.text == "":
        return None
    raise GeminiResponseError(GeminiResponseErrorKind.UNSUPPORTED_CONTENT)


def _tool_call(value: types.FunctionCall) -> LLMToolUseBlock:
    # Partial argument streaming belongs to Vertex, not this Developer API adapter.
    if value.partial_args is not None or value.will_continue is not None:
        raise GeminiResponseError(GeminiResponseErrorKind.UNSUPPORTED_CONTENT)
    try:
        block = ToolCallBuffer(
            id=value.id if value.id is not None else str(uuid4()),
            name=value.name or "",
            arguments=json.dumps(
                value.args if value.args is not None else {}, allow_nan=False
            ),
        ).to_block()
        return LLMToolUseBlock.model_validate(block.content)
    except (ValueError, TypeError):
        raise GeminiResponseError(GeminiResponseErrorKind.INVALID_TOOL_CALL) from None


class GeminiStream(BaseModel):
    """Accumulate native parts in arrival order; authorize tools only at EOF."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    requested_model: str
    id: str = ""
    model: str = ""
    blocks: list[GeminiReplayBlock] = Field(default_factory=list)
    pending_parts: list[types.Part] = Field(default_factory=list)
    finish_reason: types.FinishReason | None = None
    blocked_reason: types.BlockedReason | None = None
    usage: LLMUsageInfo | None = None
    usage_metadata: types.GenerateContentResponseUsageMetadata = Field(
        default_factory=types.GenerateContentResponseUsageMetadata
    )
    safety_ratings: list[types.SafetyRating] = Field(default_factory=list)

    def accept(self, chunk: types.GenerateContentResponse) -> LLMResponse | None:
        try:
            chunk = types.GenerateContentResponse.model_validate(
                chunk.model_dump(warnings=False), strict=True
            )
        except ValidationError:
            raise GeminiResponseError(
                GeminiResponseErrorKind.INVALID_RESPONSE
            ) from None
        if chunk.response_id:
            if not chunk.response_id.strip():
                raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
            if self.id and self.id != chunk.response_id:
                raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
            self.id = chunk.response_id
        if chunk.model_version:
            if self.model and self.model != chunk.model_version:
                raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
            self.model = chunk.model_version
        self._accept_usage(chunk.usage_metadata)
        feedback = chunk.prompt_feedback
        if feedback and feedback.block_reason not in (
            None,
            types.BlockedReason.BLOCKED_REASON_UNSPECIFIED,
        ):
            if self.blocks or chunk.candidates:
                raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
            self.blocked_reason = feedback.block_reason
            self.safety_ratings = [
                rating.model_copy(deep=True) for rating in feedback.safety_ratings or ()
            ]
        if not chunk.candidates:
            return None
        if len(chunk.candidates) != 1 or self.blocked_reason is not None:
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        candidate = chunk.candidates[0]
        if candidate.safety_ratings is not None:
            self.safety_ratings = [
                rating.model_copy(deep=True) for rating in candidate.safety_ratings
            ]
        if candidate.index not in (None, 0):
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        content = candidate.content
        parts = content.parts if content is not None else None
        if content is not None and content.role not in (None, "model"):
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        if self.finish_reason is not None and parts:
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        delta = ""
        for part in parts or ():
            kind = _part_kind(part)
            original = part.model_copy(deep=True)
            if kind is None:
                if self.blocks:
                    previous = self.blocks[-1]
                    self.blocks[-1] = previous.model_copy(
                        update={"parts": (*previous.parts, original)}
                    )
                else:
                    self.pending_parts.append(original)
                continue
            if kind == LLMContentType.TEXT:
                delta += part.text or ""
            if (
                kind != LLMContentType.TOOL_USE
                and self.blocks
                and self.blocks[-1].kind == kind
            ):
                previous = self.blocks[-1]
                self.blocks[-1] = previous.model_copy(
                    update={"parts": (*previous.parts, original)}
                )
            else:
                self.blocks.append(
                    GeminiReplayBlock(
                        kind=kind,
                        parts=(*self.pending_parts, original),
                        tool_call=_tool_call(part.function_call)
                        if part.function_call
                        else None,
                    )
                )
                self.pending_parts.clear()
        reason = candidate.finish_reason
        if reason not in (None, types.FinishReason.FINISH_REASON_UNSPECIFIED):
            if self.finish_reason is not None and self.finish_reason != reason:
                raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
            self.finish_reason = reason
        if not delta:
            return None
        self.id = self.id or str(uuid4())
        return LLMResponse(
            id=self.id,
            model=self.model or self.requested_model,
            content=self._content(include_tools=False),
            usage=self.usage.model_copy() if self.usage else None,
            metadata=LLMResponseMetadata(
                vendor=GEMINI_VENDOR,
                streaming=True,
                delta=LLMTextDelta(type=LLMDeltaKind.TEXT, text=delta),
            ),
        )

    def _accept_usage(
        self, value: types.GenerateContentResponseUsageMetadata | None
    ) -> None:
        if value is None:
            return
        counts = (
            value.prompt_token_count,
            value.candidates_token_count,
            value.cached_content_token_count,
            value.thoughts_token_count,
            value.total_token_count,
            value.tool_use_prompt_token_count,
        )
        if any(
            count is not None and (type(count) is not int or count < 0)
            for count in counts
        ):
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
        previous = self.usage_metadata
        merged = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=value.prompt_token_count
            if value.prompt_token_count is not None
            else previous.prompt_token_count,
            candidates_token_count=value.candidates_token_count
            if value.candidates_token_count is not None
            else previous.candidates_token_count,
            cached_content_token_count=value.cached_content_token_count
            if value.cached_content_token_count is not None
            else previous.cached_content_token_count,
            thoughts_token_count=value.thoughts_token_count
            if value.thoughts_token_count is not None
            else previous.thoughts_token_count,
        )
        self.usage_metadata = merged
        if merged.prompt_token_count is None or merged.candidates_token_count is None:
            return
        self.usage = LLMUsageInfo(
            input_tokens=merged.prompt_token_count,
            output_tokens=merged.candidates_token_count,
            cache_read_input_tokens=merged.cached_content_token_count,
            reasoning_tokens=merged.thoughts_token_count,
        )

    def _content(self, *, include_tools: bool) -> list[LLMContentBlock]:
        content: list[LLMContentBlock] = []
        for block in self.blocks:
            if block.kind == LLMContentType.TOOL_USE:
                if include_tools:
                    if block.tool_call is None:
                        raise GeminiResponseError(
                            GeminiResponseErrorKind.INVALID_TOOL_CALL
                        )
                    content.append(
                        LLMToolContent(
                            id=block.tool_call.id,
                            content=block.tool_call.model_copy(deep=True),
                        )
                    )
            elif block.kind == LLMContentType.TEXT:
                content.append(LLMTextContent(content=LLMTextBlock(text=block.text)))
            else:
                content.append(
                    LLMThinkingContent(content=LLMTextBlock(text=block.text))
                )
        return content

    def complete(self, *, streaming: bool) -> LLMResponse:
        if self.finish_reason is None and self.blocked_reason is None:
            raise GeminiResponseError(GeminiResponseErrorKind.INCOMPLETE_RESPONSE)
        if self.finish_reason in (
            types.FinishReason.MALFORMED_FUNCTION_CALL,
            types.FinishReason.UNEXPECTED_TOOL_CALL,
        ):
            raise GeminiResponseError(GeminiResponseErrorKind.INVALID_TOOL_CALL)
        if self.pending_parts:
            raise GeminiResponseError(GeminiResponseErrorKind.INCOMPLETE_RESPONSE)
        tools = [
            block.tool_call for block in self.blocks if block.tool_call is not None
        ]
        if tools:
            if self.finish_reason != types.FinishReason.STOP:
                raise GeminiResponseError(GeminiResponseErrorKind.INCOMPLETE_RESPONSE)
            try:
                complete_tool_calls(
                    [
                        ToolCallBuffer(
                            id=call.id,
                            name=call.name,
                            arguments=json.dumps(call.input, allow_nan=False),
                        )
                        for call in tools
                    ]
                )
            except (ToolCallAssemblyError, ValueError, TypeError):
                raise GeminiResponseError(
                    GeminiResponseErrorKind.INVALID_TOOL_CALL
                ) from None
        reason = LLMStopReason.CONTENT_FILTER
        if self.finish_reason == types.FinishReason.STOP:
            reason = LLMStopReason.TOOL_USE if tools else LLMStopReason.END_TURN
        elif self.finish_reason == types.FinishReason.MAX_TOKENS:
            reason = LLMStopReason.MAX_TOKENS
        elif self.finish_reason == types.FinishReason.OTHER:
            reason = LLMStopReason.OTHER
        self.id = self.id or str(uuid4())
        return LLMResponse(
            id=self.id,
            model=self.model or self.requested_model,
            content=self._content(include_tools=True),
            stop_reason=reason,
            usage=self.usage.model_copy() if self.usage else None,
            metadata=LLMResponseMetadata.model_validate(
                GeminiResponseMetadata(
                    streaming=streaming,
                    final=True,
                    finish_reason=self.finish_reason,
                    blocked_reason=self.blocked_reason,
                    gemini_replay=GeminiReplay(blocks=tuple(self.blocks)),
                    safety_ratings=self.safety_ratings,
                ).model_dump(mode="json")
            ),
        )


def completion_response(
    value: types.GenerateContentResponse, model: str = ""
) -> LLMResponse:
    state = GeminiStream(requested_model=model)
    state.accept(value)
    if not state.model and not model:
        raise GeminiResponseError(GeminiResponseErrorKind.INVALID_RESPONSE)
    return state.complete(streaming=False)
