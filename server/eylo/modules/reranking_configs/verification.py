"""Reranking verification contracts shared with pipeline composition."""

from __future__ import annotations

from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from eylo.modules.reranking_configs.catalog import RerankingProviders
from eylo.modules.reranking_configs.domain import RerankingProviderConfig


class RerankingVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class RerankingProviderVerification(BaseModel):
    """Observed provider identity, never its credentials."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    provider: RerankingProviders


class RerankingVerificationResult(RerankingProviderVerification):
    """Revision-checked result returned after the verification write commits."""

    revision: int = Field(ge=1)
    verified_at: AwareDatetime


class RerankingProviderVerifier(Protocol):
    async def verify(
        self,
        config: RerankingProviderConfig,
    ) -> RerankingProviderVerification: ...
