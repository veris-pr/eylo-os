"""Deepgram Listen v2 wire contracts; vendor names never become platform policy."""

from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class FluxModel(StrEnum):
    GENERAL_EN = "flux-general-en"
    GENERAL_MULTI = "flux-general-multi"


class FluxEncoding(StrEnum):
    LINEAR16 = "linear16"
    LINEAR32 = "linear32"
    MULAW = "mulaw"
    ALAW = "alaw"
    OPUS = "opus"
    OGG_OPUS = "ogg-opus"


class FluxSampleRate(IntEnum):
    HZ_8000 = 8000
    HZ_16000 = 16000
    HZ_24000 = 24000
    HZ_44100 = 44100
    HZ_48000 = 48000


FluxEOTThreshold = Annotated[
    float, Field(strict=True, ge=0.5, le=1.0, allow_inf_nan=False)
]
FluxEOTTimeout = Annotated[int, Field(strict=True, ge=500, le=60000)]


class FluxListenQuery(BaseModel):
    """Explicit raw-audio request; container auto-detection is a different contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    model: FluxModel
    encoding: FluxEncoding
    sample_rate: int = Field(strict=True)
    eot_threshold: FluxEOTThreshold
    eot_timeout_ms: FluxEOTTimeout

    @model_validator(mode="after")
    def validate_sample_rate(self) -> Self:
        FluxSampleRate(self.sample_rate)
        return self


class FluxMessageType(StrEnum):
    CONNECTED = "Connected"
    TURN_INFO = "TurnInfo"
    ERROR = "Error"
    CLOSE_STREAM = "CloseStream"


class FluxTurnEvent(StrEnum):
    START_OF_TURN = "StartOfTurn"
    UPDATE = "Update"
    EAGER_END_OF_TURN = "EagerEndOfTurn"
    END_OF_TURN = "EndOfTurn"
    TURN_RESUMED = "TurnResumed"


class FluxTurnTrigger(StrEnum):
    MODEL = "model"
    MANUAL = "manual"
    TIMEOUT = "timeout"


_Text = Annotated[str, Field(strict=True, min_length=1)]
_Sequence = Annotated[int, Field(strict=True, ge=0)]
_Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Probability = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class FluxWord(_Response):
    """Older responses omit word timestamps; absent timing must remain absent."""

    word: _Text = Field(repr=False)
    confidence: _Probability
    start: _Seconds | None = None
    end: _Seconds | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if (self.start is None) != (self.end is None):
            raise ValueError("Flux word timing requires both bounds.")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("Flux word timing must not run backwards.")
        return self


class FluxConnected(_Response):
    type: Literal[FluxMessageType.CONNECTED]
    request_id: _Text
    sequence_id: _Sequence


class FluxTurnInfo(_Response):
    """The turn confidence is not recognition confidence; windows use seconds."""

    type: Literal[FluxMessageType.TURN_INFO]
    request_id: _Text
    sequence_id: _Sequence
    event: FluxTurnEvent
    turn_index: _Sequence
    audio_window_start: _Seconds
    audio_window_end: _Seconds
    transcript: str = Field(strict=True, repr=False)
    words: tuple[FluxWord, ...] = Field(repr=False)
    end_of_turn_confidence: _Probability
    trigger: FluxTurnTrigger | None = None
    languages: tuple[_Text, ...] | None = None
    languages_hinted: tuple[_Text, ...] | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.audio_window_end < self.audio_window_start:
            raise ValueError("Flux audio window must not run backwards.")
        return self


class FluxError(_Response):
    """The provider's diagnostic text is private; error codes remain opaque."""

    type: Literal[FluxMessageType.ERROR]
    sequence_id: _Sequence
    code: _Text = Field(repr=False)
    description: _Text = Field(repr=False)


class FluxCloseStream(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal[FluxMessageType.CLOSE_STREAM] = FluxMessageType.CLOSE_STREAM


FluxResponse = Annotated[
    FluxConnected | FluxTurnInfo | FluxError, Field(discriminator="type")
]
_RESPONSE = TypeAdapter(FluxResponse)


def parse_flux_response(payload: str) -> FluxResponse:
    """Validate messages consumed by this client; unknown envelopes fail visibly."""
    return _RESPONSE.validate_json(payload)
