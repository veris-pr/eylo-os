"""API schemas for organization-owned embedding configs."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import (
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from eylo.common.schemas import EyloBaseApiSchema
from eylo.modules.embedding_configs.catalog import EmbeddingProviders
from eylo.modules.embedding_configs.domain import (
    EmbeddingModelSettings,
    EmbeddingSettings,
    InvalidEmbeddingConfig,
    parse_embedding_provider,
    parse_embedding_settings,
)

__all__ = [
    "EmbeddingConfigCreate",
    "EmbeddingConfigResponse",
    "EmbeddingConfigUpdate",
    "EmbeddingConfigVerificationResponse",
]


class _EmbeddingProviderSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: EmbeddingProviders

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> EmbeddingProviders:
        return parse_embedding_provider(value)


class _EmbeddingMaterialSchema(_EmbeddingProviderSchema):
    """Expose domain fields while keeping provider selection authoritative."""

    config: EmbeddingSettings

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, value: object, info: ValidationInfo) -> EmbeddingSettings:
        provider = info.data.get("provider")
        if not isinstance(provider, EmbeddingProviders):
            raise InvalidEmbeddingConfig("Embedding provider is not supported.")
        return parse_embedding_settings(provider, value)


class EmbeddingConfigCreate(_EmbeddingMaterialSchema):
    name: str = Field(min_length=1)
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


class EmbeddingSettingsUpdate(EmbeddingModelSettings):
    """Known update fields; the service applies the stored provider's full rules."""

    base_url: str | None = None
    region: str | None = None
    dimensions: int | None = None
    normalize: bool | None = None


class EmbeddingConfigUpdate(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1)
    config: EmbeddingSettingsUpdate | None = None
    secrets: dict[str, str | None] | None = Field(default=None, repr=False)
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied.")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        return self


class EmbeddingConfigVerificationResponse(_EmbeddingProviderSchema):
    verified: bool = True
    revision: int = Field(gt=0)
    dimensions: int = Field(gt=0)
    verified_at: datetime


class EmbeddingConfigResponse(_EmbeddingMaterialSchema):
    id: UUID
    name: str
    revision: int = Field(gt=0)
    enabled: bool
    configured: bool
    verified: bool
    ready: bool
    verified_at: datetime | None
    dimensions: int | None
    secrets: dict[str, str]
