"""Typed contracts for the STT socket module."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum, StrEnum
from time import monotonic
from typing import Annotated, Self

import arrow
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.exceptions import STTConfigurationError

_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_EOT_THRESHOLD = 0.85
_DEFAULT_EOT_TIMEOUT_MS = 5000


class STTProvider(StrEnum):
    """Known STT provider identifiers."""

    AMAZON_TRANSCRIBE = "amazon-transcribe"
    DEEPGRAM = "deepgram"
    DEEPGRAM_FLUX = "deepgram-flux"
    ASSEMBLYAI = "assemblyai"
    CARTESIA = "cartesia"
    GLADIA = "gladia"
    GOOGLE = "google"
    REVAI = "revai"
    SARVAM = "sarvam"
    SPEECHMATICS = "speechmatics"


class STTEncoding(StrEnum):
    """Audio encodings accepted at the STT boundary."""

    LINEAR16 = "linear16"
    PCM_S16LE = "pcm_s16le"
    MULAW = "mulaw"
    ALAW = "alaw"


class STTTurnDetection(StrEnum):
    """Turn detection ownership for an STT session."""

    VENDOR = "vendor"
    INTERNAL = "internal"
    NONE = "none"


class STTEndpointingMode(StrEnum):
    """Endpointing strategy for end-of-turn detection."""

    FIXED = "fixed"
    DYNAMIC = "dynamic"


class STTEventType(StrEnum):
    """Recognition outcomes; connection acknowledgements are not speech."""

    TRANSCRIPT_PARTIAL = "transcript_partial"
    TRANSCRIPT_PREFLIGHT = "transcript_preflight"
    TRANSCRIPT_FINAL = "transcript_final"
    SPEECH_START = "speech_start"
    SPEECH_END = "speech_end"
    START_OF_TURN = "start_of_turn"
    END_OF_TURN = "end_of_turn"
    TURN_RESUMED = "turn_resumed"
    RECOGNITION_USAGE = "recognition_usage"
    ERROR = "error"


class STTInterruptionHint(StrEnum):
    """Adapter signal; the voice pipeline still applies interruption policy."""

    NONE = "none"
    REQUESTED = "requested"


class STTTranscriptForm(StrEnum):
    """Independent segments use a separator; deltas already contain their spacing."""

    SEGMENT = "segment"
    DELTA = "delta"


class RetryOptions(BaseModel):
    """Factory connection attempts, never permission to replay audio.

    ``max_retry`` counts attempts after the first. ``timeout`` bounds each
    connect/readiness attempt; ``retry_interval`` follows successful cleanup.
    Both durations are seconds. Cancellation and cleanup failure stop retries.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", allow_inf_nan=False
    )

    max_retry: StrictInt = Field(default=3, ge=0)
    timeout: StrictFloat = Field(default=10.0, gt=0)
    retry_interval: StrictFloat = Field(default=1.0, ge=0)

    @classmethod
    def from_mapping(cls, value: RetryOptions | Mapping[str, object] | None) -> Self:
        """Absent settings use transport defaults; malformed settings are refused."""
        return cls.model_validate({} if value is None else value)


class STTCapabilitySupport(Enum):
    """Adapter capability claim; JSON retains the existing boolean representation."""

    UNSUPPORTED = False
    SUPPORTED = True

    def __bool__(self) -> bool:
        raise TypeError("Compare STT support with its explicit enum member.")


def _capability_support(value: object) -> STTCapabilitySupport:
    if isinstance(value, STTCapabilitySupport):
        return value
    if value is True:
        return STTCapabilitySupport.SUPPORTED
    if value is False:
        return STTCapabilitySupport.UNSUPPORTED
    raise ValueError("STT capability requires explicit support or a boolean.")


