"""AssemblyAI v3 response contracts, parsed before native events leave the reader."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    model_validator,
)


class AssemblyAIEventKind(StrEnum):
    BEGIN = "Begin"
    TURN = "Turn"
    SPEECH_STARTED = "SpeechStarted"
    TERMINATION = "Termination"
    ERROR = "Error"


class AssemblyAIResponse(BaseModel):
    """Unused vendor additions are ignored; consumed fields never bypass validation."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )


class AssemblyAISessionConfiguration(AssemblyAIResponse):
    model: str


class AssemblyAIBegin(AssemblyAIResponse):
    type: Literal[AssemblyAIEventKind.BEGIN]
    id: str = Field(min_length=1)
    expires_at: int = Field(strict=True, ge=0)
    configuration: AssemblyAISessionConfiguration | None = None


class AssemblyAIWord(AssemblyAIResponse):
    """Native word offsets are milliseconds; absent finality is not fabricated."""

    text: str = Field(repr=False)
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=0)
    confidence: float = Field(ge=0, le=1, strict=True)
    word_is_final: StrictBool | None = None
    speaker: str | None = None

    @model_validator(mode="after")
    def require_ordered_offsets(self) -> AssemblyAIWord:
        if self.end < self.start:
            raise ValueError("Word end must not precede its start.")
        return self


class AssemblyAITurn(AssemblyAIResponse):
    type: Literal[AssemblyAIEventKind.TURN]
    turn_order: int = Field(strict=True, ge=0)
    turn_is_formatted: StrictBool
    end_of_turn: StrictBool
    transcript: str = Field(repr=False)
    end_of_turn_confidence: float | None = Field(default=None, ge=0, le=1, strict=True)
    words: tuple[AssemblyAIWord, ...] = Field(repr=False)
    language_code: str | None = None
    language_confidence: float | None = Field(default=None, ge=0, le=1, strict=True)
    speaker_label: str | None = None


class AssemblyAISpeechStarted(AssemblyAIResponse):
    type: Literal[AssemblyAIEventKind.SPEECH_STARTED]
    timestamp: int = Field(strict=True, ge=0)
    confidence: float = Field(ge=0, le=1, strict=True)


class AssemblyAITermination(AssemblyAIResponse):
    type: Literal[AssemblyAIEventKind.TERMINATION]
    audio_duration_seconds: float = Field(ge=0, strict=True)
    session_duration_seconds: float = Field(ge=0, strict=True)


class AssemblyAIError(AssemblyAIResponse):
    type: Literal[AssemblyAIEventKind.ERROR]
    error_code: int = Field(strict=True)
    error: str = Field(repr=False)


AssemblyAIEvent = (
    AssemblyAIBegin
    | AssemblyAITurn
    | AssemblyAISpeechStarted
    | AssemblyAITermination
    | AssemblyAIError
)
_EVENT_ADAPTER = TypeAdapter(
    Annotated[AssemblyAIEvent, Field(discriminator="type")],
    config=ConfigDict(hide_input_in_errors=True),
)


class _Envelope(AssemblyAIResponse):
    type: str


def parse_assemblyai_event(frame: str) -> AssemblyAIEvent | None:
    """Ignore unused event kinds; malformed consumed events fail without raw text."""
    envelope = _Envelope.model_validate_json(frame)
    if envelope.type not in AssemblyAIEventKind:
        return None
    return _EVENT_ADAPTER.validate_json(frame)
