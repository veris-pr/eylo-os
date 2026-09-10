"""Block deletion while durable vector authority references a config."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import SQLColumnExpression, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.common.models import EyloOrganizationModel
from eylo.modules.agents.models import AgentRevisionModel, AgentsModel
from eylo.modules.embedding_configs.wiring import build_embedding_config_service
from eylo.modules.knowledgebase.jobs import (
    KnowledgeIngestionJobModel,
    KnowledgeReindexJobModel,
)
from eylo.modules.knowledgebase.models import KnowledgebaseModel
from eylo.modules.memory.models import (
    MemoryChangeModel,
    MemoryFormationJobModel,
    MemoryIndexModel,
    MemoryModel,
    MemoryReconciliationCursorModel,
    MemoryReconciliationJobModel,
    MemoryReindexJobModel,
)
from eylo.modules.provider_configs.constants import Capability
from eylo.pipelines.memory.dependency_references import (
    CombinedProviderConfigReferences,
    MemoryDependencyReferenceLookup,
)

_REFERENCE_COLUMNS: tuple[
    tuple[
        type[EyloOrganizationModel] | type[MemoryChangeModel],
        SQLColumnExpression[UUID] | SQLColumnExpression[UUID | None],
    ],
    ...,
] = (
    (AgentsModel, AgentsModel.file_upload_embedding_provider_config_id),
    (AgentRevisionModel, AgentRevisionModel.file_upload_embedding_provider_config_id),
    (KnowledgebaseModel, KnowledgebaseModel.embedding_provider_config_id),
    (
        KnowledgeIngestionJobModel,
        KnowledgeIngestionJobModel.embedding_provider_config_id,
    ),
    (MemoryModel, MemoryModel.embedding_provider_config_id),
    (MemoryChangeModel, MemoryChangeModel.embedding_provider_config_id),
    (MemoryFormationJobModel, MemoryFormationJobModel.embedding_provider_config_id),
    (
        MemoryReconciliationJobModel,
        MemoryReconciliationJobModel.embedding_provider_config_id,
    ),
    (
        MemoryReconciliationCursorModel,
        MemoryReconciliationCursorModel.embedding_provider_config_id,
    ),
    (MemoryIndexModel, MemoryIndexModel.embedding_provider_config_id),
    (KnowledgebaseModel, KnowledgebaseModel.target_embedding_provider_config_id),
    (MemoryIndexModel, MemoryIndexModel.target_embedding_provider_config_id),
    (
        KnowledgeReindexJobModel,
        KnowledgeReindexJobModel.source_embedding_provider_config_id,
    ),
    (
        KnowledgeReindexJobModel,
        KnowledgeReindexJobModel.target_embedding_provider_config_id,
    ),
    (MemoryReindexJobModel, MemoryReindexJobModel.source_embedding_provider_config_id),
    (MemoryReindexJobModel, MemoryReindexJobModel.target_embedding_provider_config_id),
)


class EmbeddingConfigReferenceLookup:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def has_references(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> bool:
        for model, config_column in _REFERENCE_COLUMNS:
            referenced = await self._db.scalar(
                select(
                    exists().where(
                        model.organization_id == organization_id,
                        config_column == config_id,
                        model.deleted.is_(False),
                    )
                )
            )
            if referenced:
                return True
        return False


class EmbeddingConfigDeletionUseCase:
    async def delete(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> None:
        async with start_transaction() as db:
            references = CombinedProviderConfigReferences(
                EmbeddingConfigReferenceLookup(db),
                MemoryDependencyReferenceLookup(db, Capability.EMBEDDING),
            )
            await build_embedding_config_service(
                db,
                references=references,
            ).delete(
                organization_id=organization_id,
                config_id=config_id,
            )
