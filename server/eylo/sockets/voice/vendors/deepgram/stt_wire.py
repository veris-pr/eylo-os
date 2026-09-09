"""Deepgram Listen v1 requests and responses; vendor seconds never mean wall time."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)


class DeepgramMessage(StrEnum):
    """Listen v1 protocol vocabulary, separate from Flux v2 and platform events."""

    RESULTS = "Results"
    METADATA = "Metadata"
    SPEECH_STARTED = "SpeechStarted"
    UTTERANCE_END = "UtteranceEnd"
    FINALIZE = "Finalize"
    CLOSE_STREAM = "CloseStream"
    KEEP_ALIVE = "KeepAlive"


class DeepgramEncoding(StrEnum):
    """The native client sends mono signed 16-bit PCM only."""

    LINEAR16 = "linear16"


class DeepgramListenQuery(BaseModel):
    """Configured native options; no model/language fallback or arbitrary URL keys."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    model: str = Field(min_length=1, pattern=r"\S")
    language: str = Field(min_length=1, pattern=r"\S")
    sample_rate: int = Field(default=16000, strict=True, gt=0)
    encoding: DeepgramEncoding = DeepgramEncoding.LINEAR16
    channels: Literal[1] = 1
    interim_results: StrictBool = True
    punctuate: StrictBool = True
    smart_format: StrictBool = False
    vad_events: StrictBool = True
    endpointing: Annotated[StrictInt, Field(ge=0)] | StrictBool | None = None
    utterance_end_ms: int | None = Field(default=None, strict=True, ge=1000, le=5000)

    @field_validator("channels", mode="before")
    @classmethod
    def validate_mono_channel(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("Deepgram PCM input requires exactly one integer channel.")
        return value

    @model_validator(mode="after")
    def validate_detection(self) -> "DeepgramListenQuery":
        if self.endpointing is True:
            raise ValueError("Deepgram endpointing requires milliseconds or false.")
        if self.utterance_end_ms is not None and not self.interim_results:
            raise ValueError("Deepgram utterance_end_ms requires interim_results.")
        return self

    def query_parameters(self) -> dict[str, str]:
        """HTTP query booleans use lowercase text, not Python repr or integer coercion."""
        return {
            key: str(value).lower() if isinstance(value, bool) else str(value)
            for key, value in self.model_dump(mode="json", exclude_none=True).items()
        }


class DeepgramControl(BaseModel):
    """Text-frame controls; Finalize keeps the connection open, CloseStream ends it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal[
        DeepgramMessage.FINALIZE,
        DeepgramMessage.CLOSE_STREAM,
        DeepgramMessage.KEEP_ALIVE,
    ]


class _Response(BaseModel):
    """Validate consumed fields, tolerate additive vendor fields, hide private input."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", allow_inf_nan=False, hide_input_in_errors=True
    )


Seconds = Annotated[float, Field(strict=True, ge=0)]
Confidence = Annotated[float, Field(strict=True, ge=0, le=1)]
ChannelIndex = Annotated[int, Field(strict=True, ge=0)]


class DeepgramWord(_Response):
    """Audio-relative word timing and optional native speaker attribution."""

    word: str = Field(repr=False)
    start: Seconds
    end: Seconds
    confidence: Confidence | None = None
    punctuated_word: str | None = Field(default=None, repr=False)
    speaker: ChannelIndex | None = None
    language: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "DeepgramWord":
        if self.end < self.start:
            raise ValueError("Deepgram word end precedes its start.")
        return self


class DeepgramAlternative(_Response):
    """One complete segment hypothesis, not one word or the whole recognition session."""

    transcript: str = Field(repr=False)
    confidence: Confidence | None = None
    words: tuple[DeepgramWord, ...] = Field(default=(), repr=False)
    languages: tuple[str, ...] = ()


class DeepgramChannel(_Response):
    alternatives: tuple[DeepgramAlternative, ...] = Field(repr=False)


class DeepgramModelInfo(_Response):
    name: str | None = None
    version: str | None = None
    arch: str | None = None


class DeepgramResultMetadata(_Response):
    request_id: str | None = None
    model_info: DeepgramModelInfo | None = None
    model_uuid: str | None = None


class DeepgramResults(_Response):
    """Segment finality and a speech boundary are distinct native facts."""

    type: Literal[DeepgramMessage.RESULTS]
    channel_index: tuple[ChannelIndex, ...]
    start: Seconds
    duration: Seconds
    channel: DeepgramChannel
    is_final: StrictBool
    speech_final: StrictBool = False
    from_finalize: StrictBool = False
    metadata: DeepgramResultMetadata | None = None


class DeepgramMetadata(_Response):
    """Terminal recognition summary, including valid zero-audio sessions."""

    type: Literal[DeepgramMessage.METADATA]
    request_id: str
    duration: Seconds
    channels: ChannelIndex


class DeepgramSpeechStarted(_Response):
    type: Literal[DeepgramMessage.SPEECH_STARTED]
    channel: tuple[ChannelIndex, ...]
    timestamp: Seconds


class DeepgramUtteranceEnd(_Response):
    type: Literal[DeepgramMessage.UTTERANCE_END]
    channel: tuple[ChannelIndex, ...]
    last_word_end: Seconds


DeepgramEvent = Annotated[
    DeepgramResults | DeepgramMetadata | DeepgramSpeechStarted | DeepgramUtteranceEnd,
    Field(discriminator="type"),
]
_EVENT = TypeAdapter(DeepgramEvent, config=ConfigDict(hide_input_in_errors=True))


def parse_deepgram_event(data: str) -> DeepgramEvent:
    """Malformed/unknown messages fail visibly; never disguise a protocol error as silence."""
    return _EVENT.validate_json(data)
