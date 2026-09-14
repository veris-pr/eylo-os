"""Cartesia TTS wire contracts; vendor JSON never escapes the socket adapter.

The adapter retains its configured API version and ID-based voice specifier.
Unknown response extensions are ignored; consumed fields and context identity
are validated. Unused timestamp arrays and vendor error text are not retained.
"""

import base64
import binascii
from enum import Enum
from typing import Annotated, Literal, Self

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
    model_validator,
)

from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider

_Text = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]
# Native generation_config.speed bounds, not platform-wide voice policy.
_MIN_SPEED = 0.6
_MAX_SPEED = 1.5


class CartesiaStreamState(Enum):
    """One logical session with at most one active synthesis context."""

    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    FAILED = "failed"


class CartesiaContinuation(Enum):
    """Native input continuation, serialized as the vendor's boolean field."""

    CONTINUE = True
    FINALIZE = False


class CartesiaResponseKind(str, Enum):
    CHUNK = "chunk"
    DONE = "done"
    FLUSH_DONE = "flush_done"
    TIMESTAMPS = "timestamps"
    PHONEME_TIMESTAMPS = "phoneme_timestamps"
    ERROR = "error"


class CartesiaInputError(ValueError):
    """Invalid native config/input; never includes credentials or speech text."""


class CartesiaOutputError(TTSConnectionFailed):
    """Malformed or failed synthesis must not become successful silence."""


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class CartesiaAudioFormat(_WireValue):
    """Only raw encodings the current voice transport can consume."""

    container: Literal["raw"] = "raw"
    encoding: Literal["pcm_s16le", "pcm_mulaw", "pcm_alaw"]
    sample_rate: StrictInt = Field(gt=0)


class CartesiaGenerationConfig(_WireValue):
    """Explicit settings only; model-dependent support remains vendor-owned."""

    speed: StrictFloat = Field(ge=_MIN_SPEED, le=_MAX_SPEED)


class CartesiaOptions(_WireValue):
    """Validate the generic factory option boundary before opening a socket."""

    api_key: _Text = Field(repr=False, exclude=True)
    container: Literal["raw"] = "raw"
    speed: StrictFloat | None = Field(default=None, ge=_MIN_SPEED, le=_MAX_SPEED)


class CartesiaInput(_WireValue):
    """Freeze operator-selected identity, private credentials and media format."""

    model: _Text
    voice: _Text
    language: _Text | None = None
    output_format: CartesiaAudioFormat
    options: CartesiaOptions = Field(repr=False, exclude=True)

    @classmethod
    def from_config(cls, config: TTSConfig) -> Self:
        if config.vendor != TTSProvider.CARTESIA:
            raise CartesiaInputError("Cartesia requires its own provider config.")
        try:
            options = CartesiaOptions.model_validate(config.options)
            return cls.model_validate(
                {
                    "model": config.model,
                    "voice": config.voice,
                    "language": config.language,
                    "options": options,
                    "output_format": {
                        "container": options.container,
                        "encoding": config.encoding,
                        "sample_rate": config.sample_rate,
                    },
                }
            )
        except ValidationError:
            raise CartesiaInputError("Invalid Cartesia TTS configuration.") from None


class CartesiaVoice(_WireValue):
    mode: Literal["id"] = "id"
    id: _Text


class CartesiaGenerationRequest(_WireValue):
    """Continuation and end-of-input retain identical generation settings."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    model_id: _Text
    transcript: StrictStr = Field(repr=False)
    voice: CartesiaVoice
    output_format: CartesiaAudioFormat
    context_id: _Text
    continue_: CartesiaContinuation = Field(alias="continue")
    language: _Text | None = None
    generation_config: CartesiaGenerationConfig | None = None

    @field_validator("continue_", mode="before")
    @classmethod
    def _parse_continuation(cls, value: object) -> CartesiaContinuation:
        if isinstance(value, CartesiaContinuation):
            return value
        if isinstance(value, bool):
            return CartesiaContinuation(value)
        raise ValueError("Cartesia continuation requires a boolean or its enum.")

    @model_validator(mode="after")
    def _require_input(self) -> Self:
        if self.continue_ is CartesiaContinuation.CONTINUE and not self.transcript:
            raise ValueError("Cartesia continuation requires speech text.")
        return self


class CartesiaCancelRequest(_WireValue):
    """Cancel queued generation; already generated audio still needs filtering."""

    context_id: _Text
    cancel: Literal[True] = True

    @field_validator("cancel", mode="before")
    @classmethod
    def _require_cancel(cls, value: object) -> Literal[True]:
        if value is not True:
            raise ValueError("Cartesia cancellation requires true.")
        return True


class CartesiaResponseEnvelope(_WireValue):
    """Read identity before accepting data or completion for the active context."""

    model_config = ConfigDict(extra="ignore")

    type: CartesiaResponseKind
    context_id: _Text | None = None

    @model_validator(mode="after")
    def _require_context(self) -> Self:
        if self.context_id is None and self.type is not CartesiaResponseKind.ERROR:
            raise ValueError("Cartesia synthesis output requires a context.")
        return self


class _Output(CartesiaResponseEnvelope):
    done: StrictBool

    @model_validator(mode="after")
    def _require_consistent_completion(self) -> Self:
        terminal = self.type in (CartesiaResponseKind.DONE, CartesiaResponseKind.ERROR)
        if self.done is not terminal:
            raise ValueError("Cartesia output has conflicting completion fields.")
        return self


class CartesiaAudioOutput(_Output):
    type: Literal[CartesiaResponseKind.CHUNK]
    data: StrictStr = Field(repr=False, exclude=True)

    def audio_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error):
            raise CartesiaOutputError("Invalid Cartesia audio encoding.") from None


class CartesiaDoneOutput(_Output):
    type: Literal[CartesiaResponseKind.DONE]


class CartesiaFlushOutput(_Output):
    type: Literal[CartesiaResponseKind.FLUSH_DONE]
    flush_done: StrictBool
    flush_id: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _require_flush(self) -> Self:
        if not self.flush_done:
            raise ValueError("Cartesia flush acknowledgement must be complete.")
        return self


class CartesiaTimingOutput(_Output):
    type: Literal[
        CartesiaResponseKind.TIMESTAMPS, CartesiaResponseKind.PHONEME_TIMESTAMPS
    ]


class CartesiaErrorOutput(_Output):
    """Failure identity only; both legacy and current vendor detail stay private."""

    type: Literal[CartesiaResponseKind.ERROR]


CartesiaOutput = Annotated[
    CartesiaAudioOutput
    | CartesiaDoneOutput
    | CartesiaFlushOutput
    | CartesiaTimingOutput
    | CartesiaErrorOutput,
    Field(discriminator="type"),
]
_OUTPUT = TypeAdapter(CartesiaOutput, config=ConfigDict(hide_input_in_errors=True))


def parse_envelope(raw: str | bytes) -> CartesiaResponseEnvelope:
    """Invalid identity is a protocol error, never implicitly the current turn."""
    try:
        return CartesiaResponseEnvelope.model_validate_json(raw)
    except ValidationError:
        raise CartesiaOutputError("Invalid Cartesia output envelope.") from None


def parse_output(raw: str | bytes) -> CartesiaOutput:
    """Validate known payloads only after the adapter checks their identity."""
    try:
        return _OUTPUT.validate_json(raw)
    except ValidationError:
        raise CartesiaOutputError("Invalid Cartesia output frame.") from None
