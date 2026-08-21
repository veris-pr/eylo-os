"""Public schemas for Documents-specific operator audit context."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from eylo.sor.shared.schemas import SorApiModel


class KnowledgeAuditAvailability(str, Enum):
    """Why one optional Documents audit surface is or is not populated."""

    AVAILABLE = "AVAILABLE"
    NOT_SELECTED = "NOT_SELECTED"
    UNSUPPORTED = "UNSUPPORTED"


class KnowledgeDocumentBlockResponse(SorApiModel):
    record_id: UUID
    external_id: str
    parent_external_id: str | None
    kind: str
    position: int
    text: str | None
    text_truncated: bool
    supported: bool
    created_at: datetime | None
    updated_at: datetime | None


class KnowledgeDocumentVersionResponse(SorApiModel):
    record_id: UUID
    external_id: str
    number: str
    author_external_id: str | None
    message: str | None
    message_truncated: bool
    source_format: str | None
    created_at: datetime
    source_url: str | None


class KnowledgeDocumentPropertyResponse(SorApiModel):
    record_id: UUID
    external_id: str
    key: str
    label: str
    value_type: str
    value_preview: str
    value_truncated: bool
    updated_at: datetime | None


class KnowledgeDocumentAttachmentResponse(SorApiModel):
    record_id: UUID
    external_id: str
    name: str
    media_type: str | None
    size_bytes: int | None
    source_url: str | None
    source_url_expires_at: datetime | None


class KnowledgeDocumentSpaceResponse(SorApiModel):
    record_id: UUID
    external_id: str
    name: str
    kind: str
    source_url: str | None


class KnowledgeDocumentAuthorResponse(SorApiModel):
    record_id: UUID
    external_id: str
    name: str
    primary_email: str | None
    kind: str | None
    avatar_url: str | None


class KnowledgeDocumentAuditResponse(SorApiModel):
    blocks_status: KnowledgeAuditAvailability
    blocks_truncated: bool
    blocks: tuple[KnowledgeDocumentBlockResponse, ...]
    versions_status: KnowledgeAuditAvailability
    versions_truncated: bool
    versions: tuple[KnowledgeDocumentVersionResponse, ...]
    properties_status: KnowledgeAuditAvailability
    properties_truncated: bool
    properties: tuple[KnowledgeDocumentPropertyResponse, ...]
    attachments_status: KnowledgeAuditAvailability
    attachments_truncated: bool
    attachments: tuple[KnowledgeDocumentAttachmentResponse, ...]
    space_status: KnowledgeAuditAvailability
    space: KnowledgeDocumentSpaceResponse | None
    author_status: KnowledgeAuditAvailability
    author: KnowledgeDocumentAuthorResponse | None


__all__ = [
    "KnowledgeAuditAvailability",
    "KnowledgeDocumentAttachmentResponse",
    "KnowledgeDocumentAuditResponse",
    "KnowledgeDocumentAuthorResponse",
    "KnowledgeDocumentBlockResponse",
    "KnowledgeDocumentPropertyResponse",
    "KnowledgeDocumentSpaceResponse",
    "KnowledgeDocumentVersionResponse",
]
