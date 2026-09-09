"""Deepgram Aura v1 synthesis settings and native WebSocket control contracts."""

from enum import Enum, IntEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSProvider

DEEPGRAM_TTS_URL = "wss://api.deepgram.com/v1/speak"
DEEPGRAM_AUTH_HEADER = "Authorization"


class DeepgramTTSEncoding(str, Enum):
    LINEAR16 = "linear16"
    MULAW = "mulaw"
    ALAW = "alaw"


class DeepgramTTSRate(IntEnum):
    HZ_8000 = 8000
    HZ_16000 = 16000
    HZ_24000 = 24000
    HZ_32000 = 32000
    HZ_48000 = 48000


class DeepgramTTSState(str, Enum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    FAILED = "failed"


class DeepgramTTSConfig(TTSAdapterConfig):
    """Native raw audio only; incompatible codec/rate pairs fail before I/O."""

    provider = TTSProvider.DEEPGRAM
    model: SpeechText
    sample_rate: DeepgramTTSRate = DeepgramTTSRate.HZ_24000
    encoding: DeepgramTTSEncoding = DeepgramTTSEncoding.LINEAR16
    container: Literal["none", "raw"] = "none"
    ws_url: SpeechText = DEEPGRAM_TTS_URL

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _integer_rate(cls, value: object) -> object:
        if isinstance(value, DeepgramTTSRate) or type(value) is int:
            return value
        raise ValueError("Deepgram TTS requires an integer sample rate.")

    @field_validator("encoding", mode="before")
    @classmethod
    def native_encoding(cls, value: object) -> object:
        aliases = {
            "pcm_s16le": DeepgramTTSEncoding.LINEAR16,
            "pcm_mulaw": DeepgramTTSEncoding.MULAW,
            "pcm_alaw": DeepgramTTSEncoding.ALAW,
        }
        return aliases.get(value, value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _media_pair(self) -> Self:
        if (
            self.encoding is not DeepgramTTSEncoding.LINEAR16
            and self.sample_rate
            not in (DeepgramTTSRate.HZ_8000, DeepgramTTSRate.HZ_16000)
        ):
            raise ValueError("Deepgram mu-law and A-law require 8 or 16 kHz.")
        return self


class _DeepgramInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class DeepgramSpeak(_DeepgramInput):
    type: Literal["Speak"] = "Speak"
    text: Annotated[StrictStr, Field(min_length=1)] = Field(repr=False)


class DeepgramFlush(_DeepgramInput):
    type: Literal["Flush"] = "Flush"


class DeepgramClear(_DeepgramInput):
    type: Literal["Clear"] = "Clear"


class _DeepgramOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class DeepgramTTSMetadata(_DeepgramOutput):
    type: Literal["Metadata"]
    request_id: UUID
    model_name: SpeechText
    model_version: SpeechText
    model_uuid: UUID


class DeepgramFlushed(_DeepgramOutput):
    type: Literal["Flushed"]
    sequence_id: Annotated[StrictInt, Field(ge=0)]


class DeepgramCleared(_DeepgramOutput):
    type: Literal["Cleared"]
    sequence_id: Annotated[StrictInt, Field(ge=0)]


class DeepgramTTSWarning(_DeepgramOutput):
    type: Literal["Warning"]
    code: SpeechText
    description: StrictStr = Field(repr=False)


class DeepgramTTSOutputError(TTSConnectionFailed):
    """A rejected native control frame; raw vendor contents stay private."""


type DeepgramTTSOutput = Annotated[
    DeepgramTTSMetadata | DeepgramFlushed | DeepgramCleared | DeepgramTTSWarning,
    Field(discriminator="type"),
]
_OUTPUT = TypeAdapter[DeepgramTTSOutput](DeepgramTTSOutput)


def parse_control(raw: str) -> DeepgramTTSOutput:
    try:
        return _OUTPUT.validate_json(raw)
    except ValidationError:
        raise DeepgramTTSOutputError("Invalid Deepgram TTS control message.") from None
