"""Conversation-owned completion references and final-message projections."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FieldSerializationInfo,
    SerializationInfo,
    SerializeAsAny,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictStr,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from eylo.framework.agents.common import FrameworkMetadata
from eylo.framework.agents.model import ModelResponse, ModelUsage
from eylo.framework.agents.result import RunStatus, run_metadata_from
from eylo.framework.agents.tool import ToolArtifactReference


class ConversationArtifactKind(str, Enum):
    """Artifact kinds whose authority is owned by this pipeline."""

    MESSAGE = "conversation_message"


class ConversationMessageArtifact(BaseModel):
    """Message identity only; resolving it still requires conversation authority."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    kind: Literal[ConversationArtifactKind.MESSAGE] = ConversationArtifactKind.MESSAGE
    id: UUID

    def to_framework(self) -> ToolArtifactReference:
        return ToolArtifactReference(kind=self.kind.value, id=str(self.id))


class ConversationRunSummary(BaseModel):
    """Persisted product references and usage, never a provider response body."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    kind: Literal[ConversationArtifactKind.MESSAGE] = ConversationArtifactKind.MESSAGE
    conversation_id: UUID
    origin_message_id: UUID
    final_message_id: UUID
    framework_run_id: UUID
    framework_status: RunStatus
    usage: ModelUsage


class _MetadataMirror(str, Enum):
    """Legacy top-level fields projected from the authoritative run metadata."""

    APPROVAL = "approval_request"
    INPUT = "input_request"
    CONTINUATION = "continuation"
    TERMINAL = "terminal_response"
    TOOL_CALL = "terminal_tool_call_id"


def _named_field_selection(
    selection: dict[int | str, object] | set[int | str] | None,
) -> dict[str, object] | set[str] | None:
    """Model fields use names; sequence-index selections cannot match them."""
    if isinstance(selection, dict):
        return {key: value for key, value in selection.items() if isinstance(key, str)}
    if isinstance(selection, set):
        return {key for key in selection if isinstance(key, str)}
    return None


class FrameworkTerminalMessageMeta(BaseModel):
    """Validated final-message data with one authority for completion/pause fields."""

    model_config = ConfigDict(
        frozen=True,
        extra="allow",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    framework: Literal[True] = True
    run_id: UUID
    status: RunStatus
    model: StrictStr
    usage: ModelUsage
    error: StrictBool
    run_metadata: SerializeAsAny[FrameworkMetadata] = Field(
        default_factory=FrameworkMetadata, validate_default=True
    )
    llm_response: ModelResponse | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_mirrors(cls, value: object) -> object:
        """Old stored mirrors are redundant; canonical metadata owns readback."""
        if not isinstance(value, dict):
            return value
        return {key: item for key, item in value.items() if key not in _MetadataMirror}

    @field_validator("run_metadata", mode="before")
    @classmethod
    def restore_run_metadata(cls, value: object, info: ValidationInfo) -> object:
        status = info.data.get("status")
        if not isinstance(status, RunStatus):
            return value
        return run_metadata_from(status, value)

    @field_serializer("llm_response")
    def serialize_replay(
        self, value: ModelResponse | None, info: FieldSerializationInfo
    ) -> dict[str, object] | None:
        """Replay omits null model fields; run metadata keeps its existing nulls."""
        if value is None:
            return None
        return value.model_dump(
            mode=info.mode,
            include=_named_field_selection(info.include),
            exclude=_named_field_selection(info.exclude),
            context=info.context,
            by_alias=info.by_alias,
            exclude_unset=info.exclude_unset,
            exclude_defaults=info.exclude_defaults,
            exclude_none=True,
            round_trip=info.round_trip,
            serialize_as_any=info.serialize_as_any,
        )

    @model_serializer(mode="wrap")
    def serialize_message(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, object]:
        """Mirror serialized public fields only; never serialize owner-private data."""
        data = handler(self)
        metadata = data.get("run_metadata")
        # Stored legacy mirrors are not a second authority on readback. Remove
        # them even when the caller excludes the canonical metadata projection.
        for mirror in _MetadataMirror:
            data.pop(mirror.value, None)
        if isinstance(metadata, dict):
            public_controls = {
                key: value for key, value in metadata.items() if key in _MetadataMirror
            }
            data.update(
                FrameworkMetadata.model_validate(public_controls).model_dump(
                    mode=info.mode,
                    include=_named_field_selection(info.include),
                    exclude=_named_field_selection(info.exclude),
                )
            )
        if self.llm_response is None:
            data.pop("llm_response", None)
        return data
