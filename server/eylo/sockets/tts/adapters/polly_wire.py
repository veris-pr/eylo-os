"""Polly-owned configuration and synthesis requests; no SDK values escape."""

from enum import Enum, IntEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
)

from eylo.sockets.tts.exceptions import TTSConfigurationError
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider

POLLY_SERVICE = "polly"
POLLY_PCM_ENCODING = "pcm_s16le"
POLLY_PCM_SAMPLE_RATES = (8000, 16000)
_Text = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class PollyEngine(str, Enum):
    STANDARD = "standard"
    NEURAL = "neural"
    LONG_FORM = "long-form"
    GENERATIVE = "generative"


class PollySampleRate(IntEnum):
    PCM_8_KHZ = 8000
    PCM_16_KHZ = 16000


class _PollyValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class PollyConfig(_PollyValue):
    """Explicit native choices and private credentials, validated before I/O."""

    model: PollyEngine
    voice: _Text
    language: _Text
    region: _Text
    sample_rate: PollySampleRate
    access_key_id: _Text = Field(repr=False, exclude=True)
    secret_access_key: _Text = Field(repr=False, exclude=True)
    session_token: _Text | None = Field(default=None, repr=False, exclude=True)

    @field_validator("model", mode="before")
    @classmethod
    def _engine(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _sample_rate(cls, value: object) -> object:
        if isinstance(value, PollySampleRate) or type(value) is int:
            return value
        raise ValueError("Polly PCM sample rate requires an integer rate.")

    @field_validator(
        "voice",
        "language",
        "region",
        "access_key_id",
        "secret_access_key",
        "session_token",
    )
    @classmethod
    def _trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @classmethod
    def from_runtime(cls, config: TTSConfig) -> Self:
        if config.vendor is not TTSProvider.AMAZON_POLLY:
            raise TTSConfigurationError("Polly requires its own provider config.")
        values = config.to_adapter_config()
        for field in TTSConfig.model_fields.keys() - cls.model_fields.keys():
            values.pop(field, None)
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise TTSConfigurationError("Invalid Amazon Polly configuration.") from None

    def request(self, text: str) -> "PollySynthesisRequest":
        return PollySynthesisRequest(
            Engine=self.model,
            LanguageCode=self.language,
            SampleRate=str(self.sample_rate.value),
            Text=text,
            VoiceId=self.voice,
        )


class PollySynthesisRequest(_PollyValue):
    """The current adapter requests plain text and mono, signed PCM only."""

    Engine: PollyEngine
    LanguageCode: _Text
    OutputFormat: Literal["pcm"] = "pcm"
    SampleRate: Literal["8000", "16000"]
    Text: StrictStr = Field(repr=False)
    TextType: Literal["text"] = "text"
    VoiceId: _Text
