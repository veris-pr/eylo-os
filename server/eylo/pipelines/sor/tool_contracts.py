"""Typed model-facing SOR result envelopes and private execution metadata."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.sor.runtime.commands import SorCommandReceipt
from eylo.sor.shared.contracts import SorCommandState, SorProfile, SorToolEffect
from eylo.sor.shared.json_values import SorJsonValue


class SorToolResultKind(StrEnum):
    READ = "sor_result"
    COMMAND = "sor_command_result"
    COMMAND_ERROR = "sor_command_error"
    ERROR = "sor_error"
    SOURCE_SELECTION = "sor_source_selection_required"


class SorToolErrorCode(StrEnum):
    TOOL_UNAVAILABLE = "sor_tool_unavailable"
    INPUT_INVALID = "sor_tool_input_invalid"
    SOURCE_UNAVAILABLE = "sor_source_unavailable"
    SOURCE_SELECTION_REQUIRED = "sor_source_selection_required"
    RUN_CONFLICT = "agent_run_conflict"
    RESOURCE_UNAVAILABLE = "sor_resource_unavailable"
    REQUEST_INVALID = "sor_request_invalid"


class _SorToolValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class SorReadToolResult(_SorToolValue):
    kind: Literal[SorToolResultKind.READ] = SorToolResultKind.READ
    data: dict[str, SorJsonValue] = Field(repr=False)


class SorCommandToolResult(_SorToolValue):
    kind: Literal[SorToolResultKind.COMMAND] = SorToolResultKind.COMMAND
    data: SorCommandReceipt = Field(repr=False)
    error: None = None
    message: None = None

    @model_validator(mode="after")
    def require_successful_receipt(self) -> Self:
        """A pending or failed command cannot be presented as a successful tool result."""
        if self.data.state is not SorCommandState.SUCCEEDED:
            raise ValueError("Successful SOR tool results require a succeeded command.")
        return self


class SorCommandToolError(_SorToolValue):
    kind: Literal[SorToolResultKind.COMMAND_ERROR] = SorToolResultKind.COMMAND_ERROR
    data: None = None
    error: str | None
    message: str | None = Field(repr=False)


class SorToolError(_SorToolValue):
    kind: Literal[SorToolResultKind.ERROR] = SorToolResultKind.ERROR
    error: str


class SorSourceChoice(_SorToolValue):
    source_id: UUID
    name: str
    vendor_key: str


class SorSourceSelectionRequired(_SorToolValue):
    kind: Literal[SorToolResultKind.SOURCE_SELECTION] = (
        SorToolResultKind.SOURCE_SELECTION
    )
    error: Literal[SorToolErrorCode.SOURCE_SELECTION_REQUIRED] = (
        SorToolErrorCode.SOURCE_SELECTION_REQUIRED
    )
    sources: tuple[SorSourceChoice, ...]


class SorToolMetadata(_SorToolValue):
    """Known dispatcher evidence; domain/vendor error codes retain their namespace."""

    sor_execution: Literal[True] = True
    profile: SorProfile | None = None
    tool: str | None = None
    effect: SorToolEffect | None = None
    command_id: UUID | None = None
    command_state: SorCommandState | None = None
    error_code: str | None = None
    source_selection_required: Literal[True] | None = None


type SorToolContent = Annotated[
    SorReadToolResult
    | SorCommandToolResult
    | SorCommandToolError
    | SorToolError
    | SorSourceSelectionRequired,
    Field(discriminator="kind"),
]


class SorToolExecutionOutcome(_SorToolValue):
    """Private envelope; the framework boundary explicitly projects tool content."""

    content: SorToolContent = Field(repr=False, exclude=True)
    metadata: SorToolMetadata

    @property
    def is_error(self) -> bool:
        return self.content.kind not in {
            SorToolResultKind.READ,
            SorToolResultKind.COMMAND,
        }
