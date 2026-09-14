"""Embedding provider verification contracts shared with pipeline composition."""

from __future__ import annotations

from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from eylo.modules.embedding_configs.catalog import EmbeddingProviders
from eylo.modules.embedding_configs.domain import EmbeddingProviderConfig


class EmbeddingVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class EmbeddingProviderVerification(BaseModel):
    """Observed provider identity and nonempty vector size, never credentials."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    provider: EmbeddingProviders
    dimensions: int = Field(ge=1)


class EmbeddingVerificationResult(EmbeddingProviderVerification):
    """Revision-checked result returned after the verification write commits."""

    revision: int = Field(ge=1)
    verified_at: AwareDatetime


class EmbeddingProviderVerifier(Protocol):
    async def verify(
        self,
        config: EmbeddingProviderConfig,
    ) -> EmbeddingProviderVerification: ...
