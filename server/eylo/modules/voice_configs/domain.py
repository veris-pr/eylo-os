"""Provider-specific validation and resolved runtime values for voice configs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    SerializationInfo,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from eylo.common.contracts.realtime_runtime import (
    RealtimeAWSCredentials,
    RealtimeApiKeyCredentials,
    RealtimeCredentials,
    RealtimeInferenceConfig,
)
from eylo.common.contracts.speech_runtime import (
    STTCredentials,
    STTInferenceConfig,
    SpeechAWSCredentials,
    SpeechApiKeyCredentials,
    SpeechGoogleCredentials,
    SpeechText,
    TTSCredentials,
    TTSInferenceConfig,
)
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)
from eylo.modules.voice_configs.catalog import (
    AMAZON_NOVA_SONIC_ENDPOINTING_SENSITIVITIES,
    AMAZON_NOVA_SONIC_MODELS,
    AMAZON_NOVA_SONIC_VOICES,
    RealtimeProviders,
    STTProviders,
    TTSProviders,
    VoiceKind,
)

__all__ = [
    "InvalidVoiceConfig",
    "ResolvedRealtime",
    "ResolvedSTT",
    "ResolvedTTS",
    "VoiceProviderConfig",
    "VoiceKind",
]

_SECRET_FIELD_NAME = "api_key"
_GOOGLE_SECRET_FIELD_NAME = "service_account_json"
_AWS_SECRET_FIELDS = frozenset({"access_key_id", "secret_access_key", "session_token"})
_AWS_REQUIRED_SECRET_FIELDS = frozenset({"access_key_id", "secret_access_key"})
_AWS_PROVIDERS = frozenset(
    {
        RealtimeProviders.AMAZON_NOVA_SONIC,
        STTProviders.AMAZON_TRANSCRIBE,
        TTSProviders.AMAZON_POLLY,
    }
)
_AWS_REGION_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+-\d+$")
_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2,8}){0,2}$")
_AWS_RESOURCE_NAME_PATTERN = re.compile(r"^[0-9A-Za-z._-]{1,200}$")
_POLLY_ENGINES = frozenset({"standard", "neural", "long-form", "generative"})
_PARTIAL_RESULTS_STABILITIES = frozenset({"low", "medium", "high"})
_RETIRED_FLUX_VAD_SETTING = "high_vad_sensitivity"

VoiceProvider = STTProviders | TTSProviders | RealtimeProviders
_ProviderKey = tuple[
    type[STTProviders] | type[TTSProviders] | type[RealtimeProviders],
    str,
]

_CONFIG_FIELDS: dict[_ProviderKey, frozenset[str]] = {
    (RealtimeProviders, RealtimeProviders.AMAZON_NOVA_SONIC.value): frozenset(
        {
            "region",
            "model",
            "voice",
            "max_tokens",
            "temperature",
            "top_p",
            "endpointing_sensitivity",
        }
    ),
    (RealtimeProviders, RealtimeProviders.GEMINI_LIVE.value): frozenset(
        {
            "model",
            "voice",
            "temperature",
            "context_compression_enabled",
            "context_compression_trigger_tokens",
        }
    ),
    (RealtimeProviders, RealtimeProviders.OPENAI_REALTIME.value): frozenset(
        {
            "model",
            "voice",
            "temperature",
            "input_transcription_model",
            "vad_threshold",
            "vad_silence_ms",
        }
    ),
    (STTProviders, STTProviders.AMAZON_TRANSCRIBE.value): frozenset(
        {
            "region",
            "language",
            "partial_results_stability",
            "vocabulary_name",
            "language_model_name",
            "show_speaker_label",
        }
    ),
    (STTProviders, STTProviders.DEEPGRAM.value): frozenset(
        {
            "model",
            "language",
            "sample_rate",
            "encoding",
            "interim_results",
            "punctuate",
            "vad_events",
            "endpointing",
            "utterance_end_ms",
        }
    ),
    (STTProviders, STTProviders.DEEPGRAM_FLUX.value): frozenset(
        {
            "model",
            "sample_rate",
            "encoding",
            "eot_threshold",
            "eot_timeout_ms",
            _RETIRED_FLUX_VAD_SETTING,
        }
    ),
    (STTProviders, STTProviders.SARVAM.value): frozenset(
        {
            "model",
            "language",
            "mode",
            "sample_rate",
            "encoding",
            "input_audio_codec",
            "high_vad_sensitivity",
            "flush_signal",
        }
    ),
    (STTProviders, STTProviders.ASSEMBLYAI.value): frozenset(
        {
            "model",
            "sample_rate",
            "encoding",
            "eot_threshold",
            "eot_timeout_ms",
            "keyterms_prompt",
        }
    ),
    (STTProviders, STTProviders.CARTESIA.value): frozenset(
        {"model", "language", "sample_rate", "encoding"}
    ),
    (STTProviders, STTProviders.GOOGLE.value): frozenset(
        {
            "model",
            "language",
            "sample_rate",
            "interim_results",
            "punctuation",
            "profanity_filter",
            "detect_language",
            "alternative_languages",
        }
    ),
    (STTProviders, STTProviders.GLADIA.value): frozenset(
        {"language", "sample_rate", "encoding", "buffer_size_seconds"}
    ),
    (STTProviders, STTProviders.REVAI.value): frozenset({"language", "sample_rate"}),
    (STTProviders, STTProviders.SPEECHMATICS.value): frozenset(
        {
            "language",
            "sample_rate",
            "enable_partials",
            "enable_entities",
            "max_delay",
            "diarization",
            "custom_vocabulary",
        }
    ),
    (TTSProviders, TTSProviders.ELEVENLABS.value): frozenset(
        {
            "model",
            "voice",
            "language",
            "sample_rate",
            "encoding",
            "speed",
            "stability",
            "similarity_boost",
            "style",
            "use_speaker_boost",
        }
    ),
    (TTSProviders, TTSProviders.AMAZON_POLLY.value): frozenset(
        {"region", "model", "voice", "language"}
    ),
    (TTSProviders, TTSProviders.CARTESIA.value): frozenset(
        {"model", "voice", "language", "sample_rate", "encoding", "speed"}
    ),
    (TTSProviders, TTSProviders.SARVAM.value): frozenset(
        {
            "model",
            "voice",
            "language",
            "sample_rate",
            "encoding",
            "pitch",
            "pace",
            "loudness",
            "temperature",
        }
    ),
    (TTSProviders, TTSProviders.OPENAI.value): frozenset({"model", "voice", "speed"}),
    (TTSProviders, TTSProviders.DEEPGRAM.value): frozenset(
        {"model", "sample_rate", "encoding", "container"}
    ),
    (TTSProviders, TTSProviders.GROQ.value): frozenset(
        {"model", "voice", "sample_rate"}
    ),
    (TTSProviders, TTSProviders.RIME.value): frozenset(
        {"model", "voice", "sample_rate", "audio_format"}
    ),
    (TTSProviders, TTSProviders.SMALLEST.value): frozenset(
        {"model", "voice", "language", "sample_rate", "add_wav_header"}
    ),
    (TTSProviders, TTSProviders.HUME.value): frozenset(
        {
            "model",
            "voice",
            "voice_description",
            "language",
            "speed",
            "format",
            "sample_rate",
            "instant_mode",
        }
    ),
    (TTSProviders, TTSProviders.MURF.value): frozenset(
        {
            "voice",
            "sample_rate",
            "format",
            "channel_type",
            "style",
            "rate",
            "pitch",
            "variation",
            "min_buffer_size",
            "max_buffer_delay_ms",
        }
    ),
}

_REQUIRED_CONFIG_FIELDS: dict[_ProviderKey, frozenset[str]] = {
    (RealtimeProviders, RealtimeProviders.AMAZON_NOVA_SONIC.value): frozenset(
        {
            "region",
            "model",
            "voice",
            "max_tokens",
            "temperature",
            "top_p",
            "endpointing_sensitivity",
        }
    ),
    (RealtimeProviders, RealtimeProviders.GEMINI_LIVE.value): frozenset(
        {"model", "voice"}
    ),
    (RealtimeProviders, RealtimeProviders.OPENAI_REALTIME.value): frozenset(
        {"model", "voice", "input_transcription_model"}
    ),
    (STTProviders, STTProviders.AMAZON_TRANSCRIBE.value): frozenset(
        {"region", "language"}
    ),
    (STTProviders, STTProviders.DEEPGRAM.value): frozenset({"model", "language"}),
    (STTProviders, STTProviders.DEEPGRAM_FLUX.value): frozenset({"model"}),
    (STTProviders, STTProviders.SARVAM.value): frozenset({"model", "language"}),
    (STTProviders, STTProviders.ASSEMBLYAI.value): frozenset({"model"}),
    (STTProviders, STTProviders.CARTESIA.value): frozenset({"model", "language"}),
    (STTProviders, STTProviders.GOOGLE.value): frozenset({"model", "language"}),
    (STTProviders, STTProviders.GLADIA.value): frozenset({"language"}),
    (STTProviders, STTProviders.REVAI.value): frozenset({"language"}),
    (STTProviders, STTProviders.SPEECHMATICS.value): frozenset({"language"}),
    (TTSProviders, TTSProviders.ELEVENLABS.value): frozenset({"model", "voice"}),
    (TTSProviders, TTSProviders.AMAZON_POLLY.value): frozenset(
        {"region", "model", "voice", "language"}
    ),
    (TTSProviders, TTSProviders.CARTESIA.value): frozenset({"model", "voice"}),
    (TTSProviders, TTSProviders.SARVAM.value): frozenset(
        {"model", "voice", "language"}
    ),
    (TTSProviders, TTSProviders.OPENAI.value): frozenset({"model", "voice"}),
    (TTSProviders, TTSProviders.DEEPGRAM.value): frozenset({"model"}),
    (TTSProviders, TTSProviders.GROQ.value): frozenset({"model", "voice"}),
    (TTSProviders, TTSProviders.RIME.value): frozenset({"model", "voice"}),
    (TTSProviders, TTSProviders.SMALLEST.value): frozenset(
        {"model", "voice", "language"}
    ),
    (TTSProviders, TTSProviders.HUME.value): frozenset({"model", "language"}),
    (TTSProviders, TTSProviders.MURF.value): frozenset({"voice"}),
}


class InvalidVoiceConfig(InvalidProviderConfig):
    """Raised when a voice provider config violates policy."""


class RealtimeProviderSettings(BaseModel):
    """Stored realtime settings separate transport region from model inference."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    region: SpeechText | None = None
    inference: RealtimeInferenceConfig


