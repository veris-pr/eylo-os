"""Fence and purge one organization-owned SOR source aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    SorCommandState,
    SorSourceState,
    SorSourceTransition,
    SorWebhookReceiptState,
    SorWorkState,
)
from .models import (
    SorAgentRevisionSourceGrantModel,
    SorCommandModel,
    SorCustomDatasetModel,
    SorCustomFieldDefinitionModel,
    SorCustomFieldValueModel,
    SorFieldMappingModel,
    SorMappingRevisionModel,
    SorRecordModel,
    SorRecordRelationModel,
    SorRelationIntentModel,
    SorSchemaRevisionModel,
    SorSourceGrantModel,
    SorSourceStreamModel,
    SorSyncGenerationModel,
    SorSyncRunModel,
    SorWebhookReceiptModel,
)
from .services import SorConflictError, SorNotFoundError, SorSourceService


@dataclass(frozen=True, slots=True)
class SorSourceDeletionPlan:
    """Active durable work captured after the source authority fence commits."""

    organization_id: UUID
    source_id: UUID
    external_connection_id: UUID
    connector_id: UUID | None
    sync_run_ids: tuple[UUID, ...]
    webhook_receipt_ids: tuple[UUID, ...]
    command_ids: tuple[UUID, ...]


class SorSourceDeletionService:
    """Own the source lifecycle fence and FK-safe local data purge."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sources = SorSourceService(session)

    async def fence(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> SorSourceDeletionPlan:
        """Disable one source and capture every unfinished bound work row."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        connection = await self.sources.repository.get_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            vendor_key=source.vendor_key,
            for_update=True,
            include_deleted=True,
        )
        if connection is None:
            raise SorNotFoundError("External connection not found.")
        claims = await self.sources.repository.list_sources_for_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
        )
        if any(claim.id != source.id for claim in claims):
            raise SorConflictError(
                "This source shares a connection with another source and cannot "
                "be deleted safely."
            )
        connector = await self.sources.repository.get_connector_for_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            for_update=True,
        )
        if source.state is not SorSourceState.DISABLED:
            source = await self.sources.transition(
                organization_id=organization_id,
                source_id=source_id,
                transition=SorSourceTransition.DISABLE,
            )

        return SorSourceDeletionPlan(
            organization_id=organization_id,
            source_id=source_id,
            external_connection_id=source.external_connection_id,
            connector_id=connector.id if connector is not None else None,
            sync_run_ids=await self._active_ids(
                SorSyncRunModel,
                organization_id=organization_id,
                source_id=source_id,
                states=(
                    SorWorkState.PENDING,
                    SorWorkState.RUNNING,
                    SorWorkState.WAITING,
                ),
            ),
            webhook_receipt_ids=await self._active_ids(
                SorWebhookReceiptModel,
                organization_id=organization_id,
                source_id=source_id,
                states=(
                    SorWebhookReceiptState.PENDING,
                    SorWebhookReceiptState.PROCESSING,
                ),
            ),
            command_ids=await self._active_ids(
                SorCommandModel,
                organization_id=organization_id,
                source_id=source_id,
                states=(SorCommandState.PENDING, SorCommandState.RUNNING),
            ),
        )

    async def purge(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> None:
        """Hard-delete the source-owned local aggregate in FK dependency order."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state is not SorSourceState.DISABLED:
            source = await self.sources.transition(
                organization_id=organization_id,
                source_id=source_id,
                transition=SorSourceTransition.DISABLE,
            )

        source.active_mapping_revision_id = None
        source.active_schema_revision_id = None
        await self.session.flush()

        await self._delete_source_rows(
            SorCommandModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorAgentRevisionSourceGrantModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorSourceGrantModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorWebhookReceiptModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorCustomFieldValueModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorRecordRelationModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorRelationIntentModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorRecordModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorSyncRunModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorSyncGenerationModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorSourceStreamModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorFieldMappingModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorCustomFieldDefinitionModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorCustomDatasetModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorMappingRevisionModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self._delete_source_rows(
            SorSchemaRevisionModel,
            organization_id=organization_id,
            source_id=source_id,
        )
        await self.session.delete(source)
        await self.session.flush()

    async def _active_ids(
        self,
        model: Any,
        *,
        organization_id: UUID,
        source_id: UUID,
        states: tuple[object, ...],
    ) -> tuple[UUID, ...]:
        rows = await self.session.scalars(
            select(model.id)
            .where(
                model.organization_id == organization_id,
                model.source_id == source_id,
                model.state.in_(states),
                model.deleted.is_(False),
            )
            .order_by(model.created_at.asc(), model.id.asc())
        )
        return tuple(rows.all())

    async def _delete_source_rows(
        self,
        model: Any,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> None:
        await self.session.execute(
            delete(model).where(
                model.organization_id == organization_id,
                model.source_id == source_id,
            )
        )


__all__ = ["SorSourceDeletionPlan", "SorSourceDeletionService"]
