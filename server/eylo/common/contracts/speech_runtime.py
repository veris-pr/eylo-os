"""Validated STT/TTS settings and private credentials shared across boundaries.

These are the platform's configurable inputs, not vendor wire payloads. The
owning capability module checks which fields a selected provider accepts;
adapters retain responsibility for native request shapes and protocol choices.
"""

from enum import Enum, StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
)


class SpeechOptionState(Enum):
    """Configured feature policy; preserve existing JSON boolean values."""

    DISABLED = False
    ENABLED = True

    def __bool__(self) -> bool:
        raise TypeError("Compare speech options with their explicit enum member.")


def _option_state(value: object) -> SpeechOptionState:
    if isinstance(value, SpeechOptionState):
        return value
    if value is True:
        return SpeechOptionState.ENABLED
    if value is False:
        return SpeechOptionState.DISABLED
    raise ValueError("Speech option requires an explicit policy or boolean.")


SpeechOption = Annotated[SpeechOptionState, BeforeValidator(_option_state)]
SpeechText = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class _SpeechValue(BaseModel):
    """Revalidate copied inputs; never coerce numbers/booleans into text."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class STTInferenceConfig(_SpeechValue):
    """Explicit operator settings; absent values do not choose a provider/model."""

    model: SpeechText | None = None
    language: SpeechText | None = None
    region: SpeechText | None = None
    sample_rate: StrictInt | None = Field(default=None, gt=0)
    encoding: SpeechText | None = None
    partial_results_stability: SpeechText | None = None
    vocabulary_name: SpeechText | None = None
    language_model_name: SpeechText | None = None
    show_speaker_label: SpeechOption | None = None
    interim_results: SpeechOption | None = None
    punctuate: SpeechOption | None = None
    vad_events: SpeechOption | None = None
    endpointing: StrictInt | SpeechOption | None = None
    utterance_end_ms: StrictInt | None = Field(default=None, ge=0)
    eot_threshold: StrictFloat | None = None
    eot_timeout_ms: StrictInt | None = Field(default=None, ge=0)
    high_vad_sensitivity: SpeechOption | None = None
    mode: SpeechText | None = None
    input_audio_codec: SpeechText | None = None
    flush_signal: SpeechOption | None = None
    keyterms_prompt: tuple[SpeechText, ...] | None = None
    punctuation: SpeechOption | None = None
    profanity_filter: SpeechOption | None = None
    detect_language: SpeechOption | None = None
    alternative_languages: tuple[SpeechText, ...] | None = None
    buffer_size_seconds: StrictFloat | None = Field(default=None, gt=0)
    enable_partials: SpeechOption | None = None
    enable_entities: SpeechOption | None = None
    max_delay: StrictFloat | None = Field(default=None, ge=0)
    diarization: SpeechText | None = None
    custom_vocabulary: tuple[SpeechText, ...] | None = None


class TTSInferenceConfig(_SpeechValue):
    """Known synthesis settings; provider-specific combinations belong to policy."""

    model: SpeechText | None = None
    voice: SpeechText | None = None
    language: SpeechText | None = None
    region: SpeechText | None = None
    sample_rate: StrictInt | None = Field(default=None, gt=0)
    encoding: SpeechText | None = None
    speed: StrictFloat | None = None
    stability: StrictFloat | None = None
    similarity_boost: StrictFloat | None = None
    style: StrictInt | StrictFloat | SpeechText | None = None
    use_speaker_boost: SpeechOption | None = None
    pitch: StrictInt | StrictFloat | None = None
    pace: StrictFloat | None = None
    loudness: StrictFloat | None = None
    temperature: StrictFloat | None = None
    container: SpeechText | None = None
    audio_format: SpeechText | None = None
    add_wav_header: SpeechOption | None = None
    voice_description: SpeechText | None = None
    format: SpeechText | None = None
    instant_mode: SpeechOption | None = None
    channel_type: SpeechText | None = None
    rate: StrictInt | None = None
    variation: StrictInt | None = None
    min_buffer_size: StrictInt | None = Field(default=None, ge=0)
    max_buffer_delay_ms: StrictInt | None = Field(default=None, ge=0)


class SpeechTransportEncoding(StrEnum):
    """Existing raw-media spellings supplied by browser/carrier transports."""

    LINEAR16 = "linear16"
    PCM_S16LE = "pcm_s16le"
    MULAW = "mulaw"
    ALAW = "alaw"


class SpeechTransportFormat(_SpeechValue):
    """Transport may choose media format, never model, language, or credentials."""

    sample_rate: StrictInt = Field(gt=0)
    encoding: SpeechTransportEncoding


class SpeechApiKeyCredentials(_SpeechValue):
    """Private material is excluded even when this object is dumped directly."""

    api_key: SpeechText = Field(repr=False, exclude=True)

    def for_adapter(self) -> dict[str, str]:
        """Explicit plaintext handoff to the selected adapter, never a snapshot."""
        return {"api_key": self.api_key}


class SpeechAWSCredentials(_SpeechValue):
    """Explicit AWS identity; optional session token is not an ambient fallback."""

    access_key_id: SpeechText = Field(repr=False, exclude=True)
    secret_access_key: SpeechText = Field(repr=False, exclude=True)
    session_token: SpeechText | None = Field(default=None, repr=False, exclude=True)

    def for_adapter(self) -> dict[str, str]:
        """Expose only the configured AWS credential fields to the adapter."""
        values = {
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
        }
        if self.session_token is not None:
            values["session_token"] = self.session_token
        return values


class SpeechGoogleCredentials(_SpeechValue):
    """Opaque service-account document; Google-native parsing stays in its socket."""

    service_account_json: SpeechText = Field(repr=False, exclude=True)

    def for_adapter(self) -> dict[str, str]:
        """Explicitly expose the service-account document at adapter handoff."""
        return {"service_account_json": self.service_account_json}


STTCredentials = (
    SpeechApiKeyCredentials | SpeechAWSCredentials | SpeechGoogleCredentials
)
TTSCredentials = SpeechApiKeyCredentials | SpeechAWSCredentials
