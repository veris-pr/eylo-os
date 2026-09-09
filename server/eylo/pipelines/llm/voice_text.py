"""Validated correlation and progress for ordered LLM-to-speech delivery."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class VoiceTextPhase(Enum):
    """Whether more model text may follow before TTS finalization."""

    PARTIAL = "partial"
    COMPLETE = "complete"


class VoiceTurnRef(BaseModel):
    """Caller-owned turn/request identity; optional for uncorrelated delivery."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    turn_id: UUID | None = None
    request_id: UUID | None = None


class VoiceTextSegment(VoiceTurnRef):
    """One org/conversation-scoped segment; completion may include final text."""

    organization_id: UUID
    conversation_id: UUID
    text: StrictStr = Field(repr=False)
    phase: VoiceTextPhase = Field(strict=True)
