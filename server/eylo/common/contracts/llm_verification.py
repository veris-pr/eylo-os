"""Detached, vendor-neutral input and receipts for an LLM credential probe."""

from collections.abc import Mapping
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.common.contracts.llm_catalog import LLMModels, LLMProviders
from eylo.common.contracts.llm_runtime import LLMConfigValue, LLMGenerationConfig


class LLMVerificationError(Exception):
    """A provider probe did not produce a valid verification receipt."""


class LLMVerificationInput(LLMConfigValue):
    """Resolved probe material; no organization lookup or provider selection."""

    provider: LLMProviders
    generation: LLMGenerationConfig
    secrets: Mapping[str, str] = Field(repr=False, exclude=True)
    region: str | None = None

    @field_validator("secrets")
    @classmethod
    def _freeze_secrets(cls, values: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(values))


class LLMProviderVerification(BaseModel):
    """Validated probe selection, without generated content or credentials."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    provider: LLMProviders
    model: LLMModels
