"""Hume TTS native stream-input contracts, never HTTP utterances envelopes.

Checked against Hume's SDK at 84e24b3be3e8e53df94bf23c28d9191aaa1217c0.
Vendor JSON, private audio and errors remain inside the socket boundary.
"""

import base64
import binascii
from enum import Enum, StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.exceptions import TTSConfigurationError, TTSConnectionFailed

HUME_SAMPLE_RATE = 48000
HUME_PCM_ENCODING = "pcm_s16le"
HUME_API_KEY_HEADER = "X-Hume-Api-Key"
HUME_STREAM_URL = "wss://api.hume.ai/v0/tts/stream/input"
_PCM_SAMPLE_BYTES = 2


class HumeVersion(StrEnum):
    OCTAVE_1 = "1"
    OCTAVE_2 = "2"


class HumeStreamState(Enum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    FAILED = "failed"


class HumeOutputKind(StrEnum):
    AUDIO = "audio"
    TIMESTAMP = "timestamp"


class HumeOutputError(TTSConnectionFailed):
    """Malformed native output; never carries vendor text or private audio."""


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class HumeVoice(_WireValue):
    """Existing name-based selection retains Hume's custom-library default."""

    name: SpeechText


class HumeText(_WireValue):
    text: SpeechText = Field(repr=False)
    voice: HumeVoice | None = None
    description: SpeechText | None = Field(default=None, repr=False)
    speed: StrictFloat = Field(gt=0)


class HumeEndInput(_WireValue):
    """Force buffered synthesis, then close only after all generated output."""

    close: Literal[True] = True

    @field_validator("close", mode="before")
    @classmethod
    def require_close(cls, value: object) -> Literal[True]:
        if value is not True:
            raise ValueError("Hume end-input requires true.")
        return True


class HumeAudioOutput(_WireValue):
    model_config = ConfigDict(extra="ignore")

    type: Literal[HumeOutputKind.AUDIO]
    audio: StrictStr = Field(repr=False, exclude=True)
    audio_format: Literal["pcm"]
    chunk_index: StrictInt = Field(ge=0)
    generation_id: SpeechText
    request_id: SpeechText
    snippet_id: SpeechText
    is_last_chunk: StrictBool

    def audio_bytes(self) -> bytes:
        try:
            value = base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error):
            raise HumeOutputError("Invalid Hume audio encoding.") from None
        if len(value) % _PCM_SAMPLE_BYTES:
            raise HumeOutputError("Invalid Hume PCM sample alignment.")
        return value


class HumeTimestampOutput(_WireValue):
    """Timing extensions do not signal synthesis completion."""

    model_config = ConfigDict(extra="ignore")
    type: Literal[HumeOutputKind.TIMESTAMP]


HumeOutput = Annotated[
    HumeAudioOutput | HumeTimestampOutput, Field(discriminator="type")
]
_OUTPUT = TypeAdapter(HumeOutput, config=ConfigDict(hide_input_in_errors=True))


def parse_output(raw: str) -> HumeOutput:
    try:
        return _OUTPUT.validate_json(raw)
    except ValidationError:
        raise HumeOutputError("Invalid Hume output frame.") from None


def version_for_model(model: str) -> HumeVersion:
    """Map existing operator choices to the documented handshake version."""
    versions = {
        "octave-1": HumeVersion.OCTAVE_1,
        "octave-2-preview": HumeVersion.OCTAVE_2,
        "octave-2": HumeVersion.OCTAVE_2,
        HumeVersion.OCTAVE_1.value: HumeVersion.OCTAVE_1,
        HumeVersion.OCTAVE_2.value: HumeVersion.OCTAVE_2,
    }
    try:
        return versions[model]
    except KeyError:
        raise TTSConfigurationError("Unsupported Hume Octave model.") from None
