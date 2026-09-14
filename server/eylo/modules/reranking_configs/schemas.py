"""API schemas for organization-owned reranking configs."""

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
from eylo.modules.reranking_configs.catalog import RerankingProviders
from eylo.modules.reranking_configs.domain import (
    InvalidRerankingConfig,
    RerankingModelSettings,
    RerankingSettings,
    parse_reranking_provider,
    parse_reranking_settings,
)

__all__ = [
    "RerankingConfigCreate",
    "RerankingConfigResponse",
    "RerankingConfigUpdate",
    "RerankingConfigVerificationResponse",
]


class _RerankingProviderSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: RerankingProviders

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> RerankingProviders:
        return parse_reranking_provider(value)


class _RerankingMaterialSchema(_RerankingProviderSchema):
    """Expose domain fields while keeping provider selection authoritative."""

    config: RerankingSettings

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, value: object, info: ValidationInfo) -> RerankingSettings:
        provider = info.data.get("provider")
        if not isinstance(provider, RerankingProviders):
            raise InvalidRerankingConfig("Reranking provider is not supported.")
        return parse_reranking_settings(provider, value)


class RerankingConfigCreate(_RerankingMaterialSchema):
    name: str = Field(min_length=1)
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


class RerankingSettingsUpdate(RerankingModelSettings):
    """Known update fields; the service applies the stored provider's full rules."""

    base_url: str | None = None
    region: str | None = None


class RerankingConfigUpdate(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1)
    config: RerankingSettingsUpdate | None = None
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


class RerankingConfigVerificationResponse(_RerankingProviderSchema):
    verified: bool = True
    revision: int = Field(gt=0)
    verified_at: datetime


class RerankingConfigResponse(_RerankingMaterialSchema):
    id: UUID
    name: str
    revision: int = Field(gt=0)
    enabled: bool
    configured: bool
    verified: bool
    ready: bool
    verified_at: datetime | None
    secrets: dict[str, str]
