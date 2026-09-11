"""Tenant-scoped authority for reading one document attachment."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel
from eylo.sor.shared.reads import SorReadNotFoundError

from .models import KnowledgeAttachmentModel, KnowledgeDocumentModel


class KnowledgeAttachmentAuthority(BaseModel):
    """Current source identity after document and attachment ownership checks."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    source_id: UUID
    document_external_id: str
    attachment_external_id: str
    attachment_revision: str | None
    declared_media_type: str | None
    declared_size_bytes: int | None


async def read_attachment_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    document_record_id: UUID,
    attachment_record_id: UUID,
) -> KnowledgeAttachmentAuthority:
    """Resolve an attachment only when it belongs to the requested document."""
    document_result = (
        await session.execute(
            select(SorRecordModel, KnowledgeDocumentModel)
            .join(
                KnowledgeDocumentModel,
                and_(
                    KnowledgeDocumentModel.record_id == SorRecordModel.id,
                    KnowledgeDocumentModel.source_id == SorRecordModel.source_id,
                    KnowledgeDocumentModel.organization_id
                    == SorRecordModel.organization_id,
                ),
            )
            .where(
                SorRecordModel.id == document_record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.profile == SorProfile.KNOWLEDGE,
                SorRecordModel.canonical_entity_kind == "document",
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                KnowledgeDocumentModel.deleted.is_(False),
            )
        )
    ).one_or_none()
    if document_result is None:
        raise SorReadNotFoundError("Document attachment not found.")
    document_record, _document = document_result

    attachment_result = (
        await session.execute(
            select(SorRecordModel, KnowledgeAttachmentModel)
            .join(
                KnowledgeAttachmentModel,
                and_(
                    KnowledgeAttachmentModel.record_id == SorRecordModel.id,
                    KnowledgeAttachmentModel.source_id == SorRecordModel.source_id,
                    KnowledgeAttachmentModel.organization_id
                    == SorRecordModel.organization_id,
                ),
            )
            .where(
                SorRecordModel.id == attachment_record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.source_id == document_record.source_id,
                SorRecordModel.profile == SorProfile.KNOWLEDGE,
                SorRecordModel.canonical_entity_kind == "attachment",
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                KnowledgeAttachmentModel.document_external_id
                == document_record.vendor_external_id,
                KnowledgeAttachmentModel.deleted.is_(False),
            )
        )
    ).one_or_none()
    if attachment_result is None:
        raise SorReadNotFoundError("Document attachment not found.")
    attachment_record, attachment = attachment_result
    return KnowledgeAttachmentAuthority(
        source_id=document_record.source_id,
        document_external_id=document_record.vendor_external_id,
        attachment_external_id=attachment_record.vendor_external_id,
        attachment_revision=attachment_record.source_revision,
        declared_media_type=attachment.media_type,
        declared_size_bytes=attachment.size_bytes,
    )


__all__ = ["KnowledgeAttachmentAuthority", "read_attachment_authority"]
