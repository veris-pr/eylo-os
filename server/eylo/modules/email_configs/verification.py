"""Email provider verification contracts shared with pipeline composition."""

from __future__ import annotations

from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from eylo.modules.email_configs.catalog import EmailProviders
from eylo.modules.email_configs.domain import EmailProviderConfig


class EmailVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class EmailProviderVerification(BaseModel):
    """Provider identity only; native authentication details stay in the adapter."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    provider: EmailProviders


class EmailVerificationResult(EmailProviderVerification):
    """Successful verification of an exact stored revision."""

    revision: int = Field(gt=0)
    verified_at: AwareDatetime


class EmailProviderVerifier(Protocol):
    async def verify(
        self,
        config: EmailProviderConfig,
    ) -> EmailProviderVerification: ...
