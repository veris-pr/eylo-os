"""Block storage config deletion while immutable locators still reference it."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.modules.agents.models import AgentRevisionModel
from eylo.modules.knowledgebase.jobs import (
    KnowledgeCorpusImportModel,
    KnowledgeIngestionJobModel,
)
from eylo.modules.storage_configs.wiring import build_storage_config_service
from eylo.modules.voice.models import VoiceConfigModel
from eylo.modules.voice.recording.model import VoiceRecordingModel


class StorageConfigReferenceLookup:
    """Read one non-null EXISTS result per owner; missing results are not absence."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def has_references(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> bool:
        for model in (
            VoiceRecordingModel,
            VoiceConfigModel,
            AgentRevisionModel,
            KnowledgeCorpusImportModel,
            KnowledgeIngestionJobModel,
        ):
            result = await self._db.execute(
                select(
                    exists().where(
                        model.organization_id == organization_id,
                        model.storage_provider_config_id == config_id,
                        model.deleted.is_(False),
                    )
                )
            )
            if result.scalar_one():
                return True
        return False


class StorageConfigDeletionUseCase:
    async def delete(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
    ) -> None:
        async with start_transaction() as db:
            references = StorageConfigReferenceLookup(db)
            await build_storage_config_service(
                db,
                references=references,
            ).delete(
                organization_id=organization_id,
                config_id=config_id,
            )
