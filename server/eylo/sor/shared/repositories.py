"""Organization-scoped persistence access for the shared SOR domain."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.connections.models import ExternalConnectionModel

from .contracts import SorWorkState
from .models import (
    SorAgentRevisionSourceGrantModel,
    SorCommandModel,
    SorConnectorModel,
    SorCustomDatasetModel,
    SorCustomFieldDefinitionModel,
    SorFieldMappingModel,
    SorMappingRevisionModel,
    SorRecordModel,
    SorSchemaRevisionModel,
    SorSourceGrantModel,
    SorSourceModel,
    SorSourceStreamModel,
    SorSyncRunModel,
    SorWebhookReceiptModel,
)


class SorRepository:
    """Keep every shared SOR lookup tenant- and source-scoped by construction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_connector(
        self,
        *,
        organization_id: UUID,
        connector_id: UUID,
        for_update: bool = False,
    ) -> SorConnectorModel | None:
        query = select(SorConnectorModel).where(
            SorConnectorModel.organization_id == organization_id,
            SorConnectorModel.id == connector_id,
            SorConnectorModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_connector_for_connection(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        for_update: bool = False,
    ) -> SorConnectorModel | None:
        query = select(SorConnectorModel).where(
            SorConnectorModel.organization_id == organization_id,
            SorConnectorModel.external_connection_id == connection_id,
            SorConnectorModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_connectors(
        self,
        *,
        organization_id: UUID,
    ) -> list[SorConnectorModel]:
        rows = await self.session.scalars(
            select(SorConnectorModel)
            .where(
                SorConnectorModel.organization_id == organization_id,
                SorConnectorModel.deleted.is_(False),
            )
            .order_by(SorConnectorModel.name.asc(), SorConnectorModel.id.asc())
        )
        return list(rows.all())

    async def get_source(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> SorSourceModel | None:
        query = select(SorSourceModel).where(
            SorSourceModel.organization_id == organization_id,
            SorSourceModel.id == source_id,
            SorSourceModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_custom_dataset(
        self,
        *,
        organization_id: UUID,
        dataset_id: UUID,
    ) -> SorCustomDatasetModel | None:
        return await self.session.scalar(
            select(SorCustomDatasetModel).where(
                SorCustomDatasetModel.organization_id == organization_id,
                SorCustomDatasetModel.id == dataset_id,
                SorCustomDatasetModel.deleted.is_(False),
            )
        )

    async def get_custom_dataset_by_object(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        for_update: bool = False,
    ) -> SorCustomDatasetModel | None:
        query = select(SorCustomDatasetModel).where(
            SorCustomDatasetModel.organization_id == organization_id,
            SorCustomDatasetModel.source_id == source_id,
            SorCustomDatasetModel.vendor_object_key == vendor_object_key,
            SorCustomDatasetModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_custom_datasets(
        self,
        *,
        organization_id: UUID,
    ) -> list[SorCustomDatasetModel]:
        rows = await self.session.scalars(
            select(SorCustomDatasetModel)
            .where(
                SorCustomDatasetModel.organization_id == organization_id,
                SorCustomDatasetModel.deleted.is_(False),
            )
            .order_by(
                SorCustomDatasetModel.label.asc(),
                SorCustomDatasetModel.id.asc(),
            )
        )
        return list(rows.all())

    async def list_sources(
        self,
        *,
        organization_id: UUID,
    ) -> list[SorSourceModel]:
        rows = await self.session.scalars(
            select(SorSourceModel)
            .where(
                SorSourceModel.organization_id == organization_id,
                SorSourceModel.deleted.is_(False),
            )
            .order_by(SorSourceModel.name.asc(), SorSourceModel.id.asc())
        )
        return list(rows.all())

    async def get_source_by_webhook_token_hash(
        self,
        *,
        token_hash: str,
        for_update: bool = False,
    ) -> SorSourceModel | None:
        query = select(SorSourceModel).where(
            SorSourceModel.webhook_endpoint_token_hash == token_hash,
            SorSourceModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_connection(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        vendor_key: str,
        for_update: bool = False,
    ) -> ExternalConnectionModel | None:
        query = select(ExternalConnectionModel).where(
            ExternalConnectionModel.organization_id == organization_id,
            ExternalConnectionModel.id == connection_id,
            ExternalConnectionModel.vendor_key == vendor_key,
            ExternalConnectionModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_schema_revision(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        schema_revision_id: UUID,
        for_update: bool = False,
    ) -> SorSchemaRevisionModel | None:
        query = select(SorSchemaRevisionModel).where(
            SorSchemaRevisionModel.organization_id == organization_id,
            SorSchemaRevisionModel.source_id == source_id,
            SorSchemaRevisionModel.id == schema_revision_id,
            SorSchemaRevisionModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def latest_schema_revision(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> int:
        value = await self.session.scalar(
            select(func.max(SorSchemaRevisionModel.revision)).where(
                SorSchemaRevisionModel.organization_id == organization_id,
                SorSchemaRevisionModel.source_id == source_id,
                SorSchemaRevisionModel.deleted.is_(False),
            )
        )
        return int(value or 0)

    async def get_mapping_revision(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        mapping_revision_id: UUID,
        for_update: bool = False,
    ) -> SorMappingRevisionModel | None:
        query = select(SorMappingRevisionModel).where(
            SorMappingRevisionModel.organization_id == organization_id,
            SorMappingRevisionModel.source_id == source_id,
            SorMappingRevisionModel.id == mapping_revision_id,
            SorMappingRevisionModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def latest_mapping_revision(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> int:
        value = await self.session.scalar(
            select(func.max(SorMappingRevisionModel.revision)).where(
                SorMappingRevisionModel.organization_id == organization_id,
                SorMappingRevisionModel.source_id == source_id,
                SorMappingRevisionModel.deleted.is_(False),
            )
        )
        return int(value or 0)

    async def list_field_mappings(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        mapping_revision_id: UUID,
    ) -> list[SorFieldMappingModel]:
        rows = await self.session.scalars(
            select(SorFieldMappingModel)
            .where(
                SorFieldMappingModel.organization_id == organization_id,
                SorFieldMappingModel.source_id == source_id,
                SorFieldMappingModel.mapping_revision_id == mapping_revision_id,
                SorFieldMappingModel.deleted.is_(False),
            )
            .order_by(
                SorFieldMappingModel.vendor_object_key.asc(),
                SorFieldMappingModel.vendor_field_key.asc(),
            )
        )
        return list(rows.all())

    async def get_custom_field_definition(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        vendor_field_key: str,
        for_update: bool = False,
    ) -> SorCustomFieldDefinitionModel | None:
        query = select(SorCustomFieldDefinitionModel).where(
            SorCustomFieldDefinitionModel.organization_id == organization_id,
            SorCustomFieldDefinitionModel.source_id == source_id,
            SorCustomFieldDefinitionModel.vendor_object_key == vendor_object_key,
            SorCustomFieldDefinitionModel.vendor_field_key == vendor_field_key,
            SorCustomFieldDefinitionModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_custom_field_definitions(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        definition_ids: Sequence[UUID] | None = None,
    ) -> list[SorCustomFieldDefinitionModel]:
        query = select(SorCustomFieldDefinitionModel).where(
            SorCustomFieldDefinitionModel.organization_id == organization_id,
            SorCustomFieldDefinitionModel.source_id == source_id,
            SorCustomFieldDefinitionModel.deleted.is_(False),
        )
        if definition_ids is not None:
            query = query.where(SorCustomFieldDefinitionModel.id.in_(definition_ids))
        rows = await self.session.scalars(query)
        return list(rows.all())

    async def get_record_by_identity(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        vendor_external_id: str,
        for_update: bool = False,
    ) -> SorRecordModel | None:
        query = select(SorRecordModel).where(
            SorRecordModel.organization_id == organization_id,
            SorRecordModel.source_id == source_id,
            SorRecordModel.vendor_object_key == vendor_object_key,
            SorRecordModel.vendor_external_id == vendor_external_id,
            SorRecordModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_record(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        for_update: bool = False,
    ) -> SorRecordModel | None:
        query = select(SorRecordModel).where(
            SorRecordModel.organization_id == organization_id,
            SorRecordModel.source_id == source_id,
            SorRecordModel.id == record_id,
            SorRecordModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_stream(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        stream_id: UUID,
        for_update: bool = False,
    ) -> SorSourceStreamModel | None:
        query = select(SorSourceStreamModel).where(
            SorSourceStreamModel.organization_id == organization_id,
            SorSourceStreamModel.source_id == source_id,
            SorSourceStreamModel.id == stream_id,
            SorSourceStreamModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_stream_by_object(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        for_update: bool = False,
    ) -> SorSourceStreamModel | None:
        query = select(SorSourceStreamModel).where(
            SorSourceStreamModel.organization_id == organization_id,
            SorSourceStreamModel.source_id == source_id,
            SorSourceStreamModel.vendor_object_key == vendor_object_key,
            SorSourceStreamModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_streams(
        self,
        *,
        organization_id: UUID,
        source_id: UUID | None = None,
    ) -> list[SorSourceStreamModel]:
        query = select(SorSourceStreamModel).where(
            SorSourceStreamModel.organization_id == organization_id,
            SorSourceStreamModel.deleted.is_(False),
        )
        if source_id is not None:
            query = query.where(SorSourceStreamModel.source_id == source_id)
        rows = await self.session.scalars(
            query.order_by(
                SorSourceStreamModel.source_id.asc(),
                SorSourceStreamModel.vendor_object_key.asc(),
                SorSourceStreamModel.id.asc(),
            )
        )
        return list(rows.all())

    async def get_sync_run(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        for_update: bool = False,
    ) -> SorSyncRunModel | None:
        query = select(SorSyncRunModel).where(
            SorSyncRunModel.organization_id == organization_id,
            SorSyncRunModel.id == run_id,
            SorSyncRunModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_active_sync_run(
        self,
        *,
        organization_id: UUID,
        stream_id: UUID,
        for_update: bool = False,
    ) -> SorSyncRunModel | None:
        query = select(SorSyncRunModel).where(
            SorSyncRunModel.organization_id == organization_id,
            SorSyncRunModel.stream_id == stream_id,
            SorSyncRunModel.state.in_(
                (
                    SorWorkState.PENDING,
                    SorWorkState.RUNNING,
                    SorWorkState.WAITING,
                )
            ),
            SorSyncRunModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_active_source_sync_run(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> SorSyncRunModel | None:
        """Return one unfinished run so source config changes can fail closed."""
        query = (
            select(SorSyncRunModel)
            .where(
                SorSyncRunModel.organization_id == organization_id,
                SorSyncRunModel.source_id == source_id,
                SorSyncRunModel.state.in_(
                    (
                        SorWorkState.PENDING,
                        SorWorkState.RUNNING,
                        SorWorkState.WAITING,
                    )
                ),
                SorSyncRunModel.deleted.is_(False),
            )
            .order_by(SorSyncRunModel.created_at.asc(), SorSyncRunModel.id.asc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_webhook_receipt(
        self,
        *,
        organization_id: UUID,
        receipt_id: UUID,
        for_update: bool = False,
    ) -> SorWebhookReceiptModel | None:
        query = select(SorWebhookReceiptModel).where(
            SorWebhookReceiptModel.organization_id == organization_id,
            SorWebhookReceiptModel.id == receipt_id,
            SorWebhookReceiptModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_webhook_receipt_by_identity(
        self,
        *,
        source_id: UUID,
        vendor_delivery_id: str | None,
        fingerprint: str,
        for_update: bool = False,
    ) -> SorWebhookReceiptModel | None:
        identity = (
            SorWebhookReceiptModel.vendor_delivery_id == vendor_delivery_id
            if vendor_delivery_id is not None
            else SorWebhookReceiptModel.fingerprint == fingerprint
        )
        query = select(SorWebhookReceiptModel).where(
            SorWebhookReceiptModel.source_id == source_id,
            identity,
            SorWebhookReceiptModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_command(
        self,
        *,
        organization_id: UUID,
        command_id: UUID,
        for_update: bool = False,
    ) -> SorCommandModel | None:
        query = select(SorCommandModel).where(
            SorCommandModel.organization_id == organization_id,
            SorCommandModel.id == command_id,
            SorCommandModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_command_by_idempotency(
        self,
        *,
        organization_id: UUID,
        idempotency_key: str,
        for_update: bool = False,
    ) -> SorCommandModel | None:
        query = select(SorCommandModel).where(
            SorCommandModel.organization_id == organization_id,
            SorCommandModel.idempotency_key == idempotency_key,
            SorCommandModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_source_grant(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        grant_id: UUID,
        for_update: bool = False,
    ) -> SorSourceGrantModel | None:
        query = select(SorSourceGrantModel).where(
            SorSourceGrantModel.organization_id == organization_id,
            SorSourceGrantModel.source_id == source_id,
            SorSourceGrantModel.id == grant_id,
            SorSourceGrantModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_live_source_grant(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> SorSourceGrantModel | None:
        """Load the one live Agent/source authority inside its tenant."""
        query = select(SorSourceGrantModel).where(
            SorSourceGrantModel.organization_id == organization_id,
            SorSourceGrantModel.agent_id == agent_id,
            SorSourceGrantModel.source_id == source_id,
            SorSourceGrantModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def list_live_source_grants(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID | None = None,
        source_id: UUID | None = None,
        for_update: bool = False,
    ) -> list[SorSourceGrantModel]:
        """List live grants with optional exact Agent/source constraints."""
        query = select(SorSourceGrantModel).where(
            SorSourceGrantModel.organization_id == organization_id,
            SorSourceGrantModel.deleted.is_(False),
        )
        if agent_id is not None:
            query = query.where(SorSourceGrantModel.agent_id == agent_id)
        if source_id is not None:
            query = query.where(SorSourceGrantModel.source_id == source_id)
        if for_update:
            query = query.with_for_update()
        rows = await self.session.scalars(
            query.order_by(
                SorSourceGrantModel.agent_id.asc(),
                SorSourceGrantModel.source_id.asc(),
                SorSourceGrantModel.id.asc(),
            )
        )
        return list(rows.all())

    async def list_agent_revision_source_grants(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        agent_revision: int,
    ) -> list[SorAgentRevisionSourceGrantModel]:
        """Load immutable source authority copied into one Agent revision."""
        rows = await self.session.scalars(
            select(SorAgentRevisionSourceGrantModel)
            .where(
                SorAgentRevisionSourceGrantModel.organization_id == organization_id,
                SorAgentRevisionSourceGrantModel.agent_id == agent_id,
                SorAgentRevisionSourceGrantModel.agent_revision == agent_revision,
                SorAgentRevisionSourceGrantModel.deleted.is_(False),
            )
            .order_by(
                SorAgentRevisionSourceGrantModel.source_id.asc(),
                SorAgentRevisionSourceGrantModel.id.asc(),
            )
        )
        return list(rows.all())


__all__ = ["SorRepository"]
