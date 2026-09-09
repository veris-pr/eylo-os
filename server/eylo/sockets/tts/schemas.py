"""Data contracts for the `tts` socket."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

from eylo.sockets.tts.exceptions import TTSConfigurationError

DEFAULT_TTS_SAMPLE_RATE = 24000
DEFAULT_TTS_ENCODING = "pcm_s16le"

_RAW_CONTAINER_ALIASES = {"none": "raw", "raw": "raw"}
_AUDIO_ENCODING_ALIASES = {
    "alaw": "pcm_alaw",
    "a-law": "pcm_alaw",
    "linear16": "pcm_s16le",
    "linear_16": "pcm_s16le",
    "mulaw": "pcm_mulaw",
    "mu-law": "pcm_mulaw",
    "pcm": "pcm_s16le",
    "pcm_alaw": "pcm_alaw",
    "pcm_mulaw": "pcm_mulaw",
    "pcm_s16le": "pcm_s16le",
    "s16le": "pcm_s16le",
    "ulaw": "pcm_mulaw",
}


class TTSProvider(str, Enum):
    AMAZON_POLLY = "amazon-polly"
    CARTESIA = "cartesia"
    DEEPGRAM = "deepgram"
    ELEVENLABS = "elevenlabs"
    GROQ = "groq"
    HUME = "hume"
    MURF = "murf"
    OPENAI = "openai"
    RIME = "rime"
    SARVAM = "sarvam"
    SMALLEST = "smallest"


_AMAZON_POLLY_FALLBACK_SAMPLE_RATE = 16000


class RetryOptions(BaseModel):
    """Retry behavior for vendor connection and synthesis operations."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always", allow_inf_nan=False
    )

    max_retries: StrictInt = Field(default=3, ge=0)
    timeout_seconds: StrictFloat = Field(default=10.0, gt=0)
    retry_interval_seconds: StrictFloat = Field(default=1.0, ge=0)


class TTSCapabilities(BaseModel):
    """Static vendor capabilities used by the manager and transports."""

    model_config = ConfigDict(frozen=True)

    streaming: bool = True
    batch_synthesize: bool = False
    native_interruption: bool = False
    aligned_transcript: bool = False
    emotion_control: bool = False
    speed_control: bool = False
    voice_cloning: bool = False
    context_continuity: bool = False
    word_timestamps: bool = False
    sample_rates: tuple[int, ...] = (DEFAULT_TTS_SAMPLE_RATE,)
    languages_count: int = 1


class TTSAudioFormat(BaseModel):
    """Actual raw audio emitted by one TTS adapter.

    This is deliberately separate from a transport's requested output format.
    A provider may ignore or not support the carrier codec, so the pipeline
    converts between these two explicit contracts instead of treating request
    metadata as proof of the bytes returned.
    """

    model_config = ConfigDict(frozen=True)

    container: Literal["raw"]
    encoding: Literal["pcm_s16le", "pcm_mulaw", "pcm_alaw"]
    sample_rate: int = Field(gt=0)
    channels: Literal[1] = 1

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        container = normalized.get("container")
        encoding = normalized.get("encoding")
        if isinstance(container, str):
            normalized["container"] = _RAW_CONTAINER_ALIASES.get(
                container.strip().lower(),
                container.strip().lower(),
            )
        if isinstance(encoding, str):
            normalized["encoding"] = _AUDIO_ENCODING_ALIASES.get(
                encoding.strip().lower(),
                encoding.strip().lower(),
            )
        return normalized

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TTSAudioFormat":
        """Validate a complete provider or transport media contract."""
        return cls.model_validate(value)


class TTSConfig(BaseModel):
    """Canonical TTS runtime configuration plus provider-specific options."""

    model_config = ConfigDict(
        extra="allow", revalidate_instances="always", hide_input_in_errors=True
    )

    vendor: TTSProvider
    model: StrictStr | None = None
    voice: StrictStr | None = None
    language: StrictStr | None = None
    sample_rate: StrictInt = Field(default=DEFAULT_TTS_SAMPLE_RATE, gt=0)
    encoding: StrictStr = DEFAULT_TTS_ENCODING
    output_format: dict[str, Any] | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    retry: RetryOptions = Field(default_factory=RetryOptions)

    @model_validator(mode="before")
    @classmethod
    def normalize_transport_format(cls, data: Any) -> Any:
        if isinstance(data, TTSConfig):
            return data
        if data is None:
            return {}
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        output_format = normalized.get("output_format")
        if isinstance(output_format, dict):
            sample_rate = output_format.get("sample_rate")
            encoding = output_format.get("encoding")
            if isinstance(sample_rate, int) and "sample_rate" not in normalized:
                normalized["sample_rate"] = sample_rate
            if isinstance(encoding, str) and "encoding" not in normalized:
                normalized["encoding"] = encoding

        return normalized

    def to_adapter_config(self) -> dict[str, object]:
        """One unambiguous adapter payload; nested options cannot shadow fields."""
        try:
            config = TTSConfig.model_validate(self)
        except ValidationError:
            raise TTSConfigurationError("Invalid TTS runtime configuration.") from None
        data = config.model_dump(mode="python", exclude_none=True)
        data["vendor"] = config.vendor.value
        data["retry"] = config.retry.model_dump()
        for key in config.options:
            if key in TTSConfig.model_fields and key not in config.model_fields_set:
                # A supplied option may replace an implicit transport default,
                # but never an explicitly configured value.
                data.pop(key, None)
        return _flatten_options(data)


