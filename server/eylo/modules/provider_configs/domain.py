"""Validate and represent revisioned provider configurations."""

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Self
from uuid import UUID

import uuid_utils
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    TypeAdapter,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from eylo.common.contracts.provider_config import Capability, ProviderConfigError
from eylo.modules.provider_configs.masking import apply_secret_patch

_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_JSON_OBJECT = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


class InvalidProviderConfig(ProviderConfigError):
    """Raised when a provider configuration violates a domain invariant."""


class ProviderConfigNotFound(ProviderConfigError):
    """Raised when an active provider configuration is unavailable in an org."""


class ProviderConfigConflict(ProviderConfigError):
    """Raised when a provider configuration violates an active uniqueness rule."""


class ProviderConfigRevisionConflict(ProviderConfigConflict):
    """Raised when a stale operation targets a superseded config revision."""


class _ProviderConfigValue(BaseModel):
    """Validate shared material without importing capability or vendor schemas.

    Secrets stay private during serialization. Mapping bindings are read-only;
    nested JSON values are copied on validation, not recursively frozen.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
        validate_default=True,
    )

    capability: Capability
    provider: str
    secrets: Mapping[str, str] = Field(repr=False, exclude=True)
    verification_metadata: Mapping[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _validate_fields(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidProviderConfig(
                "Provider configuration contains invalid field values."
            ) from None

    @field_validator("capability", mode="before")
    @classmethod
    def _capability(cls, value: object) -> Capability:
        if not isinstance(value, (Capability, str)):
            raise InvalidProviderConfig("Capability is not supported.")
        return _validate_capability(value)

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: str) -> str:
        return _normalize_provider(value)

    @field_validator("secrets")
    @classmethod
    def _secrets(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(_validate_secrets(value))

    @field_validator("verification_metadata")
    @classmethod
    def _metadata(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType(_JSON_OBJECT.validate_python(dict(value)))

    @field_serializer("verification_metadata")
    def _serialize_metadata(
        self, value: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return dict(value)


class EffectiveProviderConfig(_ProviderConfigValue):
    """Validated provider snapshot resolved for one explicit capability use."""

    organization_id: UUID
    provider_config_id: UUID
    revision: int = Field(ge=1)
    settings: Mapping[str, JsonValue]
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @field_validator("settings")
    @classmethod
    def _settings(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType(_JSON_OBJECT.validate_python(dict(value)))

    @field_serializer("settings")
    def _serialize_settings(
        self, value: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return dict(value)


class ProviderConfig(_ProviderConfigValue):
    """Provider configuration aggregate with plaintext secrets held in memory only."""

    id: UUID
    organization_id: UUID
    name: str
    config: Mapping[str, JsonValue]
    deleted: bool = False
    revision: int = Field(default=1, ge=1)
    current_revision: int | None = Field(default=None, ge=1)
    enabled: bool = True
    verified_at: datetime | None = None
    credentials_available: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: str) -> str:
        return _normalize_name(value)

    @field_validator("config")
    @classmethod
    def _config(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType(_JSON_OBJECT.validate_python(dict(value)))

    @field_serializer("config")
    def _serialize_config(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        return dict(value)

    @field_validator("verified_at")
    @classmethod
    def _verified_at(cls, value: datetime | None) -> datetime | None:
        return _validate_verified_at(value)

    @model_validator(mode="after")
    def _selected_revision(self) -> Self:
        current_revision = (
            self.revision if self.current_revision is None else self.current_revision
        )
        if self.revision > current_revision:
            raise InvalidProviderConfig(
                "Selected revision cannot exceed the current revision."
            )
        object.__setattr__(self, "current_revision", current_revision)
        return self

    def _replace(self, **changes: object) -> Self:
        """Revalidate every lifecycle transition, including private credentials."""
        validated = type(self).model_validate(self)
        return type(self).model_validate(
            {**validated.model_dump(), "secrets": validated.secrets, **changes}
        )

    @classmethod
    def create(
        cls,
        *,
        organization_id: UUID,
        capability: Capability | str,
        provider: str,
        name: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> "ProviderConfig":
        return cls.model_validate(
            {
                "id": UUID(str(uuid_utils.uuid7())),
                "organization_id": organization_id,
                "capability": capability,
                "provider": provider,
                "name": name,
                "config": {} if config is None else config,
                "secrets": {} if secrets is None else secrets,
            }
        )

    def update(
        self,
        *,
        name: str | None = None,
        config: Mapping[str, object] | None = None,
        secret_patch: Mapping[str, str | None] | None = None,
    ) -> "ProviderConfig":
        if not self.is_current:
            raise ProviderConfigRevisionConflict(
                "Only the current provider configuration revision can be updated."
            )
        next_revision = self.revision + 1
        return self._replace(
            name=self.name if name is None else name,
            config=self.config if config is None else config,
            secrets=(
                self.secrets
                if secret_patch is None
                else apply_secret_patch(self.secrets, secret_patch)
            ),
            revision=next_revision,
            current_revision=next_revision,
            verified_at=None,
            verification_metadata={},
        )

    def rename(self, name: str) -> "ProviderConfig":
        """Change display metadata without creating an executable revision."""
        if not self.is_current:
            raise ProviderConfigRevisionConflict(
                "Only the current provider configuration revision can be renamed."
            )
        return self._replace(name=name)

    @property
    def configured(self) -> bool:
        return self.credentials_available

    @property
    def verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_current(self) -> bool:
        return self.revision == self.current_revision

    @property
    def ready(self) -> bool:
        return (
            self.configured
            and self.verified
            and self.enabled
            and not self.deleted
            and self.is_current
        )

    def mark_verified(
        self,
        *,
        expected_revision: int,
        verified_at: datetime | None = None,
        verification_metadata: Mapping[str, object] | None = None,
    ) -> "ProviderConfig":
        if _validate_revision(expected_revision) != self.current_revision:
            raise ProviderConfigRevisionConflict(
                "Provider configuration changed during verification."
            )
        if not self.is_current:
            raise ProviderConfigRevisionConflict(
                "Only the current provider configuration revision can be verified."
            )
        return self._replace(
            verified_at=(
                datetime.now(timezone.utc) if verified_at is None else verified_at
            ),
            verification_metadata=(
                {} if verification_metadata is None else verification_metadata
            ),
        )

    def set_enabled(self, enabled: bool) -> "ProviderConfig":
        if not isinstance(enabled, bool):
            raise InvalidProviderConfig("Enabled must be a boolean.")
        return self._replace(enabled=enabled)

    def to_effective(self, *, granted: bool) -> EffectiveProviderConfig:
        if not isinstance(granted, bool):
            raise InvalidProviderConfig("Granted must be a boolean.")
        return EffectiveProviderConfig(
            organization_id=self.organization_id,
            capability=self.capability,
            provider_config_id=self.id,
            revision=self.revision,
            provider=self.provider,
            settings=self.config,
            secrets=self.secrets,
            verification_metadata=self.verification_metadata,
            configured=self.configured,
            verified=self.verified,
            ready=self.ready,
            granted=granted,
        )

    def soft_delete(self) -> "ProviderConfig":
        return self._replace(deleted=True, enabled=False)


def _validate_capability(value: Capability | str) -> Capability:
    try:
        return Capability(value)
    except ValueError as error:
        raise InvalidProviderConfig("Capability is not supported.") from error


def _normalize_provider(value: str) -> str:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if not _PROVIDER_PATTERN.fullmatch(normalized):
        raise InvalidProviderConfig(
            "Provider must be a lowercase machine-readable identifier."
        )
    return normalized


def _normalize_name(value: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidProviderConfig("Name cannot be empty.")
    return normalized


def _validate_secrets(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(secret, str) and secret
        for key, secret in value.items()
    ):
        raise InvalidProviderConfig(
            "Secrets must be a string-keyed mapping of non-empty strings."
        )
    return dict(value)


def _validate_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidProviderConfig("Revision must be a positive integer.")
    return value


def _validate_verified_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise InvalidProviderConfig("Verification time must be timezone-aware.")
    return value
