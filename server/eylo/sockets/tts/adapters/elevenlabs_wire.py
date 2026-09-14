"""ElevenLabs single-context WebSocket inputs and consumed output fields.

There is no ElevenLabs SDK in this runtime. These models describe the native
JSON boundary; they do not expose vendor schemas to platform modules. Alignment
and future output extensions are not consumed on this audio-only path.
"""

import base64
import binascii
import json
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictStr,
    ValidationError,
    model_validator,
)

from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider

_Text = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class ElevenLabsStreamState(Enum):
    """Adapter session state; each finalized turn owns a separate native stream."""

    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    FAILED = "failed"


class ElevenLabsInputError(ValueError):
    """Invalid native inputs; diagnostics never include credential values."""


class ElevenLabsOutputError(TTSConnectionFailed):
    """Invalid or failed native output must not become successful silence."""


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class ElevenLabsVoiceSettings(_WireValue):
    """Only explicit voice settings; omitted/null values remain vendor-owned."""

    stability: StrictFloat | None = Field(default=None, ge=0, le=1)
    similarity_boost: StrictFloat | None = Field(default=None, ge=0, le=1)
    style: StrictFloat | None = Field(default=None, ge=0, le=1)
    use_speaker_boost: StrictBool | None = None
    speed: StrictFloat | None = Field(default=None, gt=0)


class ElevenLabsOptions(ElevenLabsVoiceSettings):
    """Validate the generic factory's option boundary once, before connecting."""

    api_key: _Text = Field(repr=False, exclude=True)

    def voice_settings(self) -> ElevenLabsVoiceSettings:
        return ElevenLabsVoiceSettings(
            stability=self.stability,
            similarity_boost=self.similarity_boost,
            style=self.style,
            use_speaker_boost=self.use_speaker_boost,
            speed=self.speed,
        )


class ElevenLabsInput(_WireValue):
    """Snapshot model, voice and private options; never infer vendor defaults."""

    model: _Text
    voice: _Text
    language: _Text | None = None
    options: ElevenLabsOptions = Field(repr=False, exclude=True)

    @classmethod
    def from_config(cls, config: TTSConfig) -> Self:
        if config.vendor != TTSProvider.ELEVENLABS:
            raise ElevenLabsInputError("ElevenLabs requires its own provider config.")
        try:
            return cls.model_validate(
                {
                    "model": config.model,
                    "voice": config.voice,
                    "language": config.language,
                    "options": config.options,
                }
            )
        except ValidationError:
            raise ElevenLabsInputError(
                "Invalid ElevenLabs TTS configuration."
            ) from None


class ElevenLabsInitialize(_WireValue):
    """Initialization exposes the key only through the explicit wire serializer."""

    text: Literal[" "] = " "
    voice_settings: ElevenLabsVoiceSettings | None = None
    xi_api_key: _Text = Field(repr=False, exclude=True)

    def to_wire_json(self) -> str:
        value = self.model_dump(mode="json", exclude_none=True)
        value["xi_api_key"] = self.xi_api_key
        return json.dumps(value, allow_nan=False)


class ElevenLabsText(_WireValue):
    """Synthesis or keepalive input, distinct from the end-of-input command."""

    text: StrictStr = Field(min_length=1)


class ElevenLabsEndInput(_WireValue):
    """Finish buffered synthesis, then receive final output before closing."""

    text: Literal[""] = ""


class ElevenLabsOutput(_WireValue):
    """Audio and terminal facts; unused alignment/extension fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    audio: StrictStr | None = Field(default=None, repr=False)
    is_final: StrictBool | None = Field(default=None, alias="isFinal")
    message: StrictStr | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="after")
    def _require_output(self) -> Self:
        if self.audio is None and self.is_final is not True and self.message is None:
            raise ValueError("Expected ElevenLabs audio, final output or failure.")
        return self

    def audio_bytes(self) -> bytes | None:
        if self.message is not None:
            raise ElevenLabsOutputError("ElevenLabs rejected speech synthesis.")
        if not self.audio:
            return None
        try:
            return base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error):
            raise ElevenLabsOutputError("Invalid ElevenLabs audio encoding.") from None


def parse_output(raw: str | bytes) -> ElevenLabsOutput:
    """Validate consumed fields without including raw frames in public errors."""
    try:
        return ElevenLabsOutput.model_validate_json(raw)
    except ValidationError:
        raise ElevenLabsOutputError("Invalid ElevenLabs output frame.") from None
