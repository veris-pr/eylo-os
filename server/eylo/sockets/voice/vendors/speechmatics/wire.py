"""Speechmatics v2 requests and responses; native JSON is validated before use.

Contract: https://docs.speechmatics.com/api-ref/realtime-transcription-websocket
Only consumed options/messages are modeled; unknown message kinds are ignored.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    model_validator,
)


class SpeechmaticsMessage(StrEnum):
    """Native discriminators used by this mono PCM transcription client."""

    START_RECOGNITION = "StartRecognition"
    RECOGNITION_STARTED = "RecognitionStarted"
    AUDIO_ADDED = "AudioAdded"
    PARTIAL = "AddPartialTranscript"
    FINAL = "AddTranscript"
    FORCE_END_OF_UTTERANCE = "ForceEndOfUtterance"
    END_OF_UTTERANCE = "EndOfUtterance"
    END_OF_STREAM = "EndOfStream"
    END_OF_TRANSCRIPT = "EndOfTranscript"
    ERROR = "Error"


class SpeechmaticsEncoding(StrEnum):
    """This client sends mono signed 16-bit PCM, not every vendor-supported codec."""

    PCM_S16LE = "pcm_s16le"


class SpeechmaticsDiarization(StrEnum):
    """Supported mono-stream diarization choices."""

    NONE = "none"
    SPEAKER = "speaker"


class SpeechmaticsRequest(BaseModel):
    """Closed outgoing contract; native boolean flags remain native predicates."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class SpeechmaticsAudioFormat(SpeechmaticsRequest):
    type: Literal["raw"] = "raw"
    encoding: SpeechmaticsEncoding = SpeechmaticsEncoding.PCM_S16LE
    sample_rate: int = Field(strict=True, gt=0)


class SpeechmaticsVocabulary(SpeechmaticsRequest):
    content: str = Field(min_length=1, repr=False)


class SpeechmaticsTranscriptionConfig(SpeechmaticsRequest):
    language: str = Field(min_length=1)
    enable_partials: StrictBool = True
    enable_entities: StrictBool = False
    max_delay: float = Field(default=2.0, strict=True, ge=0.7, le=4.0)
    diarization: SpeechmaticsDiarization | None = None
    additional_vocab: tuple[SpeechmaticsVocabulary, ...] = ()


class SpeechmaticsStartRecognition(SpeechmaticsRequest):
    message: Literal[SpeechmaticsMessage.START_RECOGNITION] = (
        SpeechmaticsMessage.START_RECOGNITION
    )
    audio_format: SpeechmaticsAudioFormat
    transcription_config: SpeechmaticsTranscriptionConfig


class SpeechmaticsEndOfStream(SpeechmaticsRequest):
    message: Literal[SpeechmaticsMessage.END_OF_STREAM] = (
        SpeechmaticsMessage.END_OF_STREAM
    )
    last_seq_no: int = Field(strict=True, ge=0)


class SpeechmaticsForceEndOfUtterance(SpeechmaticsRequest):
    message: Literal[SpeechmaticsMessage.FORCE_END_OF_UTTERANCE] = (
        SpeechmaticsMessage.FORCE_END_OF_UTTERANCE
    )


