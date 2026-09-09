"""Compose explicit reranking authority with its vendor adapter."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.reranking_configs.domain import (
    InvalidRerankingConfig,
    ResolvedReranking,
)
from eylo.modules.reranking_configs.wiring import build_reranking_config_resolver
from eylo.pipelines.reranking.config import build_reranking_runtime_config
from eylo.sockets.reranking.base import RerankingVendorAdapter
from eylo.sockets.reranking.factory import RerankingFactory


class RerankingRuntime(BaseModel):
    """Validated authority paired with a nonserializable provider resource."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )

    authority: ResolvedReranking
    adapter: RerankingVendorAdapter = Field(repr=False, exclude=True)

    @property
    def provider_config_id(self) -> UUID:
        return self.authority.provider_config_id

    @property
    def provider_config_revision(self) -> int:
        return self.authority.provider_config_revision

    @property
    def provider(self) -> str:
        return self.authority.provider.value


async def resolve_reranker(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    provider_config_revision: int | None = None,
    db: AsyncSession | None = None,
) -> RerankingRuntime:
    """Build exactly the requested current or pinned reranking runtime."""
    resolver = build_reranking_config_resolver(db)
    if provider_config_revision is None:
        resolved = await resolver.resolve(
            organization_id,
            provider_config_id=provider_config_id,
        )
    else:
        resolved = await resolver.resolve_pinned(
            organization_id,
            provider_config_id=provider_config_id,
            revision=provider_config_revision,
        )
    resolved = ResolvedReranking.model_validate(resolved)
    if (
        resolved.organization_id != organization_id
        or resolved.provider_config_id != provider_config_id
        or (
            provider_config_revision is not None
            and resolved.provider_config_revision != provider_config_revision
        )
    ):
        raise InvalidRerankingConfig(
            "Resolved reranking authority does not match the request."
        )
    _validate_verified_authority(resolved)
    adapter = RerankingFactory(
        resolved.provider.value,
        build_reranking_runtime_config(resolved),
    ).get_adapter()
    return RerankingRuntime(authority=resolved, adapter=adapter)


def _validate_verified_authority(resolved: ResolvedReranking) -> None:
    metadata = resolved.verification_metadata
    if metadata.endpoint != resolved.endpoint or metadata.model != resolved.model:
        raise InvalidRerankingConfig(
            "Verified reranking authority does not match its endpoint and model."
        )
