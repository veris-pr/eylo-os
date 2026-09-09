"""Validated Sarvam legacy STT messages, separate from platform transcript events."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)


class SarvamMessageType(StrEnum):
    DATA = "data"
    EVENTS = "events"
    ERROR = "error"


class SarvamSignalType(StrEnum):
    START_SPEECH = "START_SPEECH"
    END_SPEECH = "END_SPEECH"


_Text = Annotated[str, Field(strict=True, min_length=1)]
_Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class SarvamTranscriptionMetrics(_Response):
    """Provider durations are seconds, not absolute audio offsets or wall time."""

    audio_duration: _Seconds
    processing_latency: _Seconds


class SarvamTranscriptData(_Response):
    """Only consumed fields; undocumented timestamps/diarization stay unclaimed."""

    request_id: _Text
    transcript: Annotated[str, Field(strict=True, repr=False)]
    metrics: SarvamTranscriptionMetrics
    language_code: _Text | None = None
    language_probability: _Probability | None = None


class SarvamTranscript(_Response):
    type: Literal[SarvamMessageType.DATA]
    data: SarvamTranscriptData = Field(repr=False)


class SarvamVadData(_Response):
    """Retain the vendor's `occured_at` spelling and explicit signal identity."""

    signal_type: SarvamSignalType
    occured_at: _Seconds | None = None
    timestamp: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if self.timestamp is not None and self.timestamp.timestamp() < 0:
            raise ValueError("Sarvam event timestamp must not precede the epoch.")
        return self


class SarvamVadEvent(_Response):
    type: Literal[SarvamMessageType.EVENTS]
    data: SarvamVadData


class SarvamErrorData(_Response):
    """Error codes are opaque vendor data; never echo its diagnostic body."""

    code: _Text = Field(repr=False)
    error: _Text = Field(repr=False)


class SarvamErrorEvent(_Response):
    type: Literal[SarvamMessageType.ERROR]
    data: SarvamErrorData = Field(repr=False)


SarvamSTTEvent = Annotated[
    SarvamTranscript | SarvamVadEvent | SarvamErrorEvent,
    Field(discriminator="type"),
]
_EVENT = TypeAdapter(SarvamSTTEvent)


def parse_sarvam_stt_event(payload: str | bytes) -> SarvamSTTEvent:
    """Reject mismatched envelopes; the SDK 0.1.28 union permits unrelated data."""
    return _EVENT.validate_json(payload)