STTSupport = Annotated[STTCapabilitySupport, BeforeValidator(_capability_support)]
STTSampleRate = Annotated[StrictInt, Field(gt=0)]
STTText = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class STTCapabilities(BaseModel):
    """Adapter-owned executable features, not a second platform policy catalog."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always"
    )

    streaming: STTSupport = STTCapabilitySupport.SUPPORTED
    batch_recognize: STTSupport = STTCapabilitySupport.UNSUPPORTED
    interim_results: STTSupport = STTCapabilitySupport.SUPPORTED
    vad_events: STTSupport = STTCapabilitySupport.UNSUPPORTED
    turn_detection: STTSupport = STTCapabilitySupport.UNSUPPORTED
    word_timestamps: STTSupport = STTCapabilitySupport.UNSUPPORTED
    speaker_labels: STTSupport = STTCapabilitySupport.UNSUPPORTED
    language_detection: STTSupport = STTCapabilitySupport.UNSUPPORTED
    custom_vocabulary: STTSupport = STTCapabilitySupport.UNSUPPORTED
    punctuation: STTSupport = STTCapabilitySupport.UNSUPPORTED
    profanity_filter: STTSupport = STTCapabilitySupport.UNSUPPORTED
    aligned_transcript: STTSupport = STTCapabilitySupport.UNSUPPORTED
    supported_encodings: tuple[STTEncoding, ...] = (
        STTEncoding.LINEAR16,
        STTEncoding.PCM_S16LE,
    )
    supported_sample_rates: tuple[STTSampleRate, ...] = (8000, 16000, 44100, 48000)


class TimedWord(BaseModel):
    """A transcript token with optional timing and confidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    word: str
    start_time: float | None = None
    end_time: float | None = None
    confidence: float | None = None
    speaker_id: str | None = None


class RecognitionUsage(BaseModel):
    """Usage payload emitted by providers that report cost dimensions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audio_duration: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, strict=True, ge=0)
    output_tokens: int | None = Field(default=None, strict=True, ge=0)


class STTError(BaseModel):
    """Structured STT error details."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    message: str = Field(repr=False)
    recoverable: StrictBool = True
    code: str | None = None


