"""Memory verification contracts shared with pipeline composition."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import Field, field_validator

from eylo.common.contracts.embedding import EmbeddingSpace
from eylo.modules.llm_configs.domain import ResolvedLLM
from eylo.modules.memory_configs.catalog import MemoryProviders
from eylo.modules.memory_configs.domain import (
    MemoryConfigValue,
    MemoryDependencyAuthority,
    MemoryProviderConfig,
    parse_memory_provider,
)

__all__ = [
    "MemoryDependencyAuthority",
    "MemoryEmbeddingRuntime",
    "MemoryProviderVerifier",
    "MemoryVerificationError",
    "MemoryVerificationResult",
]


class MemoryVerificationError(Exception):
    """The composed memory runtime failed bounded verification."""


class MemoryVerificationResult(MemoryConfigValue):
    """Successful verification result, without provider material or live handles."""

    provider: MemoryProviders
    revision: int = Field(gt=0)
    verified_at: datetime

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: object) -> MemoryProviders:
        return parse_memory_provider(value)


class MemoryEmbeddingRuntime(Protocol):
    """Embedding operations and their verified coordinate space, without SDK types."""

    @property
    def space(self) -> EmbeddingSpace: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class MemoryProviderVerifier(Protocol):
    async def verify(
        self,
        *,
        organization_id: UUID,
        memory_config_id: UUID,
        memory_config_revision: int,
        config: MemoryProviderConfig,
        authority: MemoryDependencyAuthority,
        embedding_runtime: MemoryEmbeddingRuntime,
        llm_runtime: ResolvedLLM,
    ) -> None: ...
