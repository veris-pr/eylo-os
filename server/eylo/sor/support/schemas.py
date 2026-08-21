"""Public schemas for Support-specific operator audit context."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from eylo.sor.shared.schemas import SorApiModel


class SupportAuditAvailability(str, Enum):
    """Why one optional Support audit surface is or is not populated."""

    AVAILABLE = "AVAILABLE"
    NOT_SELECTED = "NOT_SELECTED"
    UNSUPPORTED = "UNSUPPORTED"


class SupportTicketMessageResponse(SorApiModel):
    record_id: UUID
    external_id: str
    visibility: str
    direction: str | None
    author_external_id: str | None
    text: str
    body_format: str | None
    attachment_external_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None
    source_url: str | None


class SupportTicketAttachmentResponse(SorApiModel):
    record_id: UUID
    external_id: str
    message_external_id: str | None
    name: str
    content_type: str | None
    size_bytes: int | None
    source_url: str | None


class SupportTicketSlaMetricResponse(SorApiModel):
    record_id: UUID
    metric: str
    value: Decimal | None
    unit: str | None
    native_state: str | None
    normalized_state: str | None
    target_at: datetime | None
    achieved_at: datetime | None
    breached_at: datetime | None


class SupportTicketAuditResponse(SorApiModel):
    messages_status: SupportAuditAvailability
    messages_truncated: bool
    messages: tuple[SupportTicketMessageResponse, ...]
    attachments_status: SupportAuditAvailability
    attachments_truncated: bool
    attachments: tuple[SupportTicketAttachmentResponse, ...]
    sla_metrics_status: SupportAuditAvailability
    sla_metrics_truncated: bool
    sla_metrics: tuple[SupportTicketSlaMetricResponse, ...]


__all__ = [
    "SupportAuditAvailability",
    "SupportTicketAttachmentResponse",
    "SupportTicketAuditResponse",
    "SupportTicketMessageResponse",
    "SupportTicketSlaMetricResponse",
]