class TTSAudioChunk(BaseModel):
    """Canonical audio chunk carried inside the TTS manager."""

    data: bytes
    is_final: bool = False
    segment_id: str | None = None
    request_id: str | None = None
    delta_text: str | None = None
    sample_rate: int | None = None
    encoding: str | None = None
    vendor_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_response(
        cls,
        response: bytes | bytearray | memoryview | "TTSAudioChunk",
        *,
        sample_rate: int | None = None,
        encoding: str | None = None,
        request_id: str | None = None,
    ) -> "TTSAudioChunk":
        if isinstance(response, cls):
            updates: dict[str, Any] = {}
            if response.sample_rate is None and sample_rate is not None:
                updates["sample_rate"] = sample_rate
            if response.encoding is None and encoding is not None:
                updates["encoding"] = encoding
            if response.request_id is None and request_id is not None:
                updates["request_id"] = request_id
            if updates:
                return response.model_copy(update=updates)
            return response
        return cls(
            data=bytes(response),
            sample_rate=sample_rate,
            encoding=encoding,
            request_id=request_id,
        )


class TTSEvent(BaseModel):
    """Vendor-agnostic TTS event for future transcript and telemetry paths."""

    type: Literal["audio", "started", "final", "interrupted", "error", "metadata"]
    vendor: TTSProvider | str
    request_id: str | None = None
    chunk: TTSAudioChunk | None = None
    message: str | None = None
    vendor_metadata: dict[str, Any] = Field(default_factory=dict)


class TTSMetricsSnapshot(BaseModel):
    """Lightweight in-memory metrics snapshot for one TTSRealtime instance."""

    vendor: str
    chunks: int = 0
    bytes: int = 0
    first_audio_latency_seconds: float | None = None
    interruptions: int = 0
    request_drops: int = 0
    response_drops: int = 0
    consumer_drops: int = 0
    errors: int = 0
    total_requests_processed: int = 0
    total_responses_processed: int = 0
    start_time: float
    last_activity: float


def normalize_tts_config(
    config: TTSConfig | dict[str, object] | None,
    *,
    vendor: str | TTSProvider | None = None,
    api_key: str | None = None,
) -> TTSConfig:
    """Normalize a provider-config mapping into the canonical TTS contract."""
    data: dict[str, object]
    if isinstance(config, TTSConfig):
        data = config.to_adapter_config()
        # Re-normalization must not turn implicit envelope defaults into native
        # vendor selections. Explicit fields and options retain their authority.
        for field in (
            TTSConfig.model_fields.keys()
            - config.model_fields_set
            - config.options.keys()
        ):
            data.pop(field, None)
    elif isinstance(config, dict):
        data = _flatten_options(dict(config))
    elif config is None:
        data = {}
    else:
        raise TTSConfigurationError("TTS configuration must be an object.")

    configured_vendor = data.get("vendor")
    if configured_vendor is not None and not isinstance(configured_vendor, str):
        raise TTSConfigurationError("Unsupported TTS vendor.")
    if isinstance(configured_vendor, TTSProvider):
        configured_vendor = configured_vendor.value
    selected_vendor = (
        configured_vendor.strip() if isinstance(configured_vendor, str) else None
    )
    if vendor is not None:
        if not isinstance(vendor, str):
            raise TTSConfigurationError("Unsupported TTS vendor.")
        requested_vendor = (
            vendor.value if isinstance(vendor, TTSProvider) else vendor.strip()
        )
        if selected_vendor is not None and selected_vendor != requested_vendor:
            raise TTSConfigurationError(
                "TTS provider config does not match the selected provider."
            )
        selected_vendor = requested_vendor
        data["vendor"] = requested_vendor

    if api_key is not None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise TTSConfigurationError("TTS API key must be nonempty text.")
        data["api_key"] = api_key
    _apply_provider_sample_rate_default(data, selected_vendor)
    try:
        return TTSConfig.model_validate(data)
    except ValidationError:
        raise TTSConfigurationError("Invalid TTS runtime configuration.") from None


def _flatten_options(data: dict[str, object]) -> dict[str, object]:
    """Accept either input spelling, rejecting ambiguity before any native I/O."""
    options = data.pop("options", {})
    if not isinstance(options, dict):
        raise TTSConfigurationError("TTS options must be an object.")
    for key, value in options.items():
        if not isinstance(key, str) or key in {"vendor", "retry", "options"}:
            raise TTSConfigurationError("TTS options contain a reserved field.")
        if key in data and (type(data[key]) is not type(value) or data[key] != value):
            raise TTSConfigurationError("Conflicting TTS configuration fields.")
        data[key] = value
    return data


def _apply_provider_sample_rate_default(
    data: dict[str, object],
    vendor: str | None,
) -> None:
    if vendor != TTSProvider.AMAZON_POLLY.value or "sample_rate" in data:
        return
    output_format = data.get("output_format")
    if isinstance(output_format, dict) and isinstance(
        output_format.get("sample_rate"), int
    ):
        return
    data["sample_rate"] = _AMAZON_POLLY_FALLBACK_SAMPLE_RATE
