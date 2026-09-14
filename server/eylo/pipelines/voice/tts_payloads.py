"""Platform speech requests shared by producers, Redis routing and TTS queues."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    model_validator,
)

from eylo.pipelines.voice.request_state import VoiceRequestSource


class TTSRequestKind(StrEnum):
    """Ordered input operations; finalization closes the selected turn's text."""

    TEXT = "text"
    FINALIZE = "finalize"


class TTSRequestRef(BaseModel):
    """Opaque turn label and platform request identity, absent when uncorrelated."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    turn_id: Annotated[StrictStr, Field(min_length=1)] | None = None
    request_id: UUID | None = None
    policy_source: VoiceRequestSource | None = None

    @model_validator(mode="after")
    def require_policy_identity(self) -> Self:
        if self.policy_source is not None and self.request_id is None:
            raise ValueError("Policy speech requires a platform request identity.")
        return self


class TTSTextRequest(TTSRequestRef):
    """One text segment; whitespace is retained until speech normalization."""

    type: Literal[TTSRequestKind.TEXT] = TTSRequestKind.TEXT
    text: StrictStr = Field(repr=False)


class TTSFinalizeRequest(TTSRequestRef):
    """Finalize text input without manufacturing an empty text segment."""

    type: Literal[TTSRequestKind.FINALIZE] = TTSRequestKind.FINALIZE


type TTSRequest = Annotated[
    TTSTextRequest | TTSFinalizeRequest, Field(discriminator="type")
]

_REQUEST_ADAPTER = TypeAdapter[TTSRequest](
    TTSRequest, config=ConfigDict(hide_input_in_errors=True)
)


def validate_tts_request(request: TTSRequest) -> TTSRequest:
    """Revalidate copied runtime models before queue or playback effects."""
    return _REQUEST_ADAPTER.validate_python(request)


class ConversationTTSRequest(BaseModel):
    """Redis envelope; routing authority is supplied by the platform producer."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    conversation_id: UUID
    payload: TTSRequest
