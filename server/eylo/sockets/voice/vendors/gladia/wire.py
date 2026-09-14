"""Gladia Live v2 wire contracts; remote protocol details stay inside the vendor."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.schemas import STTEncoding

GLADIA_LIVE_URL = "https://api.gladia.io/v2/live"
_GLADIA_WEBSOCKET_HOST = "api.gladia.io"
_GLADIA_WEBSOCKET_PATH = "/v2/live"
_TLS_PORT = 443
_Text = Annotated[str, Field(strict=True, min_length=1)]
_Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Confidence = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
_Channel = Annotated[int, Field(strict=True, ge=0)]
PCM_SAMPLE_BYTES = 2
_BUFFER_SECONDS = 0.1


class GladiaEncoding(StrEnum):
    PCM = "wav/pcm"


class GladiaSampleRate(IntEnum):
    HZ_8000 = 8000
    HZ_16000 = 16000
    HZ_32000 = 32000
    HZ_44100 = 44100
    HZ_48000 = 48000


class GladiaMessageType(StrEnum):
    TRANSCRIPT = "transcript"
    START_SESSION = "start_session"
    START_RECORDING = "start_recording"
    END_RECORDING = "end_recording"
    END_SESSION = "end_session"
    STOP_RECORDING = "stop_recording"


class GladiaConfig(BaseModel):
    """Resolved PCM settings; frozen data is separate from the resource owner."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
        str_strip_whitespace=True,
    )
    api_key: SecretStr = Field(min_length=1, exclude=True, repr=False)
    language: _Text
    sample_rate: int = Field(default=GladiaSampleRate.HZ_16000, strict=True)
    encoding: STTEncoding = STTEncoding.LINEAR16
    buffer_size_seconds: float = Field(
        default=_BUFFER_SECONDS, strict=True, gt=0, allow_inf_nan=False
    )
    interim_results: SpeechOption = SpeechOptionState.ENABLED

    @model_validator(mode="after")
    def pcm_input(self) -> Self:
        GladiaSampleRate(self.sample_rate)
        if self.encoding not in {STTEncoding.LINEAR16, STTEncoding.PCM_S16LE}:
            raise ValueError("Gladia STT requires mono PCM16 input.")
        return self

    def live_request(self) -> GladiaLiveRequest:
        return GladiaLiveRequest(
            sample_rate=GladiaSampleRate(self.sample_rate),
            language_config=GladiaLanguageConfig(languages=(self.language,)),
            messages_config=GladiaMessagesConfig(
                receive_partial_transcripts=self.interim_results
                is SpeechOptionState.ENABLED,
            ),
        )

    @property
    def buffer_threshold(self) -> int:
        return (
            max(1, int(self.buffer_size_seconds * self.sample_rate)) * PCM_SAMPLE_BYTES
        )


class _Request(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class GladiaLanguageConfig(_Request):
    """A configured language remains explicit; this is not automatic detection."""

    languages: tuple[_Text, ...] = Field(min_length=1, max_length=1)
    code_switching: Literal[False] = False


class GladiaMessagesConfig(_Request):
    """Request only live transcripts and lifecycle controls, not add-on outputs."""

    receive_partial_transcripts: StrictBool
    receive_final_transcripts: Literal[True] = True
    receive_speech_events: Literal[False] = False
    receive_pre_processing_events: Literal[False] = False
    receive_realtime_processing_events: Literal[False] = False
    receive_post_processing_events: Literal[False] = False
    receive_acknowledgments: Literal[False] = False
    receive_errors: Literal[True] = True
    receive_lifecycle_events: Literal[True] = True


class GladiaLiveRequest(_Request):
    """PCM16 mono only; do not substitute an invented model or enable add-ons."""

    encoding: GladiaEncoding = GladiaEncoding.PCM
    bit_depth: Literal[16] = 16
    sample_rate: GladiaSampleRate
    channels: Literal[1] = 1
    language_config: GladiaLanguageConfig
    messages_config: GladiaMessagesConfig

    @field_validator("sample_rate", mode="before")
    @classmethod
    def integer_sample_rate(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Gladia sample rate must be an integer.")
        return value


class GladiaStopRecording(_Request):
    type: Literal[GladiaMessageType.STOP_RECORDING] = GladiaMessageType.STOP_RECORDING


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class GladiaLiveSession(_Response):
    """The returned URL is a bearer credential, not an unrestricted egress target."""

    id: UUID
    created_at: AwareDatetime
    url: SecretStr = Field(exclude=True, repr=False)

    @field_validator("url")
    @classmethod
    def pinned_websocket_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if any(character.isspace() or ord(character) < 32 for character in raw):
            raise ValueError("Gladia returned an invalid WebSocket URL.")
        parsed = urlsplit(raw)
        if (
            parsed.scheme != "wss"
            or parsed.hostname != _GLADIA_WEBSOCKET_HOST
            or parsed.port not in (None, _TLS_PORT)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != _GLADIA_WEBSOCKET_PATH
            or parsed.fragment
        ):
            raise ValueError("Gladia returned an unexpected WebSocket destination.")
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if set(query) != {"token"} or len(query["token"]) != 1 or not query["token"][0]:
            raise ValueError("Gladia returned an invalid session token.")
        return value


class GladiaWord(_Response):
    word: str = Field(strict=True, repr=False)
    start: _Seconds | None = None
    end: _Seconds | None = None
    confidence: _Confidence | None = None

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("Gladia word end precedes its start.")
        return self


class GladiaUtterance(_Response):
    text: str = Field(strict=True, repr=False)
    start: _Seconds
    end: _Seconds
    confidence: _Confidence | None = None
    channel: _Channel
    language: _Text | None = None
    words: tuple[GladiaWord, ...] = Field(default=(), repr=False)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end < self.start:
            raise ValueError("Gladia utterance end precedes its start.")
        return self


class GladiaTranscriptData(_Response):
    id: _Text
    is_final: StrictBool
    utterance: GladiaUtterance


class _Event(_Response):
    session_id: UUID
    created_at: AwareDatetime
    # A non-null native failure must not be accepted as a successful event.
    error: None = None


class GladiaTranscript(_Event):
    type: Literal[GladiaMessageType.TRANSCRIPT]
    data: GladiaTranscriptData


class GladiaLifecycle(_Event):
    type: Literal[
        GladiaMessageType.START_SESSION,
        GladiaMessageType.START_RECORDING,
        GladiaMessageType.END_SESSION,
    ]


class GladiaEndRecordingData(_Response):
    # The vendor's reason is diagnostic data, not a platform lifecycle choice.
    reason: _Text
    received_total_bytes: int = Field(strict=True, ge=0)


class GladiaEndRecording(_Event):
    type: Literal[GladiaMessageType.END_RECORDING]
    data: GladiaEndRecordingData


GladiaEvent = Annotated[
    GladiaTranscript | GladiaLifecycle | GladiaEndRecording,
    Field(discriminator="type"),
]
_EVENT = TypeAdapter(GladiaEvent)


def parse_gladia_event(message: str | bytes) -> GladiaEvent:
    """Validate the subscribed event set; errors and unsupported kinds fail closed."""
    return _EVENT.validate_json(message)
