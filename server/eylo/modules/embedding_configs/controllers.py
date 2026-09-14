"""Embedding config transport controller."""

from __future__ import annotations

from uuid import UUID

from eylo.modules.embedding_configs.domain import (
    EmbeddingVerificationMetadata,
    parse_embedding_provider,
    parse_embedding_settings,
)
from eylo.modules.embedding_configs.schemas import (
    EmbeddingConfigCreate,
    EmbeddingConfigResponse,
    EmbeddingConfigUpdate,
)
from eylo.modules.embedding_configs.service import EmbeddingConfigService
from eylo.modules.provider_configs.domain import ProviderConfig
from eylo.modules.provider_configs.masking import mask_secrets

__all__ = ["EmbeddingConfigController"]


class EmbeddingConfigController:
    def __init__(self, service: EmbeddingConfigService) -> None:
        self._service = service

    async def create(
        self,
        organization_id: UUID,
        request: EmbeddingConfigCreate,
    ) -> EmbeddingConfigResponse:
        config = await self._service.create(
            organization_id=organization_id,
            provider=request.provider,
            name=request.name,
            config=request.config.model_dump(mode="json", exclude_none=True),
            secrets=request.secrets,
        )
        return self._to_response(config)

    async def list(self, organization_id: UUID) -> list[EmbeddingConfigResponse]:
        configs = await self._service.list(organization_id=organization_id)
        return [self._to_response(config) for config in configs]

    async def get(
        self,
        organization_id: UUID,
        config_id: UUID,
    ) -> EmbeddingConfigResponse:
        config = await self._service.get(
            organization_id=organization_id,
            config_id=config_id,
        )
        return self._to_response(config)

    async def update(
        self,
        organization_id: UUID,
        config_id: UUID,
        request: EmbeddingConfigUpdate,
    ) -> EmbeddingConfigResponse:
        config = await self._service.update(
            organization_id=organization_id,
            config_id=config_id,
            name=request.name if "name" in request.model_fields_set else None,
            config=(
                request.config.model_dump(mode="json", exclude_unset=True)
                if request.config is not None
                else None
            ),
            secret_patch=(
                request.secrets if "secrets" in request.model_fields_set else None
            ),
            enabled=(
                request.enabled if "enabled" in request.model_fields_set else None
            ),
        )
        return self._to_response(config)

    async def delete(self, organization_id: UUID, config_id: UUID) -> None:
        await self._service.delete(
            organization_id=organization_id,
            config_id=config_id,
        )

    @staticmethod
    def _to_response(config: ProviderConfig) -> EmbeddingConfigResponse:
        provider = parse_embedding_provider(config.provider)
        metadata = EmbeddingVerificationMetadata.from_record(
            config.verification_metadata
        )
        return EmbeddingConfigResponse(
            id=config.id,
            provider=provider,
            name=config.name,
            revision=config.revision,
            enabled=config.enabled,
            configured=config.configured,
            verified=config.verified,
            ready=config.ready,
            verified_at=config.verified_at,
            dimensions=metadata.dimensions,
            config=parse_embedding_settings(provider, config.config),
            secrets=mask_secrets(config.secrets),
        )