class STTConfig(BaseModel):
    """Validated runtime settings; native fields stay private until adapter handoff."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    vendor: STTProvider
    model: STTText | None = None
    language: STTText | None = None
    sample_rate: STTSampleRate = _DEFAULT_SAMPLE_RATE
    encoding: STTEncoding = STTEncoding.LINEAR16
    interim_results: SpeechOption = SpeechOptionState.ENABLED
    vad_enabled: SpeechOption = SpeechOptionState.ENABLED
    turn_detection: STTTurnDetection = STTTurnDetection.VENDOR
    endpointing_mode: STTEndpointingMode = STTEndpointingMode.FIXED
    eot_threshold: StrictFloat = Field(default=_DEFAULT_EOT_THRESHOLD, ge=0, le=1)
    eot_timeout_ms: StrictInt = Field(default=_DEFAULT_EOT_TIMEOUT_MS, ge=0)
    custom_vocabulary: tuple[STTText, ...] = ()
    word_timestamps: SpeechOption = SpeechOptionState.ENABLED
    speaker_labels: SpeechOption = SpeechOptionState.DISABLED
    batch_enabled: SpeechOption = SpeechOptionState.DISABLED
    wait_ms: StrictFloat = Field(default=0.0, ge=0)
    retry: RetryOptions = Field(default_factory=RetryOptions)
    vendor_options: dict[str, JsonValue] = Field(
        default_factory=dict, repr=False, exclude=True
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, value: object) -> object:
        """Flat native options and the explicit envelope share one validated path."""
        if not isinstance(value, Mapping):
            return value
        data: dict[str, object] = dict(value)
        options = data.pop("vendor_options", {})
        if not isinstance(options, Mapping):
            raise ValueError("STT vendor options must be an object.")
        for name, option in options.items():
            if not isinstance(name, str) or name in {
                "vendor",
                "vendor_options",
                "retry",
            }:
                raise ValueError("STT vendor options contain a reserved field.")
            if name in data and (
                type(data[name]) is not type(option) or data[name] != option
            ):
                raise ValueError("Conflicting STT configuration fields.")
            data[name] = option

        selected_vendor = data.get("vendor")
        if isinstance(selected_vendor, str):
            data["vendor"] = selected_vendor.strip()

        # These raw PCM spellings are adapter input, not a fallback provider/model.
        if "encoding" not in data:
            data["encoding"] = (
                STTEncoding.PCM_S16LE
                if data.get("vendor") in (STTProvider.ASSEMBLYAI, STTProvider.CARTESIA)
                else STTEncoding.LINEAR16
            )
        if data.get("custom_vocabulary") is None:
            data["custom_vocabulary"] = ()
        native = {
            name: item for name, item in data.items() if name not in cls.model_fields
        }
        for name in native:
            del data[name]
        data["vendor_options"] = native
        return data

    @classmethod
    def from_mapping(
        cls,
        value: STTConfig | Mapping[str, object] | None,
        *,
        vendor: str | STTProvider | None = None,
        api_key: str | None = None,
    ) -> Self:
        """Revalidate all entry paths without exposing values in configuration errors."""
        if isinstance(value, STTConfig):
            data = value.to_adapter_config()
            data["retry"] = value.retry
        elif isinstance(value, Mapping):
            data = dict(value)
        elif value is None:
            data = {}
        else:
            raise STTConfigurationError("STT configuration must be an object.")

        selected_vendor = vendor if vendor is not None else data.get("vendor")
        if not isinstance(selected_vendor, str) or not selected_vendor.strip():
            raise STTConfigurationError("STT provider is required.")
        selected_vendor = selected_vendor.strip()
        configured_vendor = data.get("vendor")
        if isinstance(configured_vendor, str):
            configured_vendor = configured_vendor.strip()
        if configured_vendor is not None and configured_vendor != selected_vendor:
            raise STTConfigurationError(
                "STT provider config does not match the selected provider."
            )
        data["vendor"] = selected_vendor
        if api_key is not None:
            if not isinstance(api_key, str) or not api_key.strip():
                raise STTConfigurationError("STT API key must be nonempty text.")
            # Explicit resolved credentials are authoritative over settings.
            options = data.get("vendor_options")
            if isinstance(options, Mapping):
                data["vendor_options"] = {
                    name: item for name, item in options.items() if name != "api_key"
                }
            data["api_key"] = api_key
        try:
            return cls.model_validate(data)
        except ValidationError:
            raise STTConfigurationError("Invalid STT runtime configuration.") from None

    def to_adapter_config(self) -> dict[str, object]:
        """Explicit private handoff; normal model dumps never include native secrets."""
        try:
            config = type(self).model_validate(self)
        except ValidationError:
            raise STTConfigurationError("Invalid STT runtime configuration.") from None
        data: dict[str, object] = config.model_dump(mode="json", exclude_none=True)
        data.update(config.vendor_options)
        return data


class STTEvent(BaseModel):
    """Validated recognition result; never flattened with vendor metadata.

    Finality is derived from the event type. Speech activity cannot masquerade
    as a final transcript, and error/usage events must carry their own payload.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    type: STTEventType
    provider: STTProvider
    session_id: str = ""
    model: str = ""
    transcript: str = Field(default="", repr=False)
    transcript_form: STTTranscriptForm = STTTranscriptForm.SEGMENT
    confidence: float | None = None
    language: str | None = None
    request_id: str | None = None
    provider_request_id: str | None = None
    words: tuple[TimedWord, ...] = Field(default=(), repr=False)
    speaker_id: str | None = None
    audio_start_ms: int | None = None
    audio_end_ms: int | None = None
    interruption_hint: STTInterruptionHint = STTInterruptionHint.NONE
    usage: RecognitionUsage | None = None
    error: STTError | None = None
    timestamp: float = Field(default_factory=lambda: arrow.utcnow().timestamp())
    vendor_metadata: dict[str, JsonValue] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def validate_payload_kind(self) -> "STTEvent":
        if (self.type is STTEventType.ERROR) != (self.error is not None):
            raise ValueError("Only an STT error event carries an error payload.")
        if (self.type is STTEventType.RECOGNITION_USAGE) != (self.usage is not None):
            raise ValueError("Only an STT usage event carries a usage payload.")
        if (
            self.type in {STTEventType.ERROR, STTEventType.RECOGNITION_USAGE}
            and self.transcript
        ):
            raise ValueError("STT error and usage events cannot contain a transcript.")
        return self

    @property
    def is_final(self) -> bool:
        return self.type is STTEventType.TRANSCRIPT_FINAL or (
            self.type is STTEventType.END_OF_TURN and bool(self.transcript)
        )

    @property
    def is_speech_start(self) -> bool:
        return self.type in _SPEECH_START_TYPES

    @property
    def is_speech_end(self) -> bool:
        return self.type in _SPEECH_END_TYPES

    @property
    def is_transcript(self) -> bool:
        return self.type in {
            STTEventType.TRANSCRIPT_PARTIAL,
            STTEventType.TRANSCRIPT_PREFLIGHT,
            STTEventType.TRANSCRIPT_FINAL,
        } or (self.type is STTEventType.END_OF_TURN and bool(self.transcript))


