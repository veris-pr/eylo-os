"""Smallest Lightning-v2 wire values; native JSON stays inside this adapter."""

import base64
import binascii
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.exceptions import TTSConnectionFailed

SMALLEST_SAMPLE_RATE = 24000
SMALLEST_PCM_ENCODING = "pcm_s16le"
SMALLEST_WEBSOCKET_URL = (
    "wss://waves-api.smallest.ai/api/v1/lightning-v2/get_speech/stream?timeout=60"
)


class SmallestModel(StrEnum):
    LIGHTNING_V2 = "lightning-v2"


class SmallestStreamState(StrEnum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    COMPLETE = "complete"
    FAILED = "failed"


class SmallestResponseStatus(StrEnum):
    CHUNK = "chunk"
    COMPLETE = "complete"
    # The v2 WebSocket guide also documents this final spelling with done=true.
    COMP = "comp"
    ERROR = "error"


class SmallestOutputError(TTSConnectionFailed):
    """Invalid or failed output cannot become successful silence."""


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class SmallestSpeechRequest(_WireValue):
    """One non-continuation synthesis request; no implicit model switch."""

    text: SpeechText = Field(repr=False)
    voice_id: SpeechText
    language: SpeechText
    sample_rate: int = Field(strict=True, gt=0)
    add_wav_header: Literal[False] = False


class SmallestAudioData(_WireValue):
    model_config = ConfigDict(extra="ignore")
    audio: StrictStr = Field(repr=False, exclude=True)

    def audio_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error):
            raise SmallestOutputError("Invalid Smallest audio encoding.") from None


class _Response(_WireValue):
    model_config = ConfigDict(extra="ignore")
    request_id: SpeechText


class SmallestChunk(_Response):
    status: Literal[SmallestResponseStatus.CHUNK]
    data: SmallestAudioData


class SmallestComplete(_Response):
    status: Literal[SmallestResponseStatus.COMPLETE]
    data: SmallestAudioData | None = None


class SmallestComp(_Response):
    status: Literal[SmallestResponseStatus.COMP]
    done: Literal[True]
    data: SmallestAudioData | None = None

    @field_validator("done", mode="before")
    @classmethod
    def require_terminal_flag(cls, value: object) -> Literal[True]:
        if value is not True:
            raise ValueError("Smallest final marker requires true.")
        return True


class SmallestError(_WireValue):
    """Do not retain untrusted provider error text or nested request material."""

    model_config = ConfigDict(extra="ignore")
    status: Literal[SmallestResponseStatus.ERROR]
    request_id: SpeechText | None = None


SmallestResponse = Annotated[
    SmallestChunk | SmallestComplete | SmallestComp | SmallestError,
    Field(discriminator="status"),
]
_RESPONSE = TypeAdapter(SmallestResponse)


def parse_response(raw: str) -> SmallestResponse:
    """Consume documented status/data.audio frames, rejecting malformed output."""
    try:
        return _RESPONSE.validate_json(raw)
    except ValidationError:
        raise SmallestOutputError("Invalid Smallest synthesis response.") from None
