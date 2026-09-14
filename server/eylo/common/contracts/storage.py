"""Immutable storage authority and object locator contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_serializer,
    field_validator,
)

LocationText = Annotated[str, Field(min_length=1)]


class InvalidStorageLocator(ValueError):
    """A persisted storage authority or key is incomplete or malformed."""


class StorageAuthority(BaseModel):
    """Pinned organization/config identity with an immutable location snapshot."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    location: Mapping[LocationText, LocationText] = Field(min_length=1, repr=False)

    @field_validator("organization_id", "provider_config_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("location", mode="after")
    @classmethod
    def freeze_location(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return MappingProxyType(dict(value))

    @field_serializer("location")
    def serialize_location(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            dict(self.location),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()[:16]

    def locate(self, key: str) -> StorageLocator:
        try:
            return StorageLocator(authority=self, key=key)
        except ValidationError:
            raise InvalidStorageLocator("Storage object locator is invalid.") from None

    def to_dict(self) -> dict[str, JsonValue]:
        return type(self).model_validate(self).model_dump(mode="json")

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> StorageAuthority:
        """Restore the flat persisted shape, including a locator's extra key."""
        try:
            return cls.model_validate({name: value[name] for name in cls.model_fields})
        except (KeyError, TypeError, ValueError):
            raise InvalidStorageLocator("Storage authority is incomplete.") from None


class StorageLocator(BaseModel):
    """An exact key below a validated authority; never a caller-chosen root."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    authority: StorageAuthority
    key: str

    @field_validator("key")
    @classmethod
    def validate_key(cls, key: str) -> str:
        if (
            not key
            or key.startswith("/")
            or "\x00" in key
            or any(part in {".", ".."} for part in key.replace("\\", "/").split("/"))
        ):
            raise InvalidStorageLocator("Storage object key is invalid.")
        return key

    @property
    def uri(self) -> str:
        authority = self.authority
        return (
            f"storage://{authority.provider}/{authority.organization_id}/"
            f"{authority.provider_config_id}@{authority.provider_config_revision}/"
            f"{authority.fingerprint}/{quote(self.key, safe='/')}"
        )

    def to_dict(self) -> dict[str, JsonValue]:
        locator = type(self).model_validate(self)
        return {**locator.authority.to_dict(), "key": locator.key}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> StorageLocator:
        try:
            return cls.model_validate(
                {"authority": StorageAuthority.from_dict(value), "key": value["key"]}
            )
        except (KeyError, TypeError, ValidationError):
            raise InvalidStorageLocator("Storage object key is missing.") from None
