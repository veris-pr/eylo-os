"""API schemas for explicit organization-owned memory configs."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from eylo.common.schemas import EyloBaseApiSchema
from eylo.modules.memory_configs.catalog import MemoryProviders
from eylo.modules.memory_configs.domain import MemorySettings, parse_memory_provider

__all__ = [
    "MemoryConfigCreate",
    "MemoryConfigResponse",
    "MemoryConfigUpdate",
    "MemoryConfigVerificationResponse",
]


class _MemoryProviderSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: MemoryProviders

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> MemoryProviders:
        return parse_memory_provider(value)


class MemoryConfigCreate(_MemoryProviderSchema):
    name: str = Field(min_length=1)
    config: MemorySettings
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


class MemoryConfigUpdate(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1)
    config: MemorySettings | None = None
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


class MemoryConfigVerificationResponse(_MemoryProviderSchema):
    verified: bool = True
    revision: int = Field(gt=0)
    verified_at: datetime


class MemoryConfigResponse(_MemoryProviderSchema):
    id: UUID
    name: str
    revision: int = Field(gt=0)
    enabled: bool
    configured: bool
    verified: bool
    ready: bool
    verified_at: datetime | None
    config: MemorySettings
    secrets: dict[str, str]
