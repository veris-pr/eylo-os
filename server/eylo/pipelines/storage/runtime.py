"""Resolve new or historical storage work without changing its authority."""

from __future__ import annotations

from pathlib import Path
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.storage import StorageAuthority, StorageLocator
from eylo.modules.storage_configs.domain import InvalidStorageConfig, ResolvedStorage
from eylo.modules.storage_configs.wiring import build_storage_config_resolver
from eylo.pipelines.storage.config import build_storage_runtime_config
from eylo.sockets.storage.base import StorageVendorAdapter
from eylo.sockets.storage.factory import StorageFactory
from eylo.sockets.storage.schemas import (
    FilesystemStorageConfig,
    S3StorageConfig,
    StorageConfig,
)


class StorageRuntime(BaseModel):
    """Local adapter handle bound to validated material; never a wire payload."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    resolved: ResolvedStorage = Field(repr=False, exclude=True)
    authority: StorageAuthority
    adapter: StorageVendorAdapter = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def require_matching_authority(self) -> Self:
        _require_matching_authority(self.resolved, self.authority)
        return self

    def locate(self, key: str) -> StorageLocator:
        return self.authority.locate(key)


async def resolve_storage_runtime_for_new(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    db: AsyncSession | None = None,
    trusted_filesystem_root: Path | None = None,
) -> StorageRuntime:
    resolved = await build_storage_config_resolver(db).resolve(
        organization_id,
        provider_config_id=provider_config_id,
    )
    config = build_storage_runtime_config(
        resolved,
        organization_id=organization_id,
        provider_config_id=provider_config_id,
        trusted_filesystem_root=trusted_filesystem_root,
    )
    authority = _authority_from_config(resolved, config)
    return StorageRuntime(
        resolved=resolved,
        authority=authority,
        adapter=StorageFactory(config).get_adapter(),
    )


async def resolve_storage_runtime_pinned(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    revision: int,
    db: AsyncSession | None = None,
    trusted_filesystem_root: Path | None = None,
) -> StorageRuntime:
    resolved = await build_storage_config_resolver(db).resolve_pinned(
        organization_id,
        provider_config_id=provider_config_id,
        revision=revision,
    )
    config = build_storage_runtime_config(
        resolved,
        organization_id=organization_id,
        provider_config_id=provider_config_id,
        trusted_filesystem_root=trusted_filesystem_root,
    )
    return StorageRuntime(
        resolved=resolved,
        authority=_authority_from_config(resolved, config),
        adapter=StorageFactory(config).get_adapter(),
    )


async def resolve_storage_runtime_for_authority(
    authority: StorageAuthority,
    *,
    db: AsyncSession | None = None,
) -> StorageRuntime:
    try:
        authority = StorageAuthority.model_validate(authority)
    except ValidationError:
        raise InvalidStorageConfig("Persisted storage authority is invalid.") from None
    resolved = await build_storage_config_resolver(db).resolve_pinned(
        authority.organization_id,
        provider_config_id=authority.provider_config_id,
        revision=authority.provider_config_revision,
    )
    config = _config_from_authority(resolved, authority)
    return StorageRuntime(
        resolved=resolved,
        authority=authority,
        adapter=StorageFactory(config).get_adapter(),
    )


def _authority_from_config(
    resolved: ResolvedStorage,
    config: StorageConfig,
) -> StorageAuthority:
    return StorageAuthority(
        organization_id=resolved.organization_id,
        provider_config_id=resolved.provider_config_id,
        provider_config_revision=resolved.provider_config_revision,
        provider=resolved.provider.value,
        location=_location_from_config(config),
    )


def _config_from_authority(
    resolved: ResolvedStorage,
    authority: StorageAuthority,
) -> StorageConfig:
    _require_matching_authority(resolved, authority)
    config = build_storage_runtime_config(
        resolved,
        organization_id=authority.organization_id,
        provider_config_id=authority.provider_config_id,
    )
    if dict(authority.location) != _location_from_config(config):
        raise InvalidStorageConfig(
            "Persisted storage authority does not match its pinned config revision."
        )
    return config


def _location_from_config(config: StorageConfig) -> dict[str, str]:
    if isinstance(config, S3StorageConfig):
        return {
            "bucket": config.bucket,
            "region": config.region,
            "key_prefix": config.key_prefix,
        }
    if isinstance(config, FilesystemStorageConfig):
        return {"root": str(config.root)}
    raise InvalidStorageConfig(
        f"Unsupported storage runtime config: {type(config).__name__}"
    )


def _require_matching_authority(
    resolved: ResolvedStorage,
    authority: StorageAuthority,
) -> None:
    if (
        resolved.organization_id != authority.organization_id
        or resolved.provider_config_id != authority.provider_config_id
        or resolved.provider_config_revision != authority.provider_config_revision
        or resolved.provider.value != authority.provider
    ):
        raise InvalidStorageConfig(
            "Persisted storage authority does not match its pinned config revision."
        )
