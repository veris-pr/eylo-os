"""Typed item stream produced by framework runs."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    SerializeAsAny,
    SerializerFunctionWrapHandler,
    StrictStr,
    field_serializer,
)

from .common import FrameworkMetadata, FrozenFrameworkModel, JsonObject
from .interruptions import RunApprovalInterruption, RunInputInterruption
from .tool import ToolCall, ToolResult


class RunItemKind(str, Enum):
    """Kinds of items emitted during a run."""

    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    HANDOFF = "handoff"
    TOKEN_DELTA = "token_delta"
    PROGRESS = "progress"
    INPUT_REQUEST = "input_request"
    APPROVAL_REQUEST = "approval_request"
    SANDBOX_ARTIFACT = "sandbox_artifact"
    ERROR = "error"


class _RunItem(FrozenFrameworkModel):
    """Identity and presentation shared by inspectable run items."""

    model_config = ConfigDict(
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    message: str | None = None
    metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata
    )


class RunToolCallItem(_RunItem):
    """A typed call observation, without exporting private executor metadata."""

    kind: Literal[RunItemKind.TOOL_CALL] = RunItemKind.TOOL_CALL
    payload: ToolCall = Field(repr=False)

    @field_serializer("payload", mode="wrap")
    def serialize_payload(
        self,
        value: ToolCall,
        handler: SerializerFunctionWrapHandler,
    ) -> JsonObject:
        payload = handler(value.model_copy(update={"metadata": FrameworkMetadata()}))
        payload.pop("metadata", None)
        return payload


class RunToolResultItem(_RunItem):
    """A typed result observation retaining its originating command identity."""

    kind: Literal[RunItemKind.TOOL_RESULT] = RunItemKind.TOOL_RESULT
    payload: ToolResult = Field(repr=False)

    @field_serializer("payload", mode="wrap")
    def serialize_payload(
        self,
        value: ToolResult,
        handler: SerializerFunctionWrapHandler,
    ) -> JsonObject:
        payload = handler(value.model_copy(update={"metadata": FrameworkMetadata()}))
        payload.pop("metadata", None)
        return payload


class RunMessagePayload(FrozenFrameworkModel):
    """Assistant output presented by the runner, separate from model input."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    role: Literal["assistant"] = "assistant"
    content: StrictStr


class RunMessageItem(_RunItem):
    """Typed assistant message observation."""

    kind: Literal[RunItemKind.MESSAGE] = RunItemKind.MESSAGE
    payload: RunMessagePayload


class RunApprovalRequestItem(_RunItem):
    """Approval pause that cannot carry an input-only continuation."""

    kind: Literal[RunItemKind.APPROVAL_REQUEST] = RunItemKind.APPROVAL_REQUEST
    payload: RunApprovalInterruption


class RunInputRequestItem(_RunItem):
    """Input pause that cannot carry an approval-only continuation."""

    kind: Literal[RunItemKind.INPUT_REQUEST] = RunItemKind.INPUT_REQUEST
    payload: RunInputInterruption


class RunSignalItem(_RunItem):
    """Reserved observations without active producers; never a typed-item fallback."""

    model_config = ConfigDict(allow_inf_nan=False)

    kind: Literal[
        RunItemKind.HANDOFF,
        RunItemKind.TOKEN_DELTA,
        RunItemKind.PROGRESS,
        RunItemKind.SANDBOX_ARTIFACT,
        RunItemKind.ERROR,
    ]
    payload: dict[str, JsonValue] = Field(default_factory=dict)


RunItem = Annotated[
    RunToolCallItem
    | RunToolResultItem
    | RunMessageItem
    | RunApprovalRequestItem
    | RunInputRequestItem
    | RunSignalItem,
    Field(discriminator="kind"),
]
