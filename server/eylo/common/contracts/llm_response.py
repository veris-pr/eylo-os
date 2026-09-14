"""Vendor-neutral output contracts shared by adapters and platform consumers."""

import math
from enum import Enum, StrEnum
from typing import Annotated, List, Literal, Optional, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)


def _finite_json(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Validate numbers before JSON serialization could replace NaN with null."""
    pending = list(value.values())
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON numbers must be finite")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


class LLMStopReason(StrEnum):
    """Normalized socket stop reasons; native protocol enums stay in adapters."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class LLMContentType(str, Enum):
    """Generic content types that can appear in LLM responses.

    These types are common across most LLM providers, though not all
    providers support all types.
    """

    TEXT = "text"
    TOOL_USE = "tool_use"
    THINKING = "thinking"


class LLMTextBlock(BaseModel):
    """Generic text content from LLM - application native format."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str


class LLMToolUseBlock(BaseModel):
    """Generic tool use request from LLM - application native format.

    Represents a request from the LLM to execute a tool/function.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="Unique identifier for this tool use")
    name: str = Field(..., description="Name of the tool to execute")
    input: dict[str, JsonValue] = Field(
        default_factory=dict, description="Input parameters for the tool"
    )

    @field_validator("id", "name")
    @classmethod
    def nonblank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Tool identity must not be blank")
        return value

    @field_validator("input")
    @classmethod
    def finite_arguments(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        """JSON permits nested data, but not NaN/Infinity or Python objects."""
        return _finite_json(value)


class _LLMBlock(BaseModel):
    """Immutable envelope; a content discriminator cannot drift after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str | None = None


class LLMTextContent(_LLMBlock):
    """Model text eligible for conversation display and speech."""

    type: Literal[LLMContentType.TEXT] = LLMContentType.TEXT
    content: LLMTextBlock


class LLMThinkingContent(_LLMBlock):
    """Reasoning stays distinct from text displayed or spoken to the user."""

    type: Literal[LLMContentType.THINKING] = LLMContentType.THINKING
    content: LLMTextBlock


class LLMToolContent(_LLMBlock):
    """Only this variant carries executable tool identity and JSON arguments."""

    type: Literal[LLMContentType.TOOL_USE] = LLMContentType.TOOL_USE
    content: LLMToolUseBlock

    @model_validator(mode="after")
    def matching_identity(self) -> Self:
        if self.id is not None and self.id != self.content.id:
            raise ValueError("Tool block identity must match its content")
        return self


type LLMContentBlock = Annotated[
    LLMTextContent | LLMThinkingContent | LLMToolContent,
    Field(discriminator="type"),
]


class LLMUsageInfo(BaseModel):
    """A reported usage record, never an estimate for missing vendor counts.

    Both primary counts must be known. Adapters leave response usage absent while
    incomplete; optional detail counters need not be reported by every vendor.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    cache_creation_input_tokens: int | None = Field(default=None, ge=0, strict=True)
    cache_read_input_tokens: int | None = Field(default=None, ge=0, strict=True)
    reasoning_tokens: int | None = Field(default=None, ge=0, strict=True)

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed."""
        return self.input_tokens + self.output_tokens


class LLMDeltaKind(StrEnum):
    """Existing canonical progress labels, independent of vendor event names."""

    TEXT = "text_delta"
    THINKING = "thinking_delta"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_USE_COMPLETE = "tool_use_complete"


_METADATA_JSON = TypeAdapter(dict[str, JsonValue])


class _LLMMetadataFields(BaseModel):
    """Keep absent wire fields absent, while respecting caller include/exclude."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_serializer(mode="wrap")
    def explicit_fields(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, JsonValue]:
        values = _METADATA_JSON.validate_python(handler(self))
        return {
            key: value for key, value in values.items() if key in self.model_fields_set
        }


class LLMTextDelta(_LLMMetadataFields):
    """Only visible text progress is eligible for speech delivery."""

    type: Literal[LLMDeltaKind.TEXT]
    text: str
    block_index: int | None = Field(default=None, ge=0, strict=True)


class LLMThinkingDelta(_LLMMetadataFields):
    """Reasoning progress must not become user-facing speech."""

    type: Literal[LLMDeltaKind.THINKING]
    text: str
    block_index: int | None = Field(default=None, ge=0, strict=True)


class LLMToolDelta(_LLMMetadataFields):
    """A validated tool-completion notification, not execution authority."""

    type: Literal[LLMDeltaKind.TOOL_CALL_COMPLETE, LLMDeltaKind.TOOL_USE_COMPLETE]
    tool_id: str
    tool_name: str
    tool_input: dict[str, JsonValue]
    index: int | None = Field(default=None, ge=0, strict=True)
    block_index: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def valid_call(self) -> Self:
        LLMToolUseBlock(id=self.tool_id, name=self.tool_name, input=self.tool_input)
        return self


type LLMDelta = Annotated[
    LLMTextDelta | LLMThinkingDelta | LLMToolDelta, Field(discriminator="type")
]


class LLMResponsePhase(StrEnum):
    """Caller-facing interpretation of the existing serialized stream flags."""

    PROGRESS = "progress"
    COMPLETE = "complete"


class LLMResponseMetadata(_LLMMetadataFields):
    """Shared stream fields plus JSON-only, adapter-owned extensions.

    Native SDK objects must be serialized inside their adapter. The existing
    streaming/final wire flags remain readable; callers use the derived phase.
    Unset fields stay absent when transported through an LLMResponse.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    vendor: str | None = None
    streaming: bool = Field(default=False, strict=True)
    final: bool = Field(default=False, strict=True)
    delta: LLMDelta | None = None

    @property
    def phase(self) -> LLMResponsePhase:
        if self.streaming and not self.final:
            return LLMResponsePhase.PROGRESS
        return LLMResponsePhase.COMPLETE

    @model_validator(mode="after")
    def finite_extensions(self) -> Self:
        extensions = _METADATA_JSON.validate_python(self.model_extra or {})
        _finite_json(extensions)
        return self

    def to_json(self) -> dict[str, JsonValue]:
        """Preserve omitted flags and vendor nulls across persistence/replay."""
        return _METADATA_JSON.validate_python(self.model_dump(mode="json"))


class LLMResponse(BaseModel):
    """Generic LLM response - vendor-agnostic.

    This represents a normalized response from any LLM provider.
    Vendor adapters transform their specific responses into this format.

    This standardization lets platform runners process responses from any
    vendor without vendor-specific logic.
    """

    id: str = Field(..., description="Unique identifier for this response")
    model: str = Field(..., description="Model identifier used for this response")
    content: List[LLMContentBlock] = Field(
        default_factory=list, description="Content blocks in the response"
    )
    stop_reason: LLMStopReason | None = Field(
        None,
        description="Reason the model stopped generating (e.g., 'end_turn', 'max_tokens', 'tool_use')",
    )
    usage: Optional[LLMUsageInfo] = Field(None, description="Token usage information")
    role: str = Field(default="assistant", description="Role of the message author")

    metadata: LLMResponseMetadata = Field(
        default_factory=LLMResponseMetadata,
        description="Typed progress metadata with JSON-only vendor extensions",
    )
