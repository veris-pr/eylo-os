"""Rime JSON WebSocket requests and validated native output events."""

import base64
import binascii
from enum import StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlencode

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSProvider

WEBSOCKET_URL = "wss://users-ws.rime.ai/ws3"
DEFAULT_SAMPLE_RATE = 16000
MIN_MIST_SAMPLE_RATE = 4000
MAX_MIST_SAMPLE_RATE = 44100
MAX_TEXT_CHARACTERS = 1000
MAX_EVENT_BYTES = 1024 * 1024
PCM_SAMPLE_BYTES = 2


class RimeMistModel(StrEnum):
    MIST = "mist"
    MIST_V1 = "mistv1"
    MIST_V2 = "mistv2"


class RimeAudioFormat(StrEnum):
    PCM = "pcm"
    MULAW = "mulaw"


class RimeOperation(StrEnum):
    EOS = "eos"


class RimeEventKind(StrEnum):
    CHUNK = "chunk"
    TIMESTAMPS = "timestamps"
    DONE = "done"
    ERROR = "error"


class RimeStreamState(StrEnum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    COMPLETE = "complete"
    FAILED = "failed"


class RimeTTSConfig(TTSAdapterConfig):
    """Private native input; only raw formats supported by Eylo are accepted."""

    provider = TTSProvider.RIME
    voice: SpeechText
    model: SpeechText
    sample_rate: StrictInt = Field(default=DEFAULT_SAMPLE_RATE, gt=0)
    audio_format: RimeAudioFormat = RimeAudioFormat.MULAW

    @model_validator(mode="after")
    def validate_mist_rate(self) -> Self:
        if self.model in RimeMistModel and not (
            MIN_MIST_SAMPLE_RATE <= self.sample_rate <= MAX_MIST_SAMPLE_RATE
        ):
            raise ValueError("Rime Mist sample rate must be between 4000 and 44100 Hz.")
        return self

    def query(self) -> "RimeSynthesisQuery":
        return RimeSynthesisQuery(
            speaker=self.voice,
            modelId=self.model,
            audioFormat=self.audio_format,
            samplingRate=self.sample_rate,
        )


class RimeRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class RimeSynthesisQuery(RimeRequest):
    speaker: SpeechText
    modelId: SpeechText
    audioFormat: RimeAudioFormat
    samplingRate: StrictInt = Field(gt=0)

    def url(self) -> str:
        return f"{WEBSOCKET_URL}?{urlencode(self.model_dump(mode='json'))}"


class RimeText(RimeRequest):
    text: Annotated[StrictStr, Field(min_length=1, max_length=MAX_TEXT_CHARACTERS)]


class RimeEndInput(RimeRequest):
    operation: Literal[RimeOperation.EOS] = RimeOperation.EOS


class RimeOutputError(TTSConnectionFailed):
    """Malformed native output or a provider rejection, without raw payloads."""


class RimeEvent(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )


class RimeChunk(RimeEvent):
    type: Literal[RimeEventKind.CHUNK]
    data: StrictStr = Field(max_length=MAX_EVENT_BYTES)
    contextId: StrictStr | None

    def audio_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error):
            raise RimeOutputError("Rime returned invalid audio encoding.") from None


RimeTime = Annotated[StrictInt | StrictFloat, Field(ge=0)]


class RimeWordTimestamps(RimeEvent):
    words: tuple[StrictStr, ...]
    start: tuple[RimeTime, ...]
    end: tuple[RimeTime, ...]

    @model_validator(mode="after")
    def validate_intervals(self) -> Self:
        if len(self.words) != len(self.start) or len(self.start) != len(self.end):
            raise ValueError("Rime word timestamps must have matching lengths.")
        if any(start > end for start, end in zip(self.start, self.end, strict=True)):
            raise ValueError("Rime word timestamp ends before its start.")
        return self


class RimeTimestamps(RimeEvent):
    type: Literal[RimeEventKind.TIMESTAMPS]
    word_timestamps: RimeWordTimestamps
    contextId: StrictStr | None


class RimeDone(RimeEvent):
    type: Literal[RimeEventKind.DONE]
    contextId: StrictStr | None


class RimeError(RimeEvent):
    type: Literal[RimeEventKind.ERROR]
    message: StrictStr = Field(repr=False, exclude=True)


RimeOutput = Annotated[
    RimeChunk | RimeTimestamps | RimeDone | RimeError, Field(discriminator="type")
]
_OUTPUT = TypeAdapter(RimeOutput)


def parse_output(raw: str | bytes) -> RimeChunk | RimeTimestamps | RimeDone | RimeError:
    """Validate a bounded native event before the adapter changes turn state."""
    if len(raw) > MAX_EVENT_BYTES:
        raise RimeOutputError("Rime output exceeded the local event limit.")
    try:
        return _OUTPUT.validate_json(raw)
    except ValidationError:
        raise RimeOutputError("Rime returned an invalid event.") from None