VoiceProviderSettings = (
    STTInferenceConfig | TTSInferenceConfig | RealtimeProviderSettings
)


def _stored_voice_settings(config: VoiceProviderSettings) -> dict[str, object]:
    """Serialize only explicit values, preserving the existing persistence keys."""
    if not isinstance(config, RealtimeProviderSettings):
        return config.model_dump(mode="json", exclude_unset=True)
    values = config.inference.model_dump(mode="json", exclude_unset=True)
    if "is_context_compression_enabled" in values:
        values["context_compression_enabled"] = values.pop(
            "is_context_compression_enabled"
        )
    if config.region is not None:
        values["region"] = config.region
    return values


class VoiceProviderConfig(BaseModel):
    """Validated settings; plaintext secrets are private and never serialized."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    kind: VoiceKind
    provider: VoiceProvider
    config: VoiceProviderSettings
    secrets: Mapping[str, str] = Field(repr=False, exclude=True)

    @model_validator(mode="wrap")
    @classmethod
    def _validate_fields(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidVoiceConfig(
                "Voice provider configuration contains invalid field values."
            ) from None

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: object, info: ValidationInfo) -> object:
        """Overlapping vendor spellings resolve using their owning capability."""
        if isinstance(value, (STTProviders, TTSProviders, RealtimeProviders)):
            return value
        kind = info.data.get("kind")
        if isinstance(value, str) and isinstance(kind, VoiceKind):
            return _parse_provider(value, kind)
        return value

    @field_validator("config", mode="before")
    @classmethod
    def _settings(cls, value: object, info: ValidationInfo) -> VoiceProviderSettings:
        provider = info.data.get("provider")
        if not isinstance(provider, (STTProviders, TTSProviders, RealtimeProviders)):
            raise InvalidVoiceConfig("Voice settings require a valid provider.")
        if isinstance(provider, STTProviders):
            expected = STTInferenceConfig
        elif isinstance(provider, TTSProviders):
            expected = TTSInferenceConfig
        else:
            expected = RealtimeProviderSettings
        if isinstance(
            value, (STTInferenceConfig, TTSInferenceConfig, RealtimeProviderSettings)
        ):
            if not isinstance(value, expected):
                raise InvalidVoiceConfig(
                    "Voice settings do not match the provider kind."
                )
            values = _stored_voice_settings(expected.model_validate(value))
        elif isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise InvalidVoiceConfig("Voice settings require string keys.")
            if expected is RealtimeProviderSettings and "inference" in value:
                values = _stored_voice_settings(
                    RealtimeProviderSettings.model_validate(value)
                )
            else:
                values = dict(value)
        else:
            raise InvalidVoiceConfig(
                "Voice settings must be a settings object or mapping."
            )
        normalized = _validate_config(values, provider)
        if isinstance(provider, STTProviders):
            return _stt_inference_config(normalized)
        if isinstance(provider, TTSProviders):
            return _tts_inference_config(normalized)
        return RealtimeProviderSettings(
            region=_validate_aws_region(normalized["region"])
            if provider is RealtimeProviders.AMAZON_NOVA_SONIC
            else None,
            inference=_realtime_inference_config(normalized),
        )

    @field_validator("secrets")
    @classmethod
    def _secrets(
        cls, value: Mapping[str, str], info: ValidationInfo
    ) -> Mapping[str, str]:
        provider = info.data.get("provider")
        if not isinstance(provider, (STTProviders, TTSProviders, RealtimeProviders)):
            raise InvalidVoiceConfig("Voice secrets require a valid provider.")
        return MappingProxyType(dict(_validate_secrets(value, provider)))

    @model_validator(mode="after")
    def _validate_kind(self) -> Self:
        validate_voice_provider_kind(self.provider, self.kind)
        return self

    def to_storage_config(self) -> dict[str, object]:
        """An independent JSON projection for the provider persistence boundary."""
        return _stored_voice_settings(self.config)

    @field_serializer("config")
    def _settings_snapshot(
        self, value: VoiceProviderSettings, info: SerializationInfo
    ) -> dict[str, object]:
        """Do not turn absent cross-provider fields into explicit null settings."""
        return value.model_dump(mode=info.mode, exclude_unset=True)

    @classmethod
    def from_storage(
        cls,
        *,
        provider: str,
        kind: VoiceKind,
        config: Mapping[str, object] | VoiceProviderSettings | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> VoiceProviderConfig:
        return cls.model_validate(
            {
                "provider": _parse_provider(provider, kind),
                "kind": kind,
                "config": {} if config is None else config,
                "secrets": {} if secrets is None else secrets,
            }
        )

    @property
    def secret(self) -> str | None:
        return self.secrets.get(_required_secret_field(self.provider))

    @property
    def capability(self) -> Capability:
        return Capability(self.kind.value)


def _parse_provider(provider: str, kind: VoiceKind) -> VoiceProvider:
    normalized = provider.lower().strip()
    try:
        if kind is VoiceKind.STT:
            return STTProviders(normalized)
        if kind is VoiceKind.TTS:
            return TTSProviders(normalized)
        if kind is VoiceKind.REALTIME:
            return RealtimeProviders(normalized)
    except ValueError:
        label = "realtime" if kind is VoiceKind.REALTIME else kind.value.upper()
        raise InvalidVoiceConfig(f"Unknown {label} provider: {provider}") from None
    raise InvalidVoiceConfig(f"Unknown voice kind: {kind}")


def validate_voice_provider_kind(provider: VoiceProvider, kind: VoiceKind) -> None:
    """Refuse a provider from a different voice capability, even with shared names."""
    matches = (
        (kind is VoiceKind.STT and isinstance(provider, STTProviders))
        or (kind is VoiceKind.TTS and isinstance(provider, TTSProviders))
        or (kind is VoiceKind.REALTIME and isinstance(provider, RealtimeProviders))
    )
    if not matches:
        raise InvalidVoiceConfig(
            f"Provider {provider.value} does not match voice kind {kind.value}."
        )


def _validate_config(
    config: Mapping[str, object],
    provider: VoiceProvider,
) -> Mapping[str, object]:
    if not isinstance(config, Mapping):
        raise InvalidVoiceConfig("Config must be a mapping.")
    allowed = _allowed_config_fields(provider)
    unknown = set(config) - allowed
    if unknown:
        raise InvalidVoiceConfig(
            f"Unknown config fields for {provider.value}: {sorted(unknown)}"
        )
    missing = [
        field_name
        for field_name in _required_config_fields(provider)
        if not _is_required_config_value(provider, field_name, config.get(field_name))
    ]
    if missing:
        raise InvalidVoiceConfig(
            f"Provider {provider.value} requires config fields: {missing}"
        )
    if provider is TTSProviders.HUME and not (
        _is_non_empty_string(config.get("voice"))
        or _is_non_empty_string(config.get("voice_description"))
    ):
        raise InvalidVoiceConfig(
            "Provider hume requires config field voice or voice_description."
        )
    normalized = dict(config)
    if provider is STTProviders.DEEPGRAM_FLUX:
        # Older saved configs included this inert field. Accept their shape,
        # but never present it as effective configuration or forward it.
        normalized.pop(_RETIRED_FLUX_VAD_SETTING, None)
    if provider in _AWS_PROVIDERS:
        normalized["region"] = _validate_aws_region(config["region"])
    if provider in {STTProviders.AMAZON_TRANSCRIBE, TTSProviders.AMAZON_POLLY}:
        normalized["language"] = _validate_language_code(config["language"])
    if provider is STTProviders.AMAZON_TRANSCRIBE:
        _validate_amazon_transcribe_config(normalized)
    elif provider is TTSProviders.AMAZON_POLLY:
        _validate_amazon_polly_config(normalized)
    elif isinstance(provider, RealtimeProviders):
        _validate_realtime_config(_realtime_inference_config(normalized), provider)
    if isinstance(provider, STTProviders):
        _stt_inference_config(normalized)
    elif isinstance(provider, TTSProviders):
        _validate_tts_settings(_tts_inference_config(normalized), provider)
    return normalized


def _validate_secrets(
    secrets: Mapping[str, str],
    provider: VoiceProvider,
) -> Mapping[str, str]:
    if not isinstance(secrets, Mapping):
        raise InvalidVoiceConfig("Secrets must be a mapping.")
    allowed_fields = _allowed_secret_fields(provider)
    required_fields = _required_secret_fields(provider)
    unknown = set(secrets) - allowed_fields
    if unknown:
        raise InvalidVoiceConfig(
            f"Unknown secret fields for {provider.value}: {sorted(unknown)}"
        )
    missing = [
        field_name
        for field_name in required_fields
        if not _is_non_empty_string(secrets.get(field_name))
    ]
    invalid_optional = [
        field_name
        for field_name in set(secrets) - required_fields
        if not _is_non_empty_string(secrets.get(field_name))
    ]
    if missing:
        raise InvalidVoiceConfig(
            f"Provider {provider.value} requires non-empty secrets: {missing}"
        )
    if invalid_optional:
        raise InvalidVoiceConfig(
            f"Provider {provider.value} has empty optional secrets: {invalid_optional}"
        )
    return dict(secrets)


def _allowed_config_fields(provider: VoiceProvider) -> frozenset[str]:
    return _CONFIG_FIELDS[(type(provider), provider.value)]


def _required_config_fields(
    provider: VoiceProvider,
) -> frozenset[str]:
    return _REQUIRED_CONFIG_FIELDS[(type(provider), provider.value)]


def _allowed_secret_fields(
    provider: VoiceProvider,
) -> frozenset[str]:
    if provider in _AWS_PROVIDERS:
        return _AWS_SECRET_FIELDS
    return frozenset({_required_secret_field(provider)})


def _required_secret_fields(
    provider: VoiceProvider,
) -> frozenset[str]:
    if provider in _AWS_PROVIDERS:
        return _AWS_REQUIRED_SECRET_FIELDS
    return frozenset({_required_secret_field(provider)})


def _required_secret_field(provider: VoiceProvider) -> str:
    if provider is STTProviders.GOOGLE:
        return _GOOGLE_SECRET_FIELD_NAME
    return _SECRET_FIELD_NAME


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_required_config_value(
    provider: VoiceProvider,
    field_name: str,
    value: object,
) -> bool:
    if provider is RealtimeProviders.AMAZON_NOVA_SONIC and field_name in {
        "max_tokens",
        "temperature",
        "top_p",
    }:
        return not isinstance(value, bool) and isinstance(value, (int, float))
    return _is_non_empty_string(value)


def _validate_aws_region(value: object) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) > 64 or not _AWS_REGION_PATTERN.fullmatch(normalized):
        raise InvalidVoiceConfig("region must be a valid AWS region identifier.")
    return normalized


def _validate_language_code(value: object) -> str:
    normalized = str(value).strip()
    if not _LANGUAGE_CODE_PATTERN.fullmatch(normalized):
        raise InvalidVoiceConfig(
            "language must be an ISO language code accepted by the provider."
        )
    return normalized


def _validate_amazon_transcribe_config(config: Mapping[str, object]) -> None:
    stability = config.get("partial_results_stability")
    if stability is not None and stability not in _PARTIAL_RESULTS_STABILITIES:
        raise InvalidVoiceConfig(
            "partial_results_stability must be low, medium, or high."
        )
    speaker_labels = config.get("show_speaker_label")
    if speaker_labels is not None and not isinstance(speaker_labels, bool):
        raise InvalidVoiceConfig("show_speaker_label must be a boolean.")
    for field_name in ("vocabulary_name", "language_model_name"):
        value = config.get(field_name)
        if value is not None and (
            not isinstance(value, str)
            or not _AWS_RESOURCE_NAME_PATTERN.fullmatch(value)
        ):
            raise InvalidVoiceConfig(f"{field_name} must be a valid AWS resource name.")


def _validate_amazon_polly_config(config: Mapping[str, object]) -> None:
    if config.get("model") not in _POLLY_ENGINES:
        raise InvalidVoiceConfig(
            "model must be standard, neural, long-form, or generative."
        )
    voice = config.get("voice")
    if not isinstance(voice, str) or not re.fullmatch(r"[0-9A-Za-z-]{1,50}", voice):
        raise InvalidVoiceConfig("voice must be a valid Amazon Polly voice ID.")


def _realtime_inference_config(config: Mapping[str, object]) -> RealtimeInferenceConfig:
    """Translate persisted setting names once; region belongs to connection setup."""
    values = dict(config)
    values.pop("region", None)
    if "context_compression_enabled" in values:
        values["is_context_compression_enabled"] = values.pop(
            "context_compression_enabled"
        )
    try:
        return RealtimeInferenceConfig.model_validate(values)
    except ValidationError:
        raise InvalidVoiceConfig(
            "Realtime settings contain invalid field values."
        ) from None


def _validate_realtime_config(
    config: RealtimeInferenceConfig,
    provider: RealtimeProviders,
) -> None:
    if provider is RealtimeProviders.AMAZON_NOVA_SONIC:
        _validate_amazon_nova_sonic_config(config)
        return

    temperature = config.temperature

    if provider is RealtimeProviders.GEMINI_LIVE:
        if temperature is not None and not _is_number_between(
            temperature, minimum=0, maximum=2
        ):
            raise InvalidVoiceConfig("temperature must be between 0 and 2.")
        return

    if temperature is not None:
        raise InvalidVoiceConfig("temperature is not supported by OpenAI Realtime.")

    if config.input_transcription_model is None:
        raise InvalidVoiceConfig(
            "input_transcription_model must be a non-empty string."
        )


def _validate_amazon_nova_sonic_config(config: RealtimeInferenceConfig) -> None:
    if config.model not in AMAZON_NOVA_SONIC_MODELS:
        raise InvalidVoiceConfig(
            "model must be a supported Amazon Nova 2 Sonic model ID."
        )
    if config.voice not in AMAZON_NOVA_SONIC_VOICES:
        raise InvalidVoiceConfig("voice must be a supported Amazon Nova 2 Sonic voice.")

    if config.max_tokens is None:
        raise InvalidVoiceConfig("max_tokens must be a positive integer.")
    if not _is_number_between(config.temperature, minimum=0, maximum=1):
        raise InvalidVoiceConfig("temperature must be between 0 and 1.")
    if not _is_number_between(config.top_p, minimum=0, maximum=1):
        raise InvalidVoiceConfig("top_p must be between 0 and 1.")
    if (
        config.endpointing_sensitivity
        not in AMAZON_NOVA_SONIC_ENDPOINTING_SENSITIVITIES
    ):
        raise InvalidVoiceConfig(
            "endpointing_sensitivity must be HIGH, MEDIUM, or LOW."
        )


def _is_number_between(value: object, *, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and minimum <= float(value) <= maximum
    )


def _stt_inference_config(config: Mapping[str, object]) -> STTInferenceConfig:
    try:
        return STTInferenceConfig.model_validate(config)
    except ValidationError:
        raise InvalidVoiceConfig("STT settings contain invalid field values.") from None


def _tts_inference_config(config: Mapping[str, object]) -> TTSInferenceConfig:
    try:
        return TTSInferenceConfig.model_validate(config)
    except ValidationError:
        raise InvalidVoiceConfig("TTS settings contain invalid field values.") from None


def _validate_tts_settings(config: TTSInferenceConfig, provider: TTSProviders) -> None:
    """Disambiguate platform fields whose native type depends on the provider."""
    if provider is TTSProviders.ELEVENLABS and isinstance(config.style, str):
        raise InvalidVoiceConfig("ElevenLabs style must be a number.")
    if provider is TTSProviders.MURF:
        if config.style is not None and not isinstance(config.style, str):
            raise InvalidVoiceConfig("Murf style must be text.")
        if config.pitch is not None and not isinstance(config.pitch, int):
            raise InvalidVoiceConfig("Murf pitch must be an integer.")


def _validate_resolved_speech_config(
    config: STTInferenceConfig | TTSInferenceConfig,
    provider: STTProviders | TTSProviders,
) -> None:
    """A runtime snapshot must already contain the normalized storage values."""
    values = config.model_dump(mode="json", exclude_unset=True)
    if _validate_config(values, provider) != values:
        raise InvalidVoiceConfig("Resolved speech settings must be normalized.")


class _ResolvedSpeechProvider(BaseModel):
    """Immutable resolution facts; agreement checks do not replace authorization."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @model_validator(mode="wrap")
    @classmethod
    def _validate_fields(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidVoiceConfig(
                "Resolved speech configuration contains invalid field values."
            ) from None


class ResolvedSTT(_ResolvedSpeechProvider):
    """Checked recognition settings and private, provider-matched credentials."""

    provider: STTProviders
    config: STTInferenceConfig
    credentials: STTCredentials = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def _validate_material(self) -> Self:
        _validate_resolved_speech_config(self.config, self.provider)
        if self.provider is STTProviders.AMAZON_TRANSCRIBE:
            valid_credentials = isinstance(self.credentials, SpeechAWSCredentials)
        elif self.provider is STTProviders.GOOGLE:
            valid_credentials = isinstance(self.credentials, SpeechGoogleCredentials)
        else:
            valid_credentials = isinstance(self.credentials, SpeechApiKeyCredentials)
        if not valid_credentials:
            raise InvalidVoiceConfig("STT credentials do not match the provider.")
        return self

    @classmethod
    def from_voice_config(
        cls,
        *,
        provider_config_id: UUID,
        provider_config_revision: int,
        organization_id: UUID,
        config: VoiceProviderConfig,
        configured: bool = True,
        verified: bool = False,
        ready: bool = False,
        granted: bool = False,
    ) -> ResolvedSTT:
        if config.kind is not VoiceKind.STT or not isinstance(
            config.provider, STTProviders
        ):
            raise InvalidVoiceConfig("STT runtime requires an STT provider.")
        validated = VoiceProviderConfig.from_storage(
            provider=config.provider.value,
            kind=VoiceKind.STT,
            config=config.config,
            secrets=config.secrets,
        )
        credentials: STTCredentials
        if not isinstance(validated.config, STTInferenceConfig):
            raise InvalidVoiceConfig("STT runtime requires STT settings.")
        try:
            if config.provider is STTProviders.AMAZON_TRANSCRIBE:
                credentials = SpeechAWSCredentials.model_validate(validated.secrets)
            elif config.provider is STTProviders.GOOGLE:
                credentials = SpeechGoogleCredentials.model_validate(validated.secrets)
            else:
                credentials = SpeechApiKeyCredentials.model_validate(validated.secrets)
        except ValidationError:
            raise InvalidVoiceConfig(
                "STT credentials contain invalid field values."
            ) from None
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            organization_id=organization_id,
            provider=config.provider,
            config=validated.config,
            credentials=credentials,
            configured=configured,
            verified=verified,
            ready=ready,
            granted=granted,
        )

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedSTT:
        _validate_speech_identity(
            provider_config, organization_id, provider_config_id, Capability.STT
        )
        validated = VoiceProviderConfig.from_storage(
            provider=provider_config.provider,
            kind=VoiceKind.STT,
            config=provider_config.settings,
            secrets=provider_config.secrets,
        )
        return cls.from_voice_config(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config.revision,
            organization_id=organization_id,
            config=validated,
            configured=provider_config.configured,
            verified=provider_config.verified,
            ready=provider_config.ready,
            granted=provider_config.granted,
        )