class SpeechmaticsResponse(BaseModel):
    """Unknown optional vendor fields do not invalidate known, validated fields."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )


class SpeechmaticsRecognitionStarted(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.RECOGNITION_STARTED]
    id: str | None = None


class SpeechmaticsAudioAdded(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.AUDIO_ADDED]
    seq_no: int = Field(strict=True, ge=0)


class SpeechmaticsResultKind(StrEnum):
    WORD = "word"
    PUNCTUATION = "punctuation"
    ENTITY = "entity"


class SpeechmaticsAlternative(SpeechmaticsResponse):
    content: str = Field(repr=False)
    confidence: float = Field(strict=True, ge=0, le=1)
    language: str | None = None
    speaker: str | None = None


class SpeechmaticsTimedResponse(SpeechmaticsResponse):
    """Native timings are audio-relative seconds, never wall-clock timestamps."""

    start_time: float = Field(strict=True, ge=0)
    end_time: float = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def ordered_times(self) -> SpeechmaticsTimedResponse:
        if self.end_time < self.start_time:
            raise ValueError("Speechmatics end time precedes start time.")
        return self


class SpeechmaticsToken(SpeechmaticsTimedResponse):
    type: Literal[SpeechmaticsResultKind.WORD, SpeechmaticsResultKind.PUNCTUATION]
    alternatives: tuple[SpeechmaticsAlternative, ...] = Field(default=(), repr=False)


class SpeechmaticsEntity(SpeechmaticsTimedResponse):
    type: Literal[SpeechmaticsResultKind.ENTITY]
    entity_class: str | None = None
    spoken_form: tuple[SpeechmaticsToken, ...] = Field(default=(), repr=False)
    written_form: tuple[SpeechmaticsToken, ...] = Field(default=(), repr=False)


SpeechmaticsResult = Annotated[
    SpeechmaticsToken | SpeechmaticsEntity, Field(discriminator="type")
]


class SpeechmaticsTranscriptMetadata(SpeechmaticsTimedResponse):
    transcript: str = Field(repr=False)


class SpeechmaticsTranscript(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.PARTIAL, SpeechmaticsMessage.FINAL]
    metadata: SpeechmaticsTranscriptMetadata = Field(repr=False)
    results: tuple[SpeechmaticsResult, ...] = Field(repr=False)
    forced: StrictBool = False


class SpeechmaticsUtteranceMetadata(SpeechmaticsResponse):
    """EOU timing is optional in the protocol; missing values remain unknown."""

    start_time: float | None = Field(default=None, strict=True, ge=0)
    end_time: float | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def ordered_times(self) -> SpeechmaticsUtteranceMetadata:
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time < self.start_time
        ):
            raise ValueError("Speechmatics end time precedes start time.")
        return self


class SpeechmaticsEndOfUtterance(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.END_OF_UTTERANCE]
    metadata: SpeechmaticsUtteranceMetadata
    forced: StrictBool = False


class SpeechmaticsEndOfTranscript(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.END_OF_TRANSCRIPT]


class SpeechmaticsErrorKind(StrEnum):
    INVALID_MESSAGE = "invalid_message"
    INVALID_MODEL = "invalid_model"
    INVALID_LANGUAGE = "invalid_language"
    INVALID_CONFIG = "invalid_config"
    INVALID_AUDIO_TYPE = "invalid_audio_type"
    INVALID_OUTPUT_FORMAT = "invalid_output_format"
    NOT_AUTHORISED = "not_authorised"
    NOT_ALLOWED = "not_allowed"
    JOB_ERROR = "job_error"
    PROTOCOL_ERROR = "protocol_error"
    QUOTA_EXCEEDED = "quota_exceeded"
    TIMELIMIT_EXCEEDED = "timelimit_exceeded"
    IDLE_TIMEOUT = "idle_timeout"
    SESSION_TIMEOUT = "session_timeout"
    UNKNOWN_ERROR = "unknown_error"


class SpeechmaticsError(SpeechmaticsResponse):
    message: Literal[SpeechmaticsMessage.ERROR]
    type: SpeechmaticsErrorKind
    reason: str = Field(repr=False)
    code: int | None = Field(default=None, strict=True)
    seq_no: int | None = Field(default=None, strict=True, ge=0)


SpeechmaticsEvent = Annotated[
    SpeechmaticsRecognitionStarted
    | SpeechmaticsAudioAdded
    | SpeechmaticsTranscript
    | SpeechmaticsEndOfUtterance
    | SpeechmaticsEndOfTranscript
    | SpeechmaticsError,
    Field(discriminator="message"),
]
_EVENT_ADAPTER = TypeAdapter(
    SpeechmaticsEvent, config=ConfigDict(hide_input_in_errors=True)
)
_RECEIVED_MESSAGES = frozenset(
    {
        SpeechmaticsMessage.RECOGNITION_STARTED,
        SpeechmaticsMessage.AUDIO_ADDED,
        SpeechmaticsMessage.PARTIAL,
        SpeechmaticsMessage.FINAL,
        SpeechmaticsMessage.END_OF_UTTERANCE,
        SpeechmaticsMessage.END_OF_TRANSCRIPT,
        SpeechmaticsMessage.ERROR,
    }
)


class _Envelope(SpeechmaticsResponse):
    message: str


def parse_speechmatics_event(raw: str | bytes) -> SpeechmaticsEvent | None:
    """Unknown kinds are skipped; malformed known messages fail without raw text in errors."""
    envelope = _Envelope.model_validate_json(raw)
    if envelope.message not in _RECEIVED_MESSAGES:
        return None
    return _EVENT_ADAPTER.validate_json(raw)
