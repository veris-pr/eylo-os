"""Typed storage settings, private credentials and resolved organization authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)
from eylo.modules.storage_configs.catalog import StorageProviders

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_REGION_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,4}$")
_NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IP_ADDRESS_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
MAX_BUCKET_LENGTH = 63
MAX_REGION_LENGTH = 64
MAX_NAMESPACE_LENGTH = 128


class S3CredentialMode(StrEnum):
    STATIC = "static"
    SESSION = "session"


class InvalidStorageConfig(InvalidProviderConfig):
    """A storage configuration cannot be used; diagnostics omit secret values."""


def parse_storage_provider(value: object) -> StorageProviders:
    """Keep API and persisted-input provider normalization identical."""
    if not isinstance(value, str):
        raise InvalidStorageConfig("Storage provider must be a string.")
    try:
        return StorageProviders(value.strip().lower())
    except ValueError:
        raise InvalidStorageConfig("Unknown storage provider.") from None


class _StorageValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class S3StorageSettings(_StorageValue):
    """Bucket and region are explicit; the platform builds the deeper namespace."""

    bucket: str
    region: str
    credential_mode: S3CredentialMode

    @field_validator("bucket", mode="before")
    @classmethod
    def validate_bucket(cls, value: object) -> str:
        bucket = _required_string(value, "bucket", maximum=MAX_BUCKET_LENGTH).lower()
        if (
            not _BUCKET_PATTERN.fullmatch(bucket)
            or ".." in bucket
            or _IP_ADDRESS_PATTERN.fullmatch(bucket)
            or bucket.startswith(("xn--", "sthree-", "amzn_s3_demo_"))
            or bucket.endswith("-s3alias")
        ):
            raise InvalidStorageConfig("bucket must be a valid AWS S3 bucket name.")
        return bucket

    @field_validator("region", mode="before")
    @classmethod
    def validate_region(cls, value: object) -> str:
        region = _required_string(value, "region", maximum=MAX_REGION_LENGTH).lower()
        if not _REGION_PATTERN.fullmatch(region):
            raise InvalidStorageConfig("region must be an explicit AWS region name.")
        return region

    @field_validator("credential_mode", mode="before")
    @classmethod
    def validate_mode(cls, value: object) -> S3CredentialMode:
        if not isinstance(value, str):
            raise InvalidStorageConfig("credential_mode must be static or session.")
        try:
            return S3CredentialMode(value)
        except (TypeError, ValueError):
            raise InvalidStorageConfig(
                "credential_mode must be static or session."
            ) from None


class FilesystemStorageSettings(_StorageValue):
    """Only a namespace is operator-configurable, never a final disk path."""

    namespace: str

    @field_validator("namespace", mode="before")
    @classmethod
    def validate_namespace(cls, value: object) -> str:
        namespace = _required_string(value, "namespace", maximum=MAX_NAMESPACE_LENGTH)
        if namespace in {".", ".."} or not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise InvalidStorageConfig(
                "namespace must use only letters, numbers, dot, underscore, or hyphen."
            )
        return namespace


class S3StaticCredentials(_StorageValue):
    """Plaintext is an explicit invocation/persistence projection, not a dump."""

    access_key_id: str = Field(repr=False, exclude=True)
    secret_access_key: str = Field(repr=False, exclude=True)

    @field_validator("access_key_id", "secret_access_key", mode="before")
    @classmethod
    def validate_secret(cls, value: object) -> str:
        return _secret(value)


class S3SessionCredentials(S3StaticCredentials):
    session_token: str = Field(repr=False, exclude=True)

    @field_validator("session_token", mode="before")
    @classmethod
    def validate_token(cls, value: object) -> str:
        return _secret(value)


class FilesystemStorageCredentials(_StorageValue):
    """The local adapter accepts no credential fields."""


class StorageProviderConfig(_StorageValue):
    """Provider-specific material; config/secrets mappings exist only at boundaries."""

    provider: StorageProviders
    settings: S3StorageSettings | FilesystemStorageSettings
    credentials: (
        S3SessionCredentials | S3StaticCredentials | FilesystemStorageCredentials
    ) = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def require_matching_material(self) -> Self:
        if self.provider is StorageProviders.S3:
            if not isinstance(self.settings, S3StorageSettings):
                raise InvalidStorageConfig("S3 storage settings are required.")
            expected = (
                S3SessionCredentials
                if self.settings.credential_mode is S3CredentialMode.SESSION
                else S3StaticCredentials
            )
            if type(self.credentials) is not expected:
                raise InvalidStorageConfig(
                    "S3 credentials do not match credential_mode."
                )
        elif not (
            isinstance(self.settings, FilesystemStorageSettings)
            and isinstance(self.credentials, FilesystemStorageCredentials)
        ):
            raise InvalidStorageConfig(
                "Filesystem settings and empty credentials are required."
            )
        return self

    @classmethod
    def from_input(
        cls,
        *,
        provider: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> StorageProviderConfig:
        selected = parse_storage_provider(provider)
        if config is not None and not isinstance(config, Mapping):
            raise InvalidStorageConfig("Storage config must be a mapping.")
        if secrets is not None and not isinstance(secrets, Mapping):
            raise InvalidStorageConfig("Storage credentials must be a mapping.")
        config_values = {} if config is None else dict(config)
        secret_values = {} if secrets is None else dict(secrets)
        try:
            if selected is StorageProviders.S3:
                settings = S3StorageSettings.model_validate(config_values)
                if settings.credential_mode is S3CredentialMode.SESSION:
                    credentials = S3SessionCredentials.model_validate(secret_values)
                else:
                    credentials = S3StaticCredentials.model_validate(secret_values)
            else:
                settings = FilesystemStorageSettings.model_validate(config_values)
                credentials = FilesystemStorageCredentials.model_validate(secret_values)
            return cls(provider=selected, settings=settings, credentials=credentials)
        except ValidationError as error:
            first = error.errors(include_input=False, include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"]) or "material"
            raise InvalidStorageConfig(
                f"Invalid storage configuration at {location}: {first['msg']}"
            ) from None

    @property
    def config(self) -> Mapping[str, JsonValue]:
        return MappingProxyType(self.settings.model_dump(mode="json"))

    @property
    def secrets(self) -> Mapping[str, str]:
        if isinstance(self.credentials, FilesystemStorageCredentials):
            return MappingProxyType({})
        values = {
            "access_key_id": self.credentials.access_key_id,
            "secret_access_key": self.credentials.secret_access_key,
        }
        if isinstance(self.credentials, S3SessionCredentials):
            values["session_token"] = self.credentials.session_token
        return MappingProxyType(values)


class ResolvedStorage(StorageProviderConfig):
    """Validated material pinned to an exact organization, config and revision."""

    provider_config_id: UUID
    provider_config_revision: int = Field(ge=1)
    organization_id: UUID
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedStorage:
        try:
            effective = EffectiveProviderConfig.model_validate(provider_config)
        except (ValidationError, InvalidProviderConfig):
            raise InvalidStorageConfig(
                "Resolved storage configuration is invalid."
            ) from None
        if (
            effective.organization_id != organization_id
            or effective.provider_config_id != provider_config_id
            or effective.capability is not Capability.STORAGE
        ):
            raise InvalidStorageConfig(
                "Resolved storage authority does not match the requested organization/config."
            )
        material = StorageProviderConfig.from_input(
            provider=effective.provider,
            config=effective.settings,
            secrets=effective.secrets,
        )
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=effective.revision,
            organization_id=organization_id,
            provider=material.provider,
            settings=material.settings,
            credentials=material.credentials,
            configured=effective.configured,
            verified=effective.verified,
            ready=effective.ready,
            granted=effective.granted,
        )


def _required_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise InvalidStorageConfig(
            f"{field_name} must be a non-empty string of at most {maximum} characters."
        )
    return value.strip()


def _secret(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidStorageConfig("S3 requires non-empty secret fields.")
    return value
