"""Typed canonical projection tables for the customer-support profile."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel
from eylo.sor.support.contracts import SupportEntityKind


class SupportTicketModel(SorProfileRecordModel):
    """Queryable support case fields independent of the source vendor."""

    __tablename__ = "sor_support_tickets"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.TICKET,
        ),
        CheckConstraint(
            "normalized_status IS NULL OR normalized_status IN "
            "('NEW', 'OPEN', 'PENDING', 'HOLD', 'RESOLVED', 'CLOSED', 'UNKNOWN')",
            name="ck_sor_support_tickets_normalized_status",
        ),
        CheckConstraint(
            "cardinality(tag_external_ids) <= 256",
            name="ck_sor_support_tickets_tags",
        ),
        Index(
            "ix_sor_support_tickets_source_status",
            "source_id",
            "normalized_status",
        ),
        Index(
            "ix_sor_support_tickets_source_requester",
            "source_id",
            "requester_external_id",
        ),
        Index(
            "ix_sor_support_tickets_source_assignee",
            "source_id",
            "assignee_external_id",
        ),
    )

    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requester_external_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    assignee_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    group_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    inbox_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    native_status: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_status: Mapped[str | None] = mapped_column(String(96), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(96), nullable=True)
    category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(160), nullable=True)
    tag_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sla_state: Mapped[str | None] = mapped_column(String(96), nullable=True)


class SupportCustomerModel(SorProfileRecordModel):
    """Queryable support customer identity without platform-contact ownership."""

    __tablename__ = "sor_support_customers"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.CUSTOMER,
        ),
        Index("ix_sor_support_customers_source_name", "source_id", "name"),
        Index(
            "ix_sor_support_customers_source_email",
            "source_id",
            "primary_email",
        ),
        Index(
            "ix_sor_support_customers_source_company",
            "source_id",
            "company_external_id",
        ),
    )

    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_email: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    primary_phone: Mapped[str | None] = mapped_column(String(320), nullable=True)
    company_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool | None] = mapped_column(nullable=True)


class SupportAgentModel(SorProfileRecordModel):
    """Source-side support Agent used only for assignment and audit."""

    __tablename__ = "sor_support_agents"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.AGENT,
        ),
        Index("ix_sor_support_agents_source_name", "source_id", "name"),
        Index("ix_sor_support_agents_source_active", "source_id", "active"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_email: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    active: Mapped[bool | None] = mapped_column(nullable=True)
    assignable: Mapped[bool | None] = mapped_column(nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class SupportQueueModel(SorProfileRecordModel):
    """Canonical group or team to which a support ticket may be routed."""

    __tablename__ = "sor_support_queues"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.QUEUE,
        ),
        Index("ix_sor_support_queues_source_name", "source_id", "name"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool | None] = mapped_column(nullable=True)


class SupportInboxModel(SorProfileRecordModel):
    """Canonical inbox, brand, or channel container for support tickets."""

    __tablename__ = "sor_support_inboxes"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.INBOX,
        ),
        Index("ix_sor_support_inboxes_source_name", "source_id", "name"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(String(160), nullable=True)
    active: Mapped[bool | None] = mapped_column(nullable=True)


class SupportMessageModel(SorProfileRecordModel):
    """Chronological public reply or private note with immutable visibility."""

    __tablename__ = "sor_support_messages"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.MESSAGE,
        ),
        CheckConstraint(
            "visibility IN ('PUBLIC', 'PRIVATE')",
            name="ck_sor_support_messages_visibility",
        ),
        CheckConstraint(
            "direction IS NULL OR direction IN "
            "('INBOUND', 'OUTBOUND', 'SYSTEM', 'UNKNOWN')",
            name="ck_sor_support_messages_direction",
        ),
        CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_support_messages_source_body",
        ),
        CheckConstraint(
            "cardinality(attachment_external_ids) <= 256",
            name="ck_sor_support_messages_attachments",
        ),
        Index(
            "ix_sor_support_messages_source_ticket_created",
            "source_id",
            "ticket_external_id",
            "source_created_at",
        ),
    )

    ticket_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    author_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_body: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    body_format: Mapped[str | None] = mapped_column(String(96), nullable=True)
    attachment_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SupportTagModel(SorProfileRecordModel):
    """Canonical source tag available for support ticket classification."""

    __tablename__ = "sor_support_tags"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__, profile=SorProfile.SUPPORT, entity_kind=SupportEntityKind.TAG
        ),
        Index("ix_sor_support_tags_source_name", "source_id", "name"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)


class SupportSlaMetricModel(SorProfileRecordModel):
    """Vendor-supplied SLA measurement without fabricated availability."""

    __tablename__ = "sor_support_sla_metrics"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.SLA_METRIC,
        ),
        CheckConstraint(
            "normalized_state IS NULL OR normalized_state IN "
            "('ACTIVE', 'ACHIEVED', 'BREACHED', 'PAUSED', 'UNAVAILABLE', 'UNKNOWN')",
            name="ck_sor_support_sla_metrics_normalized_state",
        ),
        Index(
            "ix_sor_support_sla_metrics_source_ticket",
            "source_id",
            "ticket_external_id",
        ),
    )

    ticket_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    metric: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    native_state: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_state: Mapped[str | None] = mapped_column(String(96), nullable=True)
    target_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    achieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SupportAttachmentModel(SorProfileRecordModel):
    """Bounded support attachment metadata; content remains source-owned."""

    __tablename__ = "sor_support_attachments"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.SUPPORT,
            entity_kind=SupportEntityKind.ATTACHMENT,
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_sor_support_attachments_size_nonnegative",
        ),
        Index(
            "ix_sor_support_attachments_source_ticket",
            "source_id",
            "ticket_external_id",
        ),
        Index(
            "ix_sor_support_attachments_source_message",
            "source_id",
            "message_external_id",
        ),
    )

    ticket_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    message_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(320), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "SupportAgentModel",
    "SupportAttachmentModel",
    "SupportCustomerModel",
    "SupportInboxModel",
    "SupportMessageModel",
    "SupportQueueModel",
    "SupportSlaMetricModel",
    "SupportTagModel",
    "SupportTicketModel",
]
