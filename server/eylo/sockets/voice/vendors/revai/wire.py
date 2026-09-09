"""Rev AI Streaming v1 query parameters, native hypotheses, and close codes."""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self
from urllib.parse import urlencode

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    TypeAdapter,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.exceptions import STTConfigurationError
from eylo.sockets.stt.schemas import STTEncoding

REV_AI_WS_BASE = "wss://api.rev.ai/speechtotext/v1/stream"
_DEFAULT_SAMPLE_RATE_HZ = 16000
_MIN_SAMPLE_RATE_HZ = 8000
_MAX_SAMPLE_RATE_HZ = 48000
_Text = Annotated[str, Field(strict=True, min_length=1)]
_Seconds = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Confidence = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class RevAIMessageType(StrEnum):
    CONNECTED = "connected"
    PARTIAL = "partial"
    FINAL = "final"


class RevAIElementType(StrEnum):
    TEXT = "text"
    PUNCTUATION = "punct"


class RevAIControl(StrEnum):
    END_OF_STREAM = "EOS"


class RevAICloseCode(IntEnum):
    UNAUTHORIZED = 4001
    BAD_REQUEST = 4002
    INSUFFICIENT_CREDITS = 4003
    SERVER_SHUTTING_DOWN = 4010
    NO_INSTANCE_AVAILABLE = 4013
    TOO_MANY_REQUESTS = 4029


class RevAIConfig(BaseModel):
    """Validate consumed settings; never invent a model or leak a query credential."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )
    api_key: SecretStr = Field(min_length=1, exclude=True, repr=False)
    language: _Text
    model: _Text | None = None
    sample_rate: int = Field(
        default=_DEFAULT_SAMPLE_RATE_HZ,
        strict=True,
        ge=_MIN_SAMPLE_RATE_HZ,
        le=_MAX_SAMPLE_RATE_HZ,
    )
    encoding: STTEncoding = STTEncoding.LINEAR16
    interim_results: SpeechOption = SpeechOptionState.ENABLED

    @model_validator(mode="after")
    def pcm_input(self) -> Self:
        if self.encoding not in {STTEncoding.LINEAR16, STTEncoding.PCM_S16LE}:
            raise STTConfigurationError("Rev AI STT requires mono PCM16 input.")
        return self

    def websocket_url(self) -> str:
        """Serialize secrets only into the vendor-required server-side query."""
        query = RevAIQuery(
            content_type=(
                "audio/x-raw;layout=interleaved;"
                f"rate={self.sample_rate};format=S16LE;channels=1"
            ),
            language=self.language,
            transcriber=self.model,
        ).model_dump(exclude_none=True)
        query["access_token"] = self.api_key.get_secret_value()
        return f"{REV_AI_WS_BASE}?{urlencode(query)}"


class RevAIQuery(BaseModel):
    """Native query names stay local; credentials are added only during encoding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    content_type: str
    language: str
    transcriber: str | None


class _NativeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)


class RevAIConnected(_NativeModel):
    type: Literal[RevAIMessageType.CONNECTED]
    id: _Text


class RevAITextElement(_NativeModel):
    """Partial words may omit type, timing, and confidence; zero is a real score."""

    type: Literal[RevAIElementType.TEXT] = RevAIElementType.TEXT
    value: str = Field(strict=True)
    ts: _Seconds | None = None
    end_ts: _Seconds | None = None
    confidence: _Confidence | None = None

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.ts is not None and self.end_ts is not None and self.end_ts < self.ts:
            raise ValueError("Rev AI word end precedes its start.")
        return self


class RevAIPunctuation(_NativeModel):
    type: Literal[RevAIElementType.PUNCTUATION]
    value: str = Field(strict=True)


RevAIFinalElement = Annotated[
    RevAITextElement | RevAIPunctuation, Field(discriminator="type")
]


class _Hypothesis(_NativeModel):
    ts: _Seconds
    end_ts: _Seconds

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end_ts < self.ts:
            raise ValueError("Rev AI hypothesis end precedes its start.")
        return self


class RevAIPartial(_Hypothesis):
    type: Literal[RevAIMessageType.PARTIAL]
    elements: tuple[RevAITextElement, ...]


class RevAIFinal(_Hypothesis):
    type: Literal[RevAIMessageType.FINAL]
    elements: tuple[RevAIFinalElement, ...]
    speaker_id: int | None = Field(default=None, strict=True, ge=0)


RevAIEvent = Annotated[
    RevAIConnected | RevAIPartial | RevAIFinal, Field(discriminator="type")
]
_EVENT = TypeAdapter(RevAIEvent)


def parse_revai_event(message: str | bytes) -> RevAIEvent:
    """Reject malformed/unknown message kinds instead of misclassifying them as speech."""
    return _EVENT.validate_json(message)
