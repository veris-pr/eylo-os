"""Tool contracts for framework-managed agent capabilities."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Annotated, Protocol

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    SerializationInfo,
    SerializeAsAny,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictStr,
    field_validator,
    model_serializer,
)

from .common import FrameworkMetadata, FrozenFrameworkModel, JsonObject

if TYPE_CHECKING:
    from .context import RunContext

ToolIdentity = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class ToolCompletionMode(Enum):
    """Executor decision; the existing snapshot representation remains boolean."""

    CONTINUE = False
    COMPLETE = True

    def __bool__(self) -> bool:
        raise TypeError("Compare completion modes with their explicit enum member.")


def completion_mode_from(value: object) -> ToolCompletionMode:
    """Accept native modes or exact legacy wire booleans, never truthy aliases."""
    if isinstance(value, ToolCompletionMode):
        return value
    if value is True:
        return ToolCompletionMode.COMPLETE
    if value is False:
        return ToolCompletionMode.CONTINUE
    raise ValueError("Tool completion requires an explicit mode or boolean snapshot.")


class ToolArtifactReference(FrozenFrameworkModel):
    """Opaque application artifact identity; only its owner grants access."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    kind: StrictStr = Field(min_length=1, pattern=r"\S")
    id: StrictStr = Field(min_length=1, pattern=r"\S")


class CompletionMetadata(FrameworkMetadata):
    """Completion control shared by executor results and run conclusions."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    terminal_response: ToolCompletionMode
    terminal_artifact: ToolArtifactReference | None = None

    @field_validator("terminal_response", mode="before")
    @classmethod
    def validate_completion_mode(cls, value: object) -> ToolCompletionMode:
        return completion_mode_from(value)

    @model_serializer(mode="wrap")
    def serialize_control(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, object]:
        """Do not add absent optional controls to existing tool/run snapshots."""
        data = handler(self)
        for name in ("terminal_artifact", "terminal_output"):
            if name not in self.model_fields_set:
                data.pop(name, None)
        return data


class ToolCompletionMetadata(CompletionMetadata):
    """Executor-owned finish decision with optional replacement text."""

    terminal_output: StrictStr | None = None


class ToolKind(str, Enum):
    """Framework-visible tool family."""

    SYSTEM = "system"
    LOCAL = "local"
    API = "api"
    SANDBOX = "sandbox"
    HANDOFF = "handoff"


class ToolExecutionMode(str, Enum):
    """How a tool call may be executed."""

    AUTO = "auto"
    REQUIRES_APPROVAL = "requires_approval"
    DISABLED = "disabled"


class ToolSpec(FrozenFrameworkModel):
    """Tool definition exposed to a model."""

    name: str
    description: str
    kind: ToolKind
    input_schema: JsonObject = Field(default_factory=dict)
    execution_mode: ToolExecutionMode = ToolExecutionMode.AUTO
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )


class ToolCall(FrozenFrameworkModel):
    """Exact model command; IDs are nonblank and arguments are finite JSON."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    id: ToolIdentity
    name: ToolIdentity
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )


class ToolResult(FrozenFrameworkModel):
    """Finite JSON/text result tied to the exact invocation it completes."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    tool_call_id: ToolIdentity
    content: str | dict[str, JsonValue] | list[JsonValue]
    is_error: StrictBool = False
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_completion_metadata(cls, value: object) -> object:
        """Restore controls before callbacks; preserve owner-private exclusions."""
        if isinstance(value, ToolCompletionMetadata):
            return type(value).model_validate(value)
        fields = value.model_dump() if isinstance(value, FrameworkMetadata) else value
        if isinstance(fields, dict) and "terminal_response" in fields:
            return ToolCompletionMetadata.model_validate(fields)
        return value


class ToolExecutor(Protocol):
    """Protocol for tool dispatch in the new framework path."""

    async def execute(
        self,
        context: RunContext,
        call: ToolCall,
    ) -> ToolResult:
        """Execute one tool call and return its result."""
        ...
