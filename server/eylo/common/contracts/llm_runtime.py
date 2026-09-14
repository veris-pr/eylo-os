"""Neutral values required to select and construct an LLM adapter."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol, Self, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from eylo.common.contracts.llm_catalog import LLMModels, LLMProviders


class LLMConfigError(Exception):
    """Base error for invalid LLM provider configuration."""


class InvalidLLMConfig(LLMConfigError):
    """Raised when LLM config, overrides or secrets violate policy."""


class LLMPromptCaching(StrEnum):
    """Request policy; an adapter applies it only where supported."""

    ENABLED = "enabled"
    DISABLED = "disabled"


_MIN_TOKEN_COUNT = 1
_MIN_SAMPLING_VALUE = 0.0
_MAX_TOP_P = 1.0
_MAX_TEMPERATURE = 2.0


class LLMConfigValue(BaseModel):
    """Revalidated LLM values with safe errors, including for credential holders.

    Unchecked construction/copies do not become valid merely by being instances.
    Structural validation failures must not expose input credentials through a
    Pydantic error; domain validators retain their explicit, value-free errors.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @model_validator(mode="wrap")
    @classmethod
    def _validate_value(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidLLMConfig(
                "LLM configuration contains invalid field values."
            ) from None


class LLMGenerationParameters(LLMConfigValue):
    """Shared scalar constraints for stored generation and per-run overrides."""

    max_tokens: int | None = Field(default=None, ge=_MIN_TOKEN_COUNT)
    top_k: int | None = Field(default=None, ge=_MIN_TOKEN_COUNT)
    top_p: float | None = Field(default=None, ge=_MIN_SAMPLING_VALUE, le=_MAX_TOP_P)
    temperature: float | None = Field(
        default=None, ge=_MIN_SAMPLING_VALUE, le=_MAX_TEMPERATURE
    )
    stop_sequences: tuple[str, ...] | None = None

    @field_validator("max_tokens", "top_k", mode="before")
    @classmethod
    def _validate_token_count(cls, value: object, info: ValidationInfo) -> int | None:
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < _MIN_TOKEN_COUNT
        ):
            raise InvalidLLMConfig(f"{info.field_name} must be a positive integer.")
        return value

    @field_validator("top_p", "temperature", mode="before")
    @classmethod
    def _validate_sampling_value(
        cls, value: object, info: ValidationInfo
    ) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidLLMConfig(f"{info.field_name} must be a number.")
        maximum = _MAX_TOP_P if info.field_name == "top_p" else _MAX_TEMPERATURE
        if not _MIN_SAMPLING_VALUE <= value <= maximum:
            raise InvalidLLMConfig(
                f"{info.field_name} must be between {_MIN_SAMPLING_VALUE} and {maximum}."
            )
        return float(value)

    @field_validator("stop_sequences", mode="before")
    @classmethod
    def _validate_stop_sequences(cls, value: object) -> tuple[str, ...] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) and item for item in value
        ):
            raise InvalidLLMConfig(
                "stop_sequences must be a list of non-empty strings."
            )
        return tuple(value)


class LLMGenerationConfig(LLMGenerationParameters):
    """Concrete neutral generation data; provider/model compatibility is domain policy."""

    model: LLMModels

    @field_validator("model", mode="before")
    @classmethod
    def _validate_model(cls, value: object) -> LLMModels:
        if isinstance(value, LLMModels):
            return value
        if isinstance(value, str):
            try:
                return LLMModels(value)
            except ValueError:
                pass
        raise InvalidLLMConfig("Model is not supported.")


class LLMInferenceConfig(LLMConfigValue):
    """Effective request settings; storage serialization is not a runtime API."""

    generation: LLMGenerationConfig
    prompt_caching: LLMPromptCaching = LLMPromptCaching.DISABLED


@runtime_checkable
class ResolvedLLMConfig(Protocol):
    """Structural resolved-config view required by adapter factories."""

    @property
    def provider(self) -> LLMProviders: ...

    @property
    def secrets(self) -> Mapping[str, str]: ...

    @property
    def region(self) -> str | None: ...

    def secret(self, name: str) -> str | None: ...
