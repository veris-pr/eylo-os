"""Internal persistence contracts for source-neutral external connections."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eylo.common.schemas import EyloBaseModelSchema

from ..domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)

_VENDOR_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SCOPE = re.compile(r"^[^\s\x00-\x1f\x7f]{1,256}$")


class ExternalConnectionModelSchema(EyloBaseModelSchema):
    """Internal connection state; encrypted credentials never reach API schemas."""

    model_config = ConfigDict(revalidate_instances="always")

    external_id: str | None = None
    organization_id: UUID = Field(strict=True)
    contact_id: UUID | None = None
    owner_kind: ConnectionOwnerKind
    vendor_key: str
    auth_kind: ConnectionAuthKind
    instance_origin: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    credentials: str | None = Field(default=None, exclude=True, repr=False)
    credentials_expires_at: datetime | None = None
    revision: int = Field(ge=1)
    status: ExternalConnectionStatus
    last_refresh_success_at: datetime | None = None
    last_refresh_failure_at: datetime | None = None
    refresh_attempts: int = Field(ge=0)
    last_error_code: str | None = None


class ExternalConnectionInDb(ExternalConnectionModelSchema):
    """Validated external connection loaded from persistence."""


class ExternalConnectionCreateSchema(BaseModel):
    """Create one external account with an already-encrypted credential envelope."""

    id: UUID
    organization_id: UUID
    contact_id: UUID | None = None
    owner_kind: ConnectionOwnerKind
    vendor_key: str
    auth_kind: ConnectionAuthKind
    instance_origin: str | None = Field(default=None, max_length=512)
    granted_scopes: list[str] = Field(default_factory=list)
    credentials: str | None = Field(default=None, repr=False)
    credentials_expires_at: datetime | None = None
    status: ExternalConnectionStatus = ExternalConnectionStatus.INITIATED

    @field_validator("vendor_key")
    @classmethod
    def require_vendor_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _VENDOR_KEY.fullmatch(normalized):
            raise ValueError("vendor_key must be a lowercase machine identifier.")
        return normalized

    @field_validator("granted_scopes")
    @classmethod
    def normalize_scopes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            if not _SCOPE.fullmatch(value):
                raise ValueError("granted_scopes contains an invalid scope.")
            if value not in seen:
                seen.add(value)
                normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def require_consistent_state(self) -> Self:
        if self.owner_kind is ConnectionOwnerKind.CONTACT and self.contact_id is None:
            raise ValueError("CONTACT connections require contact_id.")
        if (
            self.owner_kind is ConnectionOwnerKind.ORGANIZATION
            and self.contact_id is not None
        ):
            raise ValueError("ORGANIZATION connections cannot set contact_id.")
        if self.status is ExternalConnectionStatus.INITIATED and self.credentials:
            raise ValueError("INITIATED connections cannot contain credentials.")
        if (
            self.status is ExternalConnectionStatus.ACTIVE
            and self.auth_kind != ConnectionAuthKind.NO_AUTH
            and not self.credentials
        ):
            raise ValueError("Authenticated ACTIVE connections require credentials.")
        return self


__all__ = [
    "ExternalConnectionCreateSchema",
    "ExternalConnectionInDb",
    "ExternalConnectionModelSchema",
]