class ResolvedTTS(_ResolvedSpeechProvider):
    """Checked synthesis settings and private, provider-matched credentials."""

    provider: TTSProviders
    config: TTSInferenceConfig
    credentials: TTSCredentials = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def _validate_material(self) -> Self:
        _validate_resolved_speech_config(self.config, self.provider)
        if self.provider is TTSProviders.AMAZON_POLLY:
            valid_credentials = isinstance(self.credentials, SpeechAWSCredentials)
        else:
            valid_credentials = isinstance(self.credentials, SpeechApiKeyCredentials)
        if not valid_credentials:
            raise InvalidVoiceConfig("TTS credentials do not match the provider.")
        return self

    @classmethod
    def from_voice_config(
        cls,
        *,
        provider_config_id: UUID,
        provider_config_revision: int,
        organization_id: UUID,
        config: VoiceProviderConfig,
        configured: bool = True,
        verified: bool = False,
        ready: bool = False,
        granted: bool = False,
    ) -> ResolvedTTS:
        if config.kind is not VoiceKind.TTS or not isinstance(
            config.provider, TTSProviders
        ):
            raise InvalidVoiceConfig("TTS runtime requires a TTS provider.")
        validated = VoiceProviderConfig.from_storage(
            provider=config.provider.value,
            kind=VoiceKind.TTS,
            config=config.config,
            secrets=config.secrets,
        )
        credentials: TTSCredentials
        if not isinstance(validated.config, TTSInferenceConfig):
            raise InvalidVoiceConfig("TTS runtime requires TTS settings.")
        try:
            if config.provider is TTSProviders.AMAZON_POLLY:
                credentials = SpeechAWSCredentials.model_validate(validated.secrets)
            else:
                credentials = SpeechApiKeyCredentials.model_validate(validated.secrets)
        except ValidationError:
            raise InvalidVoiceConfig(
                "TTS credentials contain invalid field values."
            ) from None
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            organization_id=organization_id,
            provider=config.provider,
            config=validated.config,
            credentials=credentials,
            configured=configured,
            verified=verified,
            ready=ready,
            granted=granted,
        )

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedTTS:
        _validate_speech_identity(
            provider_config, organization_id, provider_config_id, Capability.TTS
        )
        validated = VoiceProviderConfig.from_storage(
            provider=provider_config.provider,
            kind=VoiceKind.TTS,
            config=provider_config.settings,
            secrets=provider_config.secrets,
        )
        return cls.from_voice_config(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config.revision,
            organization_id=organization_id,
            config=validated,
            configured=provider_config.configured,
            verified=provider_config.verified,
            ready=provider_config.ready,
            granted=provider_config.granted,
        )


