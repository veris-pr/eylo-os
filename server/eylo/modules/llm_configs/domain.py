"""Provider policies and immutable runtime values for LLM configuration."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from eylo.common.contracts.llm_catalog import (
    LLMModels,
    LLMProviders,
    is_model_supported,
)
from eylo.common.contracts.llm_runtime import (
    InvalidLLMConfig,
    LLMConfigError,
    LLMConfigValue,
    LLMGenerationConfig,
    LLMGenerationParameters,
)
from eylo.modules.provider_configs.masking import MASKED_SECRET_VALUE

__all__ = [
    "InvalidLLMConfig",
    "LLMConfigError",
    "LLMGenerationSettings",
    "LLMOverrides",
    "LLMProviderConfig",
    "ResolvedLLM",
    "ResolvePinnedLLM",
]

_COMMON_CONFIG_FIELDS = frozenset(
    {
        "model",
        "max_tokens",
        "top_k",
        "top_p",
        "temperature",
        "stop_sequences",
    }
)
_BEDROCK_CONFIG_FIELDS = frozenset({"region"})
_TOP_K_PROVIDERS = frozenset(
    {LLMProviders.ANTHROPIC, LLMProviders.BEDROCK, LLMProviders.GEMINI}
)
_STOP_SEQUENCE_PROVIDERS = frozenset(
    provider
    for provider in LLMProviders
    if provider is not LLMProviders.OPENAI_RESPONSES
)
_REQUIRED_MAX_TOKENS_PROVIDERS = frozenset(
    {LLMProviders.ANTHROPIC, LLMProviders.BEDROCK}
)
_API_KEY_PROVIDERS = frozenset(
    {
        LLMProviders.ANTHROPIC,
        LLMProviders.CEREBRAS,
        LLMProviders.GEMINI,
        LLMProviders.GROQ,
        LLMProviders.OPENAI,
        LLMProviders.OPENAI_RESPONSES,
        LLMProviders.SARVAM,
    }
)
_API_KEY_SECRET_FIELDS = frozenset({"api_key"})
_BEDROCK_STORED_REQUIRED_SECRET_FIELDS = frozenset(
    {"access_key_id", "secret_access_key"}
)
_BEDROCK_STORED_SECRET_FIELDS = frozenset(
    {*_BEDROCK_STORED_REQUIRED_SECRET_FIELDS, "session_token"}
)


class LLMGenerationSettings(LLMGenerationConfig):
    """Generation values with provider-specific override and storage policy."""

    def apply(
        self,
        *,
        provider: LLMProviders,
        overrides: "LLMOverrides",
    ) -> "LLMGenerationSettings":
        current = LLMGenerationSettings.model_validate(self)
        overrides = LLMOverrides.model_validate(overrides)
        allowed = _allowed_generation_fields(provider)
        effective = LLMGenerationSettings(
            model=current.model if overrides.model is None else overrides.model,
            max_tokens=(
                current.max_tokens
                if overrides.max_tokens is None or "max_tokens" not in allowed
                else overrides.max_tokens
            ),
            top_k=(
                current.top_k
                if overrides.top_k is None or "top_k" not in allowed
                else overrides.top_k
            ),
            top_p=(
                current.top_p
                if overrides.top_p is None or "top_p" not in allowed
                else overrides.top_p
            ),
            temperature=(
                current.temperature
                if overrides.temperature is None or "temperature" not in allowed
                else overrides.temperature
            ),
            stop_sequences=(
                current.stop_sequences
                if (overrides.stop_sequences is None or "stop_sequences" not in allowed)
                else overrides.stop_sequences
            ),
        )
        _ensure_supported_model(provider, effective.model)
        return effective

    def to_storage(self) -> dict[str, object]:
        values: dict[str, object] = {"model": self.model.value}
        if self.max_tokens is not None:
            values["max_tokens"] = self.max_tokens
        if self.top_k is not None:
            values["top_k"] = self.top_k
        if self.top_p is not None:
            values["top_p"] = self.top_p
        if self.temperature is not None:
            values["temperature"] = self.temperature
        if self.stop_sequences is not None:
            values["stop_sequences"] = list(self.stop_sequences)
        return values


class LLMOverrides(LLMGenerationParameters):
    """Optional per-run settings; an omitted value preserves stored config."""

    model: LLMModels | None = None

    @field_validator("model", mode="before")
    @classmethod
    def _validate_model(cls, value: object) -> LLMModels | None:
        return _optional_model(value)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object] | None) -> "LLMOverrides":
        if values is None:
            return cls()
        data = _validate_mapping(values, name="Overrides")
        _reject_unknown_fields(data, allowed=_COMMON_CONFIG_FIELDS, name="override")
        return cls.model_validate(data)

    def to_storage(self) -> dict[str, object]:
        values: dict[str, object] = {}
        if self.model is not None:
            values["model"] = self.model.value
        if self.max_tokens is not None:
            values["max_tokens"] = self.max_tokens
        if self.top_k is not None:
            values["top_k"] = self.top_k
        if self.top_p is not None:
            values["top_p"] = self.top_p
        if self.temperature is not None:
            values["temperature"] = self.temperature
        if self.stop_sequences is not None:
            values["stop_sequences"] = list(self.stop_sequences)
        return values


class LLMProviderConfig(LLMConfigValue):
    """Provider-validated values; credentials are read-only and never dumped."""

    provider: LLMProviders
    generation: LLMGenerationSettings
    secrets: Mapping[str, str] = Field(repr=False, exclude=True)
    region: str | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def _validate_provider(cls, value: object) -> LLMProviders:
        return _normalize_provider(value)

    @field_validator("secrets", mode="before")
    @classmethod
    def _validate_secret_values(cls, value: object) -> dict[str, str]:
        return _validate_secrets(value)

    @model_validator(mode="after")
    def _validate_provider_policy(self) -> Self:
        _ensure_supported_model(self.provider, self.generation.model)
        if self.provider is LLMProviders.BEDROCK:
            region = _required_non_empty_string(self.region, "region")
            _validate_bedrock_secrets(self.secrets)
            object.__setattr__(self, "region", region)
        else:
            if self.provider not in _API_KEY_PROVIDERS:
                raise InvalidLLMConfig("LLM provider is not supported.")
            if self.region is not None:
                raise InvalidLLMConfig("Region is only valid for Bedrock.")
            _validate_api_key_secrets(self.secrets)
        object.__setattr__(self, "secrets", MappingProxyType(dict(self.secrets)))
        return self

    @classmethod
    def from_storage(
        cls,
        *,
        provider: LLMProviders | str,
        config: Mapping[str, object],
        secrets: Mapping[str, str],
    ) -> "LLMProviderConfig":
        normalized_provider = _normalize_provider(provider)
        config_values = _validate_mapping(config, name="Config")
        allowed_config_fields = _allowed_generation_fields(normalized_provider)
        if normalized_provider is LLMProviders.BEDROCK:
            allowed_config_fields |= _BEDROCK_CONFIG_FIELDS
        _reject_unknown_fields(
            config_values,
            allowed=allowed_config_fields,
            name="config",
        )

        generation = _generation_settings(normalized_provider, config_values)
        if normalized_provider is LLMProviders.BEDROCK:
            region = _required_non_empty_string(config_values.get("region"), "region")
            return cls(
                provider=normalized_provider,
                generation=generation,
                secrets=secrets,
                region=region,
            )

        return cls(
            provider=normalized_provider,
            generation=generation,
            secrets=secrets,
        )

    @property
    def storage_provider(self) -> str:
        return self.provider.value.lower()

    def config_for_storage(self) -> dict[str, object]:
        values = self.generation.to_storage()
        if self.provider is LLMProviders.BEDROCK:
            values["region"] = self.region
        return values


class ResolvedLLM(LLMProviderConfig):
    """Detached provider material and explicit revision/authority for one run."""

    provider_config_id: UUID
    provider_config_revision: int = Field(ge=1)
    organization_id: UUID
    configured: bool
    verified: bool
    ready: bool
    granted: bool

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        provider_config_revision: int,
        organization_id: UUID,
        provider_config: LLMProviderConfig,
        configured: bool,
        verified: bool,
        ready: bool,
        granted: bool,
        overrides: LLMOverrides | None = None,
    ) -> "ResolvedLLM":
        provider_config = LLMProviderConfig.model_validate(provider_config)
        effective_generation = provider_config.generation.apply(
            provider=provider_config.provider,
            overrides=overrides or LLMOverrides(),
        )
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            organization_id=organization_id,
            provider=provider_config.provider,
            generation=effective_generation,
            secrets=provider_config.secrets,
            configured=configured,
            verified=verified,
            ready=ready,
            granted=granted,
            region=provider_config.region,
        )

    def secret(self, name: str) -> str | None:
        return self.secrets.get(name)


class ResolvePinnedLLM(Protocol):
    """Resolve pinned authority into detached values without retaining a session."""

    async def __call__(
        self,
        organization_id: UUID,
        *,
        provider_config_id: UUID,
        revision: int,
        overrides: LLMOverrides | None = None,
    ) -> ResolvedLLM: ...


def _normalize_provider(value: object) -> LLMProviders:
    if isinstance(value, LLMProviders):
        return value
    if not isinstance(value, str):
        raise InvalidLLMConfig("LLM provider is not supported.")
    try:
        return LLMProviders(value.strip().upper())
    except ValueError:
        raise InvalidLLMConfig("LLM provider is not supported.") from None


def _generation_settings(
    provider: LLMProviders,
    values: Mapping[str, object],
) -> LLMGenerationSettings:
    if "model" not in values:
        raise InvalidLLMConfig("Config is missing required field: model.")
    model = _required_model(values["model"])
    _ensure_supported_model(provider, model)
    generation = LLMGenerationSettings.model_validate(
        {key: value for key, value in values.items() if key in _COMMON_CONFIG_FIELDS}
    )
    if provider in _REQUIRED_MAX_TOKENS_PROVIDERS and generation.max_tokens is None:
        raise InvalidLLMConfig("Config is missing required field: max_tokens.")
    return generation


def _allowed_generation_fields(provider: LLMProviders) -> frozenset[str]:
    fields = {"model", "max_tokens", "temperature", "top_p"}
    if provider in _TOP_K_PROVIDERS:
        fields.add("top_k")
    if provider in _STOP_SEQUENCE_PROVIDERS:
        fields.add("stop_sequences")
    return frozenset(fields)


def _required_model(value: object) -> LLMModels:
    if isinstance(value, LLMModels):
        return value
    if not isinstance(value, str):
        raise InvalidLLMConfig("Model is not supported.")
    try:
        return LLMModels(value)
    except ValueError:
        raise InvalidLLMConfig("Model is not supported.") from None


def _optional_model(value: object) -> LLMModels | None:
    return None if value is None else _required_model(value)


def _ensure_supported_model(provider: LLMProviders, model: LLMModels) -> None:
    if not is_model_supported(provider, model):
        raise InvalidLLMConfig("Model is not supported by the selected provider.")


def _validate_mapping(
    values: object,
    *,
    name: str,
) -> dict[str, object]:
    if not isinstance(values, Mapping) or not all(
        isinstance(key, str) for key in values
    ):
        raise InvalidLLMConfig(f"{name} must be a string-keyed mapping.")
    return dict(values)


def _validate_secrets(values: object) -> dict[str, str]:
    data = _validate_mapping(values, name="Secrets")
    if not all(
        isinstance(value, str) and value and value != MASKED_SECRET_VALUE
        for value in data.values()
    ):
        raise InvalidLLMConfig("Secret values must be unmasked non-empty strings.")
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _reject_unknown_fields(
    values: Mapping[str, object],
    *,
    allowed: frozenset[str],
    name: str,
) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise InvalidLLMConfig(f"Unknown {name} fields: {', '.join(unknown)}.")


def _validate_api_key_secrets(secrets: Mapping[str, str]) -> None:
    _reject_unknown_fields(
        secrets,
        allowed=_API_KEY_SECRET_FIELDS,
        name="secret",
    )
    if "api_key" not in secrets:
        raise InvalidLLMConfig("Secrets are missing required field: api_key.")


def _validate_bedrock_secrets(
    secrets: Mapping[str, str],
) -> None:
    _reject_unknown_fields(
        secrets,
        allowed=_BEDROCK_STORED_SECRET_FIELDS,
        name="secret",
    )
    missing = sorted(_BEDROCK_STORED_REQUIRED_SECRET_FIELDS - set(secrets))
    if missing:
        raise InvalidLLMConfig(
            f"Secrets are missing required fields: {', '.join(missing)}."
        )


def _required_non_empty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidLLMConfig(f"{name} must be a non-empty string.")
    return value.strip()
