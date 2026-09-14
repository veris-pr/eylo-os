"""API schemas for storage configs."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from eylo.common.schemas import EyloBaseApiSchema
from eylo.modules.storage_configs.catalog import StorageProviders
from eylo.modules.storage_configs.domain import (
    FilesystemStorageSettings,
    InvalidStorageConfig,
    S3StorageSettings,
    parse_storage_provider,
)

__all__ = [
    "StorageConfigCreate",
    "StorageConfigResponse",
    "StorageConfigUpdate",
    "StorageConfigVerificationResponse",
]


class StorageCapabilitiesResponse(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid")

    upload: bool
    list: bool
    download: bool
    delete: bool
    presigned_download: bool


class _StorageProviderSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    provider: StorageProviders

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> StorageProviders:
        return parse_storage_provider(value)


class _StorageMaterialSchema(_StorageProviderSchema):
    """Reuse domain settings without changing the public nested config shape."""

    config: S3StorageSettings | FilesystemStorageSettings

    @model_validator(mode="after")
    def validate_provider_settings(self) -> Self:
        expected = (
            S3StorageSettings
            if self.provider is StorageProviders.S3
            else FilesystemStorageSettings
        )
        if not isinstance(self.config, expected):
            raise InvalidStorageConfig("Storage settings do not match the provider.")
        return self


class StorageConfigCreate(_StorageMaterialSchema):
    name: str = Field(min_length=1)
    secrets: dict[str, str] = Field(default_factory=dict, repr=False)


class StorageConfigUpdate(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1)
    config: S3StorageSettings | FilesystemStorageSettings | None = None
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


class StorageConfigVerificationResponse(_StorageProviderSchema):
    verified: bool = True
    revision: int = Field(gt=0)
    verified_at: datetime
    capabilities: StorageCapabilitiesResponse


class StorageConfigResponse(_StorageMaterialSchema):
    id: UUID
    name: str
    revision: int = Field(gt=0)
    enabled: bool
    configured: bool
    verified: bool
    ready: bool
    verified_at: datetime | None
    secrets: dict[str, str]
    capabilities: StorageCapabilitiesResponse
