"""Provider-agnostic model contracts for framework runs."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self
from uuid import UUID

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    SerializeAsAny,
    SerializerFunctionWrapHandler,
    StrictStr,
    field_serializer,
    model_validator,
)

from .common import FrameworkMetadata, FrozenFrameworkModel, JsonObject
from .config import RunPromptCaching, validate_mode_snapshot
from .tool import ToolCall

if TYPE_CHECKING:
    from .context import RunInput


class ModelSettings(FrozenFrameworkModel):
    """Typed model configuration for one agent or run."""

    model_config = ConfigDict(
        strict=True,
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    provider_config_id: UUID | None = None
    provider_config_revision: int | None = Field(default=None, gt=0, strict=True)
    model: str | None = None
    vendor: str | None = None
    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, strict=True)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0, strict=True)
    top_k: int | None = Field(default=None, gt=0, strict=True)
    stop_sequences: tuple[str, ...] | None = None
    prompt_caching: Annotated[
        RunPromptCaching, BeforeValidator(validate_mode_snapshot)
    ] = RunPromptCaching.DISABLED
    reasoning: dict[str, JsonValue] | None = None


class ModelStopReason(str, Enum):
    """Framework stop vocabulary, translated by each embedding application."""

    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    TOOL_USE = "tool_use"
    PAUSE_TURN = "pause_turn"
    REFUSAL = "refusal"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class ModelBlockKind(str, Enum):
    """Normalized model output block kind."""

    TEXT = "text"
    TOOL_CALL = "tool_call"
    REASONING = "reasoning"


class _ModelOutputBlock(FrozenFrameworkModel):
    """Revalidate returned/copy-built blocks before a runner consumes them."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)


class ModelTextBlock(_ModelOutputBlock):
    """Visible text eligible for messages and speech, never executable data."""

    kind: Literal[ModelBlockKind.TEXT] = ModelBlockKind.TEXT
    content: StrictStr


class ModelToolCallBlock(_ModelOutputBlock):
    """Exact executable command; private tool metadata stays out of snapshots."""

    kind: Literal[ModelBlockKind.TOOL_CALL] = ModelBlockKind.TOOL_CALL
    content: ToolCall = Field(repr=False)

    @field_serializer("content", mode="wrap")
    def serialize_content(
        self, value: ToolCall, handler: SerializerFunctionWrapHandler
    ) -> JsonObject:
        """Keep the existing command wire fields, excluding opaque annotations."""
        content = handler(value.model_copy(update={"metadata": FrameworkMetadata()}))
        content.pop("metadata", None)
        return content


class ModelReasoningBlock(_ModelOutputBlock):
    """Reasoning remains distinct from visible text and tool authority."""

    kind: Literal[ModelBlockKind.REASONING] = ModelBlockKind.REASONING
    content: StrictStr


ModelOutputBlock = Annotated[
    ModelTextBlock | ModelToolCallBlock | ModelReasoningBlock,
    Field(discriminator="kind"),
]


class ModelUsage(FrozenFrameworkModel):
    """Nonnegative token totals; zero also initializes accumulators and replay."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    input_tokens: int = Field(default=0, ge=0, strict=True)
    output_tokens: int = Field(default=0, ge=0, strict=True)
    cache_creation_input_tokens: int = Field(default=0, ge=0, strict=True)
    cache_read_input_tokens: int = Field(default=0, ge=0, strict=True)
    reasoning_tokens: int = Field(default=0, ge=0, strict=True)

    @property
    def total_tokens(self) -> int:
        """Sum input/output counts without adding overlapping detail counters."""
        return self.input_tokens + self.output_tokens


class ModelResponse(FrozenFrameworkModel):
    """Provider-neutral model response consumed by the framework runner."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    id: str
    model: str
    blocks: tuple[ModelOutputBlock, ...] = ()
    usage: ModelUsage = Field(default_factory=ModelUsage)
    stop_reason: ModelStopReason | None = None
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )

    @model_validator(mode="after")
    def unique_tool_call_identities(self) -> Self:
        """One response cannot alias two commands to the same result/receipt ID."""
        seen: set[str] = set()
        for block in self.blocks:
            if block.kind is not ModelBlockKind.TOOL_CALL:
                continue
            if block.content.id in seen:
                raise ValueError(
                    "Model response contains duplicate tool call identities."
                )
            seen.add(block.content.id)
        return self


class Model(Protocol):
    """Protocol implemented by model adapters used by ``FrameworkRunner``."""

    async def generate(
        self,
        run_input: RunInput,
        settings: ModelSettings,
    ) -> ModelResponse:
        """Generate one complete model response."""
        ...
