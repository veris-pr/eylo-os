"""Translate validated platform storage values into typed socket configs."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import SecretStr, ValidationError

from eylo.modules.storage_configs.domain import (
    FilesystemStorageSettings,
    InvalidStorageConfig,
    ResolvedStorage,
    S3SessionCredentials,
    S3StaticCredentials,
    S3StorageSettings,
    StorageProviderConfig,
)
from eylo.sockets.storage.schemas import (
    FilesystemStorageConfig,
    S3StorageConfig,
    StorageConfig,
)

FILESYSTEM_ROOT_SETTING = "STORAGE_FILESYSTEM_ROOT"


def build_storage_runtime_config(
    config: StorageProviderConfig | ResolvedStorage,
    *,
    organization_id: UUID,
    provider_config_id: UUID,
    trusted_filesystem_root: Path | None = None,
) -> StorageConfig:
    try:
        config = type(config).model_validate(config)
    except ValidationError:
        raise InvalidStorageConfig("Storage runtime material is invalid.") from None
    _require_matching_scope(
        config,
        organization_id=organization_id,
        provider_config_id=provider_config_id,
    )
    settings = config.settings
    storage_prefix = _storage_prefix(organization_id, provider_config_id)
    try:
        if isinstance(settings, S3StorageSettings) and isinstance(
            config.credentials, S3StaticCredentials
        ):
            return S3StorageConfig(
                bucket=settings.bucket,
                region=settings.region,
                key_prefix=storage_prefix,
                access_key_id=SecretStr(config.credentials.access_key_id),
                secret_access_key=SecretStr(config.credentials.secret_access_key),
                session_token=(
                    SecretStr(config.credentials.session_token)
                    if isinstance(config.credentials, S3SessionCredentials)
                    else None
                ),
            )
        if isinstance(settings, FilesystemStorageSettings):
            platform_root = (
                trusted_filesystem_root or _configured_filesystem_root()
            ).resolve()
            namespace_root = (
                platform_root / settings.namespace / Path(storage_prefix)
            ).resolve()
            if not namespace_root.is_relative_to(platform_root):
                raise InvalidStorageConfig(
                    "Filesystem namespace escapes the trusted storage root."
                )
            return FilesystemStorageConfig(root=namespace_root)
    except ValidationError:
        raise InvalidStorageConfig(
            f"Invalid runtime config for {config.provider.value}."
        ) from None
    raise InvalidStorageConfig(f"Unsupported storage provider: {config.provider}")


def _storage_prefix(organization_id: UUID, provider_config_id: UUID) -> str:
    return f"organizations/{organization_id}/storage-configs/{provider_config_id}"


def _require_matching_scope(
    config: StorageProviderConfig | ResolvedStorage,
    *,
    organization_id: UUID,
    provider_config_id: UUID,
) -> None:
    if not isinstance(config, ResolvedStorage):
        return
    if (
        config.organization_id != organization_id
        or config.provider_config_id != provider_config_id
    ):
        raise InvalidStorageConfig(
            "Resolved storage config does not match the requested authority."
        )


def _configured_filesystem_root() -> Path:
    from eylo.common.config import settings

    raw = settings.STORAGE_FILESYSTEM_ROOT
    if not raw:
        raise InvalidStorageConfig(
            f"filesystem storage requires operator setting {FILESYSTEM_ROOT_SETTING}."
        )
    root = Path(raw).expanduser()
    if not root.is_absolute() or root == Path(root.anchor):
        raise InvalidStorageConfig(
            f"{FILESYSTEM_ROOT_SETTING} must be a scoped absolute path."
        )
    return root.resolve()
