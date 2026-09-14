"""Cartesia STT wire contracts; native names stay inside the vendor boundary."""

from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlencode

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    model_validator,
)

API_VERSION = "2026-03-01"


class CartesiaSTTEncoding(StrEnum):
    """Only PCM16 is supported by Eylo's current native audio chunker."""

    PCM_S16LE = "pcm_s16le"


class CartesiaSTTCommand(StrEnum):
    """Finalize one segment without closing the connection; close ends input."""

    FINALIZE = "finalize"
    CLOSE = "close"


class CartesiaSTTQuery(BaseModel):
    """Consumed connection settings; no credentials appear in the URL."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    model: str = Field(min_length=1)
    encoding: CartesiaSTTEncoding = CartesiaSTTEncoding.PCM_S16LE
    sample_rate: int = Field(default=16000, strict=True, gt=0)
    language: str | None = None

    def query_string(self) -> str:
        values = self.model_dump(mode="json", exclude_none=True)
        values["cartesia_version"] = API_VERSION
        return urlencode(values)


class CartesiaSTTEventKind(StrEnum):
    """Responses consumed by the STT adapter, not Cartesia TTS responses."""

    TRANSCRIPT = "transcript"
    FLUSH_DONE = "flush_done"
    DONE = "done"
    ERROR = "error"


class CartesiaSTTResponse(BaseModel):
    """Validate consumed fields without retaining unknown vendor extensions."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )


class CartesiaSTTWord(CartesiaSTTResponse):
    """Native word timing is seconds; the vendor does not supply confidence."""

    word: str = Field(repr=False)
    start: float = Field(strict=True, ge=0)
    end: float = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def require_ordered_time(self) -> "CartesiaSTTWord":
        if self.end < self.start:
            raise ValueError("Word end precedes its start.")
        return self


class CartesiaSTTTranscript(CartesiaSTTResponse):
    """Final text is a delta; preserve whitespace and every final chunk."""

    type: Literal[CartesiaSTTEventKind.TRANSCRIPT]
    request_id: str = Field(min_length=1)
    text: str = Field(repr=False)
    is_final: StrictBool
    duration: float | None = Field(default=None, strict=True, ge=0)
    language: str | None = None
    words: tuple[CartesiaSTTWord, ...] = Field(default=(), repr=False)


class CartesiaSTTFlushDone(CartesiaSTTResponse):
    """Finalize acknowledgement, not evidence that a user started/stopped speaking."""

    type: Literal[CartesiaSTTEventKind.FLUSH_DONE]
    request_id: str = Field(min_length=1)


class CartesiaSTTDone(CartesiaSTTResponse):
    """Connection-level end acknowledgement."""

    type: Literal[CartesiaSTTEventKind.DONE]
    request_id: str = Field(min_length=1)


class CartesiaSTTError(CartesiaSTTResponse):
    """Vendor failure details remain private and do not become transcript text."""

    type: Literal[CartesiaSTTEventKind.ERROR]
    status_code: int = Field(strict=True)
    title: str = Field(repr=False)
    message: str = Field(repr=False)
    error_code: str | None = None
    doc_url: str | None = None
    request_id: str | None = None


CartesiaSTTEvent = Annotated[
    CartesiaSTTTranscript | CartesiaSTTFlushDone | CartesiaSTTDone | CartesiaSTTError,
    Field(discriminator="type"),
]
_EVENT_ADAPTER = TypeAdapter(
    CartesiaSTTEvent, config=ConfigDict(hide_input_in_errors=True)
)


class _Envelope(CartesiaSTTResponse):
    type: str


def parse_cartesia_stt_event(frame: str) -> CartesiaSTTEvent | None:
    """Unknown kinds are ignored; malformed consumed kinds fail at ingress."""
    envelope = _Envelope.model_validate_json(frame)
    if envelope.type not in CartesiaSTTEventKind:
        return None
    return _EVENT_ADAPTER.validate_json(frame)