_ByteCount = Annotated[StrictInt, Field(ge=0)]
_BYTE_COUNT = TypeAdapter(_ByteCount)


class STTMetricsSnapshot(BaseModel):
    """Mutable counters; timestamps are process-monotonic seconds, not wall time."""

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, allow_inf_nan=False
    )

    request_count: StrictInt = Field(default=0, ge=0)
    event_count: StrictInt = Field(default=0, ge=0)
    audio_bytes_sent: StrictInt = Field(default=0, ge=0)
    error_count: StrictInt = Field(default=0, ge=0)
    reconnect_count: StrictInt = Field(default=0, ge=0)
    connected_at: StrictFloat | None = Field(default=None, ge=0)
    last_event_at: StrictFloat | None = Field(default=None, ge=0)
    last_event_type: STTEventType | None = None

    def mark_connected(self) -> None:
        """Record connection start time."""
        self.connected_at = monotonic()

    def mark_audio_sent(self, byte_count: int) -> None:
        """Record a sent audio chunk."""
        checked_count = _BYTE_COUNT.validate_python(byte_count)
        self.request_count += 1
        self.audio_bytes_sent += checked_count

    def mark_event(self, event_type: STTEventType) -> None:
        """Record a normalized STT event."""
        checked_type = STTEventType(event_type)
        self.event_count += 1
        self.last_event_type = checked_type
        self.last_event_at = monotonic()

    def mark_error(self) -> None:
        """Record an STT error."""
        self.error_count += 1

    def mark_reconnect(self) -> None:
        """Record a reconnect attempt."""
        self.reconnect_count += 1

    def as_dict(self) -> dict[str, JsonValue]:
        """Return a serializable metrics snapshot."""
        return {
            "request_count": self.request_count,
            "event_count": self.event_count,
            "audio_bytes_sent": self.audio_bytes_sent,
            "error_count": self.error_count,
            "reconnect_count": self.reconnect_count,
            "connected_at": self.connected_at,
            "last_event_at": self.last_event_at,
            "last_event_type": self.last_event_type.value
            if self.last_event_type is not None
            else None,
        }


_SPEECH_START_TYPES = {
    STTEventType.SPEECH_START,
    STTEventType.START_OF_TURN,
    STTEventType.TURN_RESUMED,
}
_SPEECH_END_TYPES = {
    STTEventType.SPEECH_END,
    STTEventType.END_OF_TURN,
}
