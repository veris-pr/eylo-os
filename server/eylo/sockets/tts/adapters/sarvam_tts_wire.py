"""Sarvam-owned synthesis configuration and validated WebSocket messages."""

import base64
import binascii
from enum import Enum, IntEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from eylo.common.contracts.provider_config import Capability, NotConfiguredError
from eylo.sockets.tts.exceptions import TTSConfigurationError, TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider

SARVAM_STREAM_URL = "wss://api.sarvam.ai/text-to-speech/ws"
SARVAM_KEY_HEADER = "api-subscription-key"
SARVAM_PCM_ENCODING = "pcm_s16le"
SARVAM_TEXT_LIMIT = 2500
_Text = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class SarvamModel(str, Enum):
    BULBUL_V2 = "bulbul:v2"
    BULBUL_V3 = "bulbul:v3"


class SarvamLanguage(str, Enum):
    BENGALI = "bn-IN"
    ENGLISH = "en-IN"
    GUJARATI = "gu-IN"
    HINDI = "hi-IN"
    KANNADA = "kn-IN"
    MALAYALAM = "ml-IN"
    MARATHI = "mr-IN"
    ODIA = "od-IN"
    PUNJABI = "pa-IN"
    TAMIL = "ta-IN"
    TELUGU = "te-IN"


class SarvamSampleRate(IntEnum):
    HZ_8000 = 8000
    HZ_16000 = 16000
    HZ_22050 = 22050
    HZ_24000 = 24000


class SarvamTuningField(str, Enum):
    PITCH = "pitch"
    PACE = "pace"
    LOUDNESS = "loudness"
    TEMPERATURE = "temperature"


class SarvamStreamState(str, Enum):
    DISCONNECTED = "disconnected"
    READY = "ready"
    STREAMING = "streaming"
    DRAINING = "draining"
    FAILED = "failed"


class _SarvamValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class SarvamTuning(_SarvamValue):
    pitch: Annotated[StrictFloat, Field(ge=-1, le=1)] | None = None
    pace: Annotated[StrictFloat, Field(ge=0.3, le=3)] | None = None
    loudness: Annotated[StrictFloat, Field(ge=0.1, le=3)] | None = None
    temperature: Annotated[StrictFloat, Field(ge=0.01, le=1)] | None = None


class SarvamTTSConfig(SarvamTuning):
    """Only native inputs; secrets never appear in representation or dumps."""

    model: SarvamModel
    voice: _Text
    language: SarvamLanguage
    sample_rate: SarvamSampleRate
    api_key: _Text = Field(repr=False, exclude=True)

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _sample_rate(cls, value: object) -> object:
        if isinstance(value, SarvamSampleRate) or type(value) is int:
            return value
        raise ValueError("Sarvam sample rate requires an integer rate.")

    @model_validator(mode="after")
    def _model_tuning(self) -> Self:
        if (
            self.model is SarvamModel.BULBUL_V3
            and self.pace is not None
            and not 0.5 <= self.pace <= 2
        ):
            raise ValueError("Bulbul v3 pace must be between 0.5 and 2.")
        return self

    @classmethod
    def from_runtime(cls, config: TTSConfig) -> Self:
        if config.vendor is not TTSProvider.SARVAM:
            raise TTSConfigurationError("Sarvam requires its own provider config.")
        values = config.to_adapter_config()
        missing = tuple(
            name
            for name in ("api_key", "model", "voice", "language")
            if values.get(name) in (None, "")
        )
        if missing:
            raise NotConfiguredError(
                missing=missing,
                capability=Capability.TTS,
                configure_via="/api/tts-configs",
            )
        # The common carrier already resolves the output rate. Never label a
        # vendor-default rate as that resolved value without requesting it.
        legacy_rate = values.pop("speech_sample_rate", None)
        if legacy_rate is not None and (
            type(legacy_rate) is not int or legacy_rate != config.sample_rate
        ):
            raise TTSConfigurationError("Conflicting Sarvam sample rate settings.")
        for field in TTSConfig.model_fields.keys() - cls.model_fields.keys():
            values.pop(field, None)
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise TTSConfigurationError("Invalid Sarvam TTS configuration.") from None

    def unsupported_options(self) -> tuple[str, ...]:
        if self.model is SarvamModel.BULBUL_V3:
            candidates = (
                (SarvamTuningField.PITCH, self.pitch),
                (SarvamTuningField.LOUDNESS, self.loudness),
            )
        else:
            candidates = ((SarvamTuningField.TEMPERATURE, self.temperature),)
        return tuple(field.value for field, value in candidates if value is not None)

    def tuning(self) -> SarvamTuning:
        v3 = self.model is SarvamModel.BULBUL_V3
        return SarvamTuning(
            pitch=None if v3 else self.pitch,
            pace=self.pace,
            loudness=None if v3 else self.loudness,
            temperature=self.temperature if v3 else None,
        )

    def initial_message(self) -> "SarvamConfigure":
        tuning = self.tuning()
        return SarvamConfigure(
            data=SarvamConfiguration(
                language_code=self.language,
                speaker=self.voice,
                speech_sample_rate=self.sample_rate,
                pitch=tuning.pitch,
                pace=tuning.pace,
                loudness=tuning.loudness,
                temperature=tuning.temperature,
            )
        )


class SarvamConfiguration(SarvamTuning):
    language_code: SarvamLanguage
    speaker: _Text
    speech_sample_rate: SarvamSampleRate
    output_audio_codec: Literal["linear16"] = "linear16"

    @field_serializer("speech_sample_rate")
    def _wire_sample_rate(self, value: SarvamSampleRate) -> str:
        return str(value.value)


class SarvamConfigure(_SarvamValue):
    type: Literal["config"] = "config"
    data: SarvamConfiguration


class SarvamTextData(_SarvamValue):
    text: Annotated[StrictStr, Field(min_length=1, max_length=SARVAM_TEXT_LIMIT)] = (
        Field(repr=False)
    )


class SarvamText(_SarvamValue):
    type: Literal["text"] = "text"
    data: SarvamTextData


class SarvamFlush(_SarvamValue):
    type: Literal["flush"] = "flush"


class SarvamPing(_SarvamValue):
    type: Literal["ping"] = "ping"


class _SarvamOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class SarvamAudioData(_SarvamOutput):
    content_type: _Text
    audio: _Text = Field(repr=False)

    def audio_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.audio, validate=True)
        except (ValueError, binascii.Error):
            raise SarvamOutputError("Sarvam returned invalid audio data.") from None


class SarvamAudio(_SarvamOutput):
    type: Literal["audio"]
    data: SarvamAudioData


class SarvamFinalData(_SarvamOutput):
    event_type: Literal["final"]


class SarvamFinal(_SarvamOutput):
    type: Literal["event"]
    data: SarvamFinalData


class SarvamErrorData(_SarvamOutput):
    message: StrictStr = Field(repr=False)


class SarvamError(_SarvamOutput):
    type: Literal["error"]
    data: SarvamErrorData


class SarvamOutputError(TTSConnectionFailed):
    """A malformed or failed native response, without vendor payload disclosure."""


_Output = TypeAdapter(
    Annotated[SarvamAudio | SarvamFinal | SarvamError, Field(discriminator="type")]
)


def parse_output(raw: str | bytes) -> SarvamAudio | SarvamFinal:
    try:
        message = _Output.validate_json(raw)
    except ValidationError:
        raise SarvamOutputError("Invalid Sarvam TTS response.") from None
    if isinstance(message, SarvamError):
        raise SarvamOutputError("Sarvam TTS synthesis failed.")
    return message
