"""Public schemas for ticketing-specific operator audit context."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from eylo.sor.shared.schemas import SorApiModel


class TicketingAuditAvailability(str, Enum):
    """Why one optional ticketing audit surface is or is not populated."""

    AVAILABLE = "AVAILABLE"
    NOT_SELECTED = "NOT_SELECTED"
    UNSUPPORTED = "UNSUPPORTED"


class TicketingIssueCommentResponse(SorApiModel):
    record_id: UUID
    author_external_id: str | None
    author_name: str | None
    text: str
    created_at: datetime
    updated_at: datetime | None
    source_url: str | None


class TicketingIssueAuditResponse(SorApiModel):
    comments_status: TicketingAuditAvailability
    comments_truncated: bool
    comments: tuple[TicketingIssueCommentResponse, ...]
    history_status: TicketingAuditAvailability


__all__ = [
    "TicketingAuditAvailability",
    "TicketingIssueAuditResponse",
    "TicketingIssueCommentResponse",
]
