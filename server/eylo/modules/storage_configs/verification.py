"""Storage verification contracts shared with pipeline composition."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from eylo.modules.storage_configs.catalog import StorageProviders
from eylo.modules.storage_configs.domain import StorageProviderConfig


class StorageVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class _VerificationValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class StorageVerificationCapabilities(_VerificationValue):
    """Intrinsic operation support predicates, not a provider lifecycle policy."""

    upload: bool
    list: bool
    download: bool
    delete: bool
    presigned_download: bool

    def to_dict(self) -> dict[str, bool]:
        return self.model_dump()


class StorageProviderVerification(_VerificationValue):
    """The adapter's verified provider identity and operation capabilities."""

    provider: StorageProviders
    capabilities: StorageVerificationCapabilities


class StorageVerificationResult(_VerificationValue):
    """Only the exact revision tested outside the transaction can be verified."""

    provider: StorageProviders
    revision: int = Field(ge=1)
    verified_at: AwareDatetime
    capabilities: StorageVerificationCapabilities


class StorageProviderVerifier(Protocol):
    async def verify(
        self,
        config: StorageProviderConfig,
        *,
        organization_id: UUID,
        provider_config_id: UUID,
    ) -> StorageProviderVerification: ...
