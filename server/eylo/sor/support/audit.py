"""Tenant-scoped Support ticket projections for the operator audit console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel, SorSourceModel
from eylo.sor.shared.reads import SorReadNotFoundError, resolve_reference_labels
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.support.models import (
    SupportAttachmentModel,
    SupportMessageModel,
    SupportSlaMetricModel,
    SupportTicketModel,
)

SUPPORT_TICKET_MESSAGE_LIMIT = 500
SUPPORT_TICKET_ATTACHMENT_LIMIT = 250
SUPPORT_TICKET_SLA_METRIC_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SupportTicketMessageAudit:
    """One bounded public reply or private note in source chronology."""

    record_id: UUID
    external_id: str
    visibility: str
    direction: str | None
    author_external_id: str | None
    author_name: str | None
    text: str
    body_format: str | None
    attachment_external_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None
    source_url: str | None


@dataclass(frozen=True, slots=True)
class SupportTicketAttachmentAudit:
    """One bounded source-owned attachment metadata record."""

    record_id: UUID
    external_id: str
    message_external_id: str | None
    name: str
    content_type: str | None
    size_bytes: int | None
    source_url: str | None


@dataclass(frozen=True, slots=True)
class SupportTicketSlaMetricAudit:
    """One source-supplied SLA measurement without inferred values."""

    record_id: UUID
    metric: str
    value: Decimal | None
    unit: str | None
    native_state: str | None
    normalized_state: str | None
    target_at: datetime | None
    achieved_at: datetime | None
    breached_at: datetime | None


@dataclass(frozen=True, slots=True)
class SupportTicketAuditContext:
    """Ticket-owned audit data plus source selection facts for availability."""

    source: SorSourceModel
    selected_entities: frozenset[str]
    messages_truncated: bool
    messages: tuple[SupportTicketMessageAudit, ...]
    attachments_truncated: bool
    attachments: tuple[SupportTicketAttachmentAudit, ...]
    sla_metrics_truncated: bool
    sla_metrics: tuple[SupportTicketSlaMetricAudit, ...]


class SupportTicketAuditService:
    """Read ticket chronology and metadata without widening tenant authority."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def read(
        self,
        *,
        organization_id: UUID,
        record_id: UUID,
    ) -> SupportTicketAuditContext:
        ticket_record = await self.session.scalar(
            select(SorRecordModel)
            .join(
                SupportTicketModel,
                and_(
                    SupportTicketModel.record_id == SorRecordModel.id,
                    SupportTicketModel.source_id == SorRecordModel.source_id,
                    SupportTicketModel.organization_id
                    == SorRecordModel.organization_id,
                ),
            )
            .where(
                SorRecordModel.id == record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.profile == SorProfile.SUPPORT,
                SorRecordModel.canonical_entity_kind == "ticket",
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                SupportTicketModel.deleted.is_(False),
            )
        )
        if ticket_record is None:
            raise SorReadNotFoundError("Support ticket not found.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=ticket_record.source_id,
        )
        if source is None:
            raise SorReadNotFoundError("Support ticket source not found.")
        streams = await self.repository.list_streams(
            organization_id=organization_id,
            source_id=source.id,
        )
        selected_entities = frozenset(
            stream.canonical_entity_kind for stream in streams
        )
        messages_truncated, messages = await self._messages(
            organization_id=organization_id,
            source_id=source.id,
            ticket_external_id=ticket_record.vendor_external_id,
            selected="message" in selected_entities,
        )
        attachments_truncated, attachments = await self._attachments(
            organization_id=organization_id,
            source_id=source.id,
            ticket_external_id=ticket_record.vendor_external_id,
            selected="attachment" in selected_entities,
        )
        sla_metrics_truncated, sla_metrics = await self._sla_metrics(
            organization_id=organization_id,
            source_id=source.id,
            ticket_external_id=ticket_record.vendor_external_id,
            selected="sla_metric" in selected_entities,
        )
        return SupportTicketAuditContext(
            source=source,
            selected_entities=selected_entities,
            messages_truncated=messages_truncated,
            messages=messages,
            attachments_truncated=attachments_truncated,
            attachments=attachments,
            sla_metrics_truncated=sla_metrics_truncated,
            sla_metrics=sla_metrics,
        )

    async def _messages(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        ticket_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[SupportTicketMessageAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(SupportMessageModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == SupportMessageModel.record_id,
                        SorRecordModel.source_id == SupportMessageModel.source_id,
                        SorRecordModel.organization_id
                        == SupportMessageModel.organization_id,
                    ),
                )
                .where(
                    SupportMessageModel.organization_id == organization_id,
                    SupportMessageModel.source_id == source_id,
                    SupportMessageModel.ticket_external_id == ticket_external_id,
                    SupportMessageModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.SUPPORT,
                    SorRecordModel.canonical_entity_kind == "message",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    SupportMessageModel.source_created_at.desc(),
                    SorRecordModel.id.desc(),
                )
                .limit(SUPPORT_TICKET_MESSAGE_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > SUPPORT_TICKET_MESSAGE_LIMIT
        selected_rows = rows[:SUPPORT_TICKET_MESSAGE_LIMIT]
        author_external_ids = tuple(
            message.author_external_id
            for message, _record in selected_rows
            if message.author_external_id is not None
        )
        author_labels = await resolve_reference_labels(
            self.session,
            organization_id=organization_id,
            reference_keys=tuple(
                (source_id, entity, author_external_id)
                for author_external_id in author_external_ids
                for entity in ("agent", "customer")
            ),
        )
        return truncated, tuple(
            SupportTicketMessageAudit(
                record_id=record.id,
                external_id=record.vendor_external_id,
                visibility=message.visibility,
                direction=message.direction,
                author_external_id=message.author_external_id,
                author_name=(
                    author_labels.get(
                        (source_id, "agent", message.author_external_id)
                    )
                    or author_labels.get(
                        (source_id, "customer", message.author_external_id)
                    )
                    if message.author_external_id is not None
                    else None
                ),
                text=message.normalized_text,
                body_format=message.body_format,
                attachment_external_ids=tuple(message.attachment_external_ids),
                created_at=message.source_created_at,
                updated_at=message.source_updated_at,
                source_url=record.source_url,
            )
            for message, record in reversed(selected_rows)
        )

    async def _attachments(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        ticket_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[SupportTicketAttachmentAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(SupportAttachmentModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == SupportAttachmentModel.record_id,
                        SorRecordModel.source_id == SupportAttachmentModel.source_id,
                        SorRecordModel.organization_id
                        == SupportAttachmentModel.organization_id,
                    ),
                )
                .where(
                    SupportAttachmentModel.organization_id == organization_id,
                    SupportAttachmentModel.source_id == source_id,
                    SupportAttachmentModel.ticket_external_id == ticket_external_id,
                    SupportAttachmentModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.SUPPORT,
                    SorRecordModel.canonical_entity_kind == "attachment",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(SupportAttachmentModel.name.asc(), SorRecordModel.id.asc())
                .limit(SUPPORT_TICKET_ATTACHMENT_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > SUPPORT_TICKET_ATTACHMENT_LIMIT
        return truncated, tuple(
            SupportTicketAttachmentAudit(
                record_id=record.id,
                external_id=record.vendor_external_id,
                message_external_id=attachment.message_external_id,
                name=attachment.name,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                source_url=attachment.source_url or record.source_url,
            )
            for attachment, record in rows[:SUPPORT_TICKET_ATTACHMENT_LIMIT]
        )

    async def _sla_metrics(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        ticket_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[SupportTicketSlaMetricAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(SupportSlaMetricModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == SupportSlaMetricModel.record_id,
                        SorRecordModel.source_id == SupportSlaMetricModel.source_id,
                        SorRecordModel.organization_id
                        == SupportSlaMetricModel.organization_id,
                    ),
                )
                .where(
                    SupportSlaMetricModel.organization_id == organization_id,
                    SupportSlaMetricModel.source_id == source_id,
                    SupportSlaMetricModel.ticket_external_id == ticket_external_id,
                    SupportSlaMetricModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.SUPPORT,
                    SorRecordModel.canonical_entity_kind == "sla_metric",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    SupportSlaMetricModel.metric.asc(),
                    SorRecordModel.id.asc(),
                )
                .limit(SUPPORT_TICKET_SLA_METRIC_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > SUPPORT_TICKET_SLA_METRIC_LIMIT
        return truncated, tuple(
            SupportTicketSlaMetricAudit(
                record_id=record.id,
                metric=metric.metric,
                value=metric.value,
                unit=metric.unit,
                native_state=metric.native_state,
                normalized_state=metric.normalized_state,
                target_at=metric.target_at,
                achieved_at=metric.achieved_at,
                breached_at=metric.breached_at,
            )
            for metric, record in rows[:SUPPORT_TICKET_SLA_METRIC_LIMIT]
        )


__all__ = [
    "SupportTicketAttachmentAudit",
    "SupportTicketAuditContext",
    "SupportTicketAuditService",
    "SupportTicketMessageAudit",
    "SupportTicketSlaMetricAudit",
]
