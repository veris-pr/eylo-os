"""Murf-owned WebSocket messages; native casing stays inside this adapter.

The request voiceId spelling follows Murf's WebSocket quickstart. Its generated
AsyncAPI uses voice_id instead; keep the established wire spelling until native
verification establishes a migration. These models do not select a newer model.
"""

import base64
import binascii
from enum import StrEnum
from typing import Literal, Self
from urllib.parse import urlencode

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.exceptions import TTSConnectionFailed

MAX_EVENT_BYTES = 1024 * 1024
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_MIN_BUFFER_SIZE = 60
DEFAULT_MAX_BUFFER_DELAY_MS = 500
MIN_BUFFER_SIZE = 40
MAX_BUFFER_SIZE = 160
MAX_BUFFER_DELAY_MS = 1000
MIN_VARIATION = 0
MAX_VARIATION = 5
API_KEY_QUERY_PARAMETER = "api-key"


class MurfAudioFormat(StrEnum):
    """Native formats accepted by Eylo's raw PCM voice path."""

    PCM = "PCM"
    WAV = "WAV"


class MurfStreamState(StrEnum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    COMPLETE = "complete"
    FAILED = "failed"


class MurfRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class MurfHandshake(MurfRequest):
    """Keep the existing endpoint/auth spelling; escape every query value."""

    api_key: SpeechText = Field(repr=False, exclude=True)
    sample_rate: StrictInt = Field(gt=0)
    channel_type: SpeechText
    format: MurfAudioFormat

    def url(self, endpoint: str) -> str:
        query = self.model_dump(mode="json")
        query[API_KEY_QUERY_PARAMETER] = self.api_key
        return f"{endpoint}?{urlencode(query)}"


class MurfVoiceSettings(MurfRequest):
    voiceId: SpeechText
    rate: StrictInt
    pitch: StrictInt
    variation: StrictInt = Field(ge=MIN_VARIATION, le=MAX_VARIATION)
    style: SpeechText | None = None


class MurfInitialize(MurfRequest):
    voice_config: MurfVoiceSettings


class MurfAdvancedSettings(MurfRequest):
    """Native buffering is a WebSocket command, not handshake query parameters."""

    min_buffer_size: StrictInt = Field(ge=MIN_BUFFER_SIZE, le=MAX_BUFFER_SIZE)
    max_buffer_delay_in_ms: StrictInt = Field(ge=0, le=MAX_BUFFER_DELAY_MS)


class MurfText(MurfRequest):
    context_id: SpeechText
    text: StrictStr = Field(repr=False)
    end: StrictBool


class MurfClear(MurfRequest):
    context_id: SpeechText
    clear: Literal[True] = True


class MurfOutputError(TTSConnectionFailed):
    """Native payload validation failed; never include provider content."""


class MurfOutput(BaseModel):
    """Validate the native audio/final alternatives before consuming audio.

    Error payloads are opaque diagnostics, not a domain contract. They are detected
    but never interpreted, logged, or included in a snapshot. Unknown additive
    fields are ignored; an unknown message shape is not a valid audio event.
    """

    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )

    audio: StrictStr | None = Field(default=None, repr=False, exclude=True)
    final: StrictBool | None = None
    context_id: StrictStr | None = None
    error: JsonValue = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if (
            sum(
                (self.audio is not None, self.final is not None, self.error is not None)
            )
            != 1
        ):
            raise ValueError(
                "Murf output must contain one audio, final or error payload."
            )
        return self

    def audio_bytes(self) -> bytes | None:
        if self.audio is None:
            return None
        try:
            return base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error):
            raise MurfOutputError("Murf returned invalid audio encoding.") from None


def parse_output(raw: str) -> MurfOutput:
    """Bound and validate a native JSON message without exposing raw failures."""
    if len(raw.encode("utf-8")) > MAX_EVENT_BYTES:
        raise MurfOutputError("Murf output exceeded the local event limit.")
    try:
        return MurfOutput.model_validate_json(raw)
    except ValidationError:
        raise MurfOutputError("Murf returned an invalid WebSocket message.") from None