def _validate_speech_identity(
    config: EffectiveProviderConfig,
    organization_id: UUID,
    provider_config_id: UUID,
    capability: Capability,
) -> None:
    if (
        config.organization_id != organization_id
        or config.provider_config_id != provider_config_id
        or config.capability is not capability
    ):
        raise InvalidVoiceConfig("Effective speech provider identity does not match.")


class ResolvedRealtime(BaseModel):
    """Immutable runtime material; identity agreement is not a grant check.

    Resolution owns authorization. Credentials stay in memory and are excluded
    from repr/serialization; consumers use fields, never storage dictionary keys.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    provider: RealtimeProviders
    config: RealtimeInferenceConfig
    region: str | None = None
    credentials: RealtimeCredentials = Field(repr=False, exclude=True)
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @model_validator(mode="wrap")
    @classmethod
    def _validate_fields(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidVoiceConfig(
                "Resolved realtime configuration contains invalid field values."
            ) from None

    @model_validator(mode="after")
    def _validate_provider_material(self) -> Self:
        _validate_realtime_config(self.config, self.provider)
        if self.provider is RealtimeProviders.AMAZON_NOVA_SONIC:
            if not isinstance(self.credentials, RealtimeAWSCredentials):
                raise InvalidVoiceConfig("Amazon Nova Sonic requires AWS credentials.")
            if self.region is None or self.region != _validate_aws_region(self.region):
                raise InvalidVoiceConfig("region must be a normalized AWS region.")
        elif not isinstance(self.credentials, RealtimeApiKeyCredentials):
            raise InvalidVoiceConfig("Realtime provider requires API key credentials.")
        elif self.region is not None:
            raise InvalidVoiceConfig(
                "region is not supported by this realtime provider."
            )
        return self

    @classmethod
    def from_voice_config(
        cls,
        *,
        provider_config_id: UUID,
        provider_config_revision: int,
        organization_id: UUID,
        config: VoiceProviderConfig,
        configured: bool = True,
        verified: bool = False,
        ready: bool = False,
        granted: bool = False,
    ) -> ResolvedRealtime:
        """Hydrate stored JSON for runtime or a bounded verification/inspection."""
        if config.kind is not VoiceKind.REALTIME or not isinstance(
            config.provider, RealtimeProviders
        ):
            raise InvalidVoiceConfig("Realtime runtime requires a realtime provider.")
        # Revalidate copied instances before admitting them to a runtime snapshot.
        validated = VoiceProviderConfig.from_storage(
            provider=config.provider.value,
            kind=VoiceKind.REALTIME,
            config=config.config,
            secrets=config.secrets,
        )
        credentials: RealtimeCredentials
        if not isinstance(validated.config, RealtimeProviderSettings):
            raise InvalidVoiceConfig("Realtime runtime requires realtime settings.")
        try:
            if config.provider is RealtimeProviders.AMAZON_NOVA_SONIC:
                credentials = RealtimeAWSCredentials.model_validate(validated.secrets)
            else:
                credentials = RealtimeApiKeyCredentials.model_validate(
                    validated.secrets
                )
        except ValidationError:
            raise InvalidVoiceConfig(
                "Realtime credentials contain invalid field values."
            ) from None
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            organization_id=organization_id,
            provider=config.provider,
            config=validated.config.inference,
            region=validated.config.region,
            credentials=credentials,
            configured=configured,
            verified=verified,
            ready=ready,
            granted=granted,
        )

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedRealtime:
        if (
            provider_config.organization_id != organization_id
            or provider_config.provider_config_id != provider_config_id
            or provider_config.capability is not Capability.REALTIME
        ):
            raise InvalidVoiceConfig(
                "Effective realtime provider identity does not match."
            )
        validated = VoiceProviderConfig.from_storage(
            provider=provider_config.provider,
            kind=VoiceKind.REALTIME,
            config=provider_config.settings,
            secrets=provider_config.secrets,
        )
        return cls.from_voice_config(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config.revision,
            organization_id=organization_id,
            config=validated,
            configured=provider_config.configured,
            verified=provider_config.verified,
            ready=provider_config.ready,
            granted=provider_config.granted,
        )

    @property
    def provider_id(self) -> str:
        return self.provider.value
