"""Resolve one explicit, verified embedding revision into a vector space."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.embedding import (
    EmbeddingInput,
    EmbeddingSpace,
)
from eylo.common.contracts.embedding_vectors import EmbeddingVectorBatch
from eylo.modules.embedding_configs.domain import (
    InvalidEmbeddingConfig,
    ResolvedEmbedding,
)
from eylo.modules.embedding_configs.wiring import build_embedding_config_resolver
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.embedding.config import build_embedding_runtime_config
from eylo.sockets.embedding.base import EmbeddingVendorAdapter
from eylo.sockets.embedding.factory import EmbeddingFactory


class EmbeddingRuntime(BaseModel):
    """Adapter plus the immutable coordinate space it is allowed to use."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )

    space: EmbeddingSpace
    adapter: EmbeddingVendorAdapter = Field(repr=False, exclude=True)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._require_space(
            await self.adapter.embed(texts, input_type=EmbeddingInput.DOCUMENT),
            expected_count=len(texts),
        )

    async def embed_query(self, text: str) -> list[float]:
        vectors = self._require_space(
            await self.adapter.embed([text], input_type=EmbeddingInput.QUERY),
            expected_count=1,
        )
        return vectors[0]

    def _require_space(
        self, vectors: object, *, expected_count: int
    ) -> list[list[float]]:
        return EmbeddingVectorBatch.validate_result(
            vectors,
            expected_count=expected_count,
            dimensions=self.space.dimensions,
            vendor=self.space.provider,
        ).root


async def resolve_embedding_runtime(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    db: AsyncSession | None = None,
) -> EmbeddingRuntime:
    """Resolve the current verified revision selected by the caller."""
    resolved = await build_embedding_config_resolver(db).resolve(
        organization_id,
        provider_config_id=provider_config_id,
    )
    return _build_runtime(resolved)


async def resolve_pinned_embedding_runtime(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    provider_config_revision: int,
    db: AsyncSession | None = None,
) -> EmbeddingRuntime:
    """Resolve the exact revision recorded by durable vector work."""
    resolved = await build_embedding_config_resolver(db).resolve_pinned(
        organization_id,
        provider_config_id=provider_config_id,
        revision=provider_config_revision,
    )
    return _build_runtime(resolved)


async def resolve_compatible_embedding_runtime(
    organization_id: UUID,
    *,
    persisted_space: EmbeddingSpace,
    db: AsyncSession | None = None,
) -> EmbeddingRuntime:
    """Prefer current ready credentials, then fall back to recorded execution."""
    if persisted_space.organization_id != organization_id:
        raise InvalidEmbeddingConfig(
            "Embedding space does not belong to the requested organization."
        )

    try:
        current = await resolve_embedding_runtime(
            organization_id,
            provider_config_id=persisted_space.provider_config_id,
            db=db,
        )
    except (InvalidEmbeddingConfig, NotConfiguredError):
        current = None
    if current is not None and current.space.is_compatible_with(persisted_space):
        return current

    pinned = await resolve_pinned_embedding_runtime(
        organization_id,
        provider_config_id=persisted_space.provider_config_id,
        provider_config_revision=persisted_space.provider_config_revision,
        db=db,
    )
    if not pinned.space.is_compatible_with(persisted_space):
        raise InvalidEmbeddingConfig(
            "Recorded embedding execution does not match its semantic space."
        )
    return pinned


def _build_runtime(resolved: ResolvedEmbedding) -> EmbeddingRuntime:
    resolved = ResolvedEmbedding.model_validate(resolved)
    adapter = EmbeddingFactory(
        resolved.provider.value,
        build_embedding_runtime_config(resolved),
    ).get_adapter()
    space = _build_space(resolved, semantic_options=adapter.semantic_options)
    return EmbeddingRuntime(space=space, adapter=adapter)


def _build_space(
    resolved: ResolvedEmbedding,
    *,
    semantic_options: dict[str, JsonValue],
) -> EmbeddingSpace:
    metadata = resolved.verification_metadata
    if metadata.endpoint != resolved.endpoint:
        raise InvalidEmbeddingConfig(
            "Verified embedding endpoint does not match the resolved revision."
        )
    if metadata.model != resolved.model:
        raise InvalidEmbeddingConfig(
            "Verified embedding model does not match the resolved revision."
        )
    return EmbeddingSpace(
        organization_id=resolved.organization_id,
        provider_config_id=resolved.provider_config_id,
        provider_config_revision=resolved.provider_config_revision,
        provider=resolved.provider.value,
        endpoint=resolved.endpoint,
        model=resolved.model,
        dimensions=resolved.dimensions,
        semantic_options=semantic_options,
    )
