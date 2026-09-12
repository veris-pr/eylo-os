"""Plivo Audio Streaming fields consumed by Eylo, with explicit legacy digits."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Event(StrEnum):
    START = "start"
    MEDIA = "media"
    DTMF = "dtmf"
    LEGACY_DIGITS = "digits"
    PLAY_AUDIO = "playAudio"
    CLEAR_AUDIO = "clearAudio"


class ContentType(StrEnum):
    MULAW = "audio/x-mulaw"


MULAW_SAMPLE_RATE = 8000


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class Start(_WireValue):
    call_id: str = Field(default="", alias="callId")
    stream_id: str = Field(default="", alias="streamId")
    from_number: str = Field(default="", alias="from", repr=False)
    to_number: str = Field(default="", alias="to", repr=False)


class Media(_WireValue):
    payload: str = Field(default="", repr=False, exclude=True)
    timestamp: str | int = ""
    track: str = "inbound"


class Dtmf(_WireValue):
    digit: str | None = Field(default=None, repr=False, exclude=True)
    digits: str | None = Field(default=None, repr=False, exclude=True)

    @property
    def value(self) -> str | None:
        return self.digit or self.digits or None


class StreamMessage(_WireValue):
    event: str = ""
    sequence_number: str | int | None = Field(default=None, alias="sequenceNumber")
    start: Start | None = Field(default=None, repr=False, exclude=True)
    media: Media | None = Field(default=None, repr=False, exclude=True)
    dtmf: Dtmf | str | None = Field(default=None, repr=False, exclude=True)
    digits: Dtmf | str | None = Field(default=None, repr=False, exclude=True)
    digit: str | None = Field(default=None, repr=False, exclude=True)

    @property
    def keypad_digits(self) -> str | None:
        data = self.dtmf or self.digits
        if isinstance(data, Dtmf):
            return data.value
        return data or self.digit or None


class _OutboundValue(_WireValue):
    model_config = ConfigDict(extra="forbid")


class OutboundAudio(_OutboundValue):
    """Plivo requires a numeric sampleRate matching its stream audio format."""

    content_type: Literal[ContentType.MULAW] = Field(
        default=ContentType.MULAW, serialization_alias="contentType"
    )
    sample_rate: int = Field(
        default=MULAW_SAMPLE_RATE, serialization_alias="sampleRate", gt=0
    )
    payload: str = Field(repr=False)


class MediaCommand(_OutboundValue):
    event: Literal[Event.PLAY_AUDIO] = Event.PLAY_AUDIO
    media: OutboundAudio = Field(repr=False)


class ClearCommand(_OutboundValue):
    event: Literal[Event.CLEAR_AUDIO] = Event.CLEAR_AUDIO
    stream_id: str = Field(serialization_alias="streamId")
