"""Tenant-scoped document detail projection for the operator audit console."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.knowledge.contracts import KnowledgeSourceFormat
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel, SorSourceModel
from eylo.sor.shared.reads import SorReadNotFoundError
from eylo.sor.shared.repositories import SorRepository

from .models import (
    KnowledgeAttachmentModel,
    KnowledgeAuthorModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeSpaceModel,
    KnowledgeVersionModel,
)

DOCUMENT_BLOCK_LIMIT = 500
DOCUMENT_VERSION_LIMIT = 1
DOCUMENT_PROPERTY_LIMIT = 250
DOCUMENT_ATTACHMENT_LIMIT = 250
BLOCK_TEXT_PREVIEW_CHARS = 4_000
PROPERTY_VALUE_PREVIEW_CHARS = 4_000
VERSION_MESSAGE_PREVIEW_CHARS = 4_000


class KnowledgeDocumentBlockAudit(BaseModel):
    """One ordered block with explicit translation support."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

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


class KnowledgeDocumentVersionAudit(BaseModel):
    """One source-provided version summary without copying its full body."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    external_id: str
    number: str
    author_external_id: str | None
    message: str | None
    message_truncated: bool
    source_format: KnowledgeSourceFormat | None
    created_at: datetime
    source_url: str | None


class KnowledgeDocumentPropertyAudit(BaseModel):
    """One bounded native property preview; full value remains its own record."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    external_id: str
    key: str
    label: str
    value_type: str
    value_preview: str
    value_truncated: bool
    updated_at: datetime | None


class KnowledgeDocumentAttachmentAudit(BaseModel):
    """One source-owned file metadata record."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    external_id: str
    name: str
    media_type: str | None
    size_bytes: int | None
    source_url: str | None
    source_url_expires_at: datetime | None


class KnowledgeDocumentSpaceAudit(BaseModel):
    """Resolved source container for one document."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    external_id: str
    name: str
    kind: str
    source_url: str | None


class KnowledgeDocumentAuthorAudit(BaseModel):
    """Resolved source author for one document."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    external_id: str
    name: str
    primary_email: str | None
    kind: str | None
    avatar_url: str | None


class KnowledgeDocumentAuditContext(BaseModel):
    """Document-owned audit data plus source selection facts for availability."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    source: SkipJsonSchema[InstanceOf[SorSourceModel]] = Field(repr=False, exclude=True)
    selected_entities: frozenset[str]
    blocks_truncated: bool
    blocks: tuple[KnowledgeDocumentBlockAudit, ...]
    versions_truncated: bool
    versions: tuple[KnowledgeDocumentVersionAudit, ...]
    properties_truncated: bool
    properties: tuple[KnowledgeDocumentPropertyAudit, ...]
    attachments_truncated: bool
    attachments: tuple[KnowledgeDocumentAttachmentAudit, ...]
    space: KnowledgeDocumentSpaceAudit | None
    author: KnowledgeDocumentAuthorAudit | None


class KnowledgeDocumentAuditService:
    """Read one document's bounded related projections without widening scope."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def read(
        self,
        *,
        organization_id: UUID,
        record_id: UUID,
    ) -> KnowledgeDocumentAuditContext:
        document_row = await self.session.execute(
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
                SorRecordModel.id == record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.profile == SorProfile.KNOWLEDGE,
                SorRecordModel.canonical_entity_kind == "document",
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                KnowledgeDocumentModel.deleted.is_(False),
            )
        )
        result = document_row.one_or_none()
        if result is None:
            raise SorReadNotFoundError("Document not found.")
        document_record, document = result
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=document_record.source_id,
        )
        if source is None:
            raise SorReadNotFoundError("Document source not found.")
        streams = await self.repository.list_streams(
            organization_id=organization_id,
            source_id=source.id,
        )
        selected_entities = frozenset(
            stream.canonical_entity_kind for stream in streams
        )
        blocks_truncated, blocks = await self._blocks(
            organization_id=organization_id,
            source_id=source.id,
            document_external_id=document_record.vendor_external_id,
            selected="block" in selected_entities,
        )
        versions_truncated, versions = await self._versions(
            organization_id=organization_id,
            source_id=source.id,
            document_external_id=document_record.vendor_external_id,
            current_version=document.version,
            selected="version" in selected_entities,
        )
        properties_truncated, properties = await self._properties(
            organization_id=organization_id,
            source_id=source.id,
            document_external_id=document_record.vendor_external_id,
            selected="property" in selected_entities,
        )
        attachments_truncated, attachments = await self._attachments(
            organization_id=organization_id,
            source_id=source.id,
            document_external_id=document_record.vendor_external_id,
            selected="attachment" in selected_entities,
        )
        space = await self._space(
            organization_id=organization_id,
            source_id=source.id,
            external_id=document.space_external_id,
            selected="space" in selected_entities,
        )
        author = await self._author(
            organization_id=organization_id,
            source_id=source.id,
            external_id=document.author_external_id,
            selected="author" in selected_entities,
        )
        return KnowledgeDocumentAuditContext(
            source=source,
            selected_entities=selected_entities,
            blocks_truncated=blocks_truncated,
            blocks=blocks,
            versions_truncated=versions_truncated,
            versions=versions,
            properties_truncated=properties_truncated,
            properties=properties,
            attachments_truncated=attachments_truncated,
            attachments=attachments,
            space=space,
            author=author,
        )

    async def _blocks(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        document_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[KnowledgeDocumentBlockAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(KnowledgeBlockModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgeBlockModel.record_id,
                        SorRecordModel.source_id == KnowledgeBlockModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgeBlockModel.organization_id,
                    ),
                )
                .where(
                    KnowledgeBlockModel.organization_id == organization_id,
                    KnowledgeBlockModel.source_id == source_id,
                    KnowledgeBlockModel.document_external_id == document_external_id,
                    KnowledgeBlockModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "block",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    KnowledgeBlockModel.position.asc(),
                    SorRecordModel.id.asc(),
                )
                .limit(DOCUMENT_BLOCK_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > DOCUMENT_BLOCK_LIMIT
        audits: list[KnowledgeDocumentBlockAudit] = []
        for block, record in rows[:DOCUMENT_BLOCK_LIMIT]:
            text, text_truncated = _text_preview(
                block.normalized_text,
                BLOCK_TEXT_PREVIEW_CHARS,
            )
            audits.append(
                KnowledgeDocumentBlockAudit(
                    record_id=record.id,
                    external_id=record.vendor_external_id,
                    parent_external_id=block.parent_external_id,
                    kind=block.kind,
                    position=block.position,
                    text=text,
                    text_truncated=text_truncated,
                    supported=block.supported,
                    created_at=block.source_created_at,
                    updated_at=block.source_updated_at,
                )
            )
        return truncated, _order_blocks(audits)

    async def _versions(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        document_external_id: str,
        current_version: str | None,
        selected: bool,
    ) -> tuple[bool, tuple[KnowledgeDocumentVersionAudit, ...]]:
        if not selected or current_version is None:
            return False, ()
        rows = (
            await self.session.execute(
                select(KnowledgeVersionModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgeVersionModel.record_id,
                        SorRecordModel.source_id == KnowledgeVersionModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgeVersionModel.organization_id,
                    ),
                )
                .where(
                    KnowledgeVersionModel.organization_id == organization_id,
                    KnowledgeVersionModel.source_id == source_id,
                    KnowledgeVersionModel.document_external_id == document_external_id,
                    KnowledgeVersionModel.number == current_version,
                    KnowledgeVersionModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "version",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    KnowledgeVersionModel.source_created_at.desc(),
                    SorRecordModel.id.desc(),
                )
                .limit(DOCUMENT_VERSION_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > DOCUMENT_VERSION_LIMIT
        audits: list[KnowledgeDocumentVersionAudit] = []
        for version, record in rows[:DOCUMENT_VERSION_LIMIT]:
            message, message_truncated = _text_preview(
                version.message,
                VERSION_MESSAGE_PREVIEW_CHARS,
            )
            audits.append(
                KnowledgeDocumentVersionAudit(
                    record_id=record.id,
                    external_id=record.vendor_external_id,
                    number=version.number,
                    author_external_id=version.author_external_id,
                    message=message,
                    message_truncated=message_truncated,
                    source_format=(
                        KnowledgeSourceFormat(version.source_format)
                        if version.source_format is not None
                        else None
                    ),
                    created_at=version.source_created_at,
                    source_url=record.source_url,
                )
            )
        return truncated, tuple(audits)

    async def _properties(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        document_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[KnowledgeDocumentPropertyAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(KnowledgePropertyModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgePropertyModel.record_id,
                        SorRecordModel.source_id == KnowledgePropertyModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgePropertyModel.organization_id,
                    ),
                )
                .where(
                    KnowledgePropertyModel.organization_id == organization_id,
                    KnowledgePropertyModel.source_id == source_id,
                    KnowledgePropertyModel.document_external_id == document_external_id,
                    KnowledgePropertyModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "property",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    KnowledgePropertyModel.label.asc(),
                    KnowledgePropertyModel.property_key.asc(),
                    SorRecordModel.id.asc(),
                )
                .limit(DOCUMENT_PROPERTY_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > DOCUMENT_PROPERTY_LIMIT
        audits: list[KnowledgeDocumentPropertyAudit] = []
        for property_value, record in rows[:DOCUMENT_PROPERTY_LIMIT]:
            value_preview, value_truncated = _json_preview(property_value.value)
            audits.append(
                KnowledgeDocumentPropertyAudit(
                    record_id=record.id,
                    external_id=record.vendor_external_id,
                    key=property_value.property_key,
                    label=property_value.label,
                    value_type=property_value.value_type,
                    value_preview=value_preview,
                    value_truncated=value_truncated,
                    updated_at=property_value.source_updated_at,
                )
            )
        return truncated, tuple(audits)

    async def _attachments(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        document_external_id: str,
        selected: bool,
    ) -> tuple[bool, tuple[KnowledgeDocumentAttachmentAudit, ...]]:
        if not selected:
            return False, ()
        rows = (
            await self.session.execute(
                select(KnowledgeAttachmentModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgeAttachmentModel.record_id,
                        SorRecordModel.source_id == KnowledgeAttachmentModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgeAttachmentModel.organization_id,
                    ),
                )
                .where(
                    KnowledgeAttachmentModel.organization_id == organization_id,
                    KnowledgeAttachmentModel.source_id == source_id,
                    KnowledgeAttachmentModel.document_external_id
                    == document_external_id,
                    KnowledgeAttachmentModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "attachment",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    KnowledgeAttachmentModel.name.asc(),
                    SorRecordModel.id.asc(),
                )
                .limit(DOCUMENT_ATTACHMENT_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > DOCUMENT_ATTACHMENT_LIMIT
        return truncated, tuple(
            KnowledgeDocumentAttachmentAudit(
                record_id=record.id,
                external_id=record.vendor_external_id,
                name=attachment.name,
                media_type=attachment.media_type,
                size_bytes=attachment.size_bytes,
                source_url=attachment.source_url,
                source_url_expires_at=attachment.source_url_expires_at,
            )
            for attachment, record in rows[:DOCUMENT_ATTACHMENT_LIMIT]
        )

    async def _space(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        external_id: str | None,
        selected: bool,
    ) -> KnowledgeDocumentSpaceAudit | None:
        if not selected or external_id is None:
            return None
        result = (
            await self.session.execute(
                select(KnowledgeSpaceModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgeSpaceModel.record_id,
                        SorRecordModel.source_id == KnowledgeSpaceModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgeSpaceModel.organization_id,
                    ),
                )
                .where(
                    KnowledgeSpaceModel.organization_id == organization_id,
                    KnowledgeSpaceModel.source_id == source_id,
                    KnowledgeSpaceModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "space",
                    SorRecordModel.vendor_external_id == external_id,
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
            )
        ).one_or_none()
        if result is None:
            return None
        space, record = result
        return KnowledgeDocumentSpaceAudit(
            record_id=record.id,
            external_id=record.vendor_external_id,
            name=space.name,
            kind=space.kind,
            source_url=record.source_url,
        )

    async def _author(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        external_id: str | None,
        selected: bool,
    ) -> KnowledgeDocumentAuthorAudit | None:
        if not selected or external_id is None:
            return None
        result = (
            await self.session.execute(
                select(KnowledgeAuthorModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == KnowledgeAuthorModel.record_id,
                        SorRecordModel.source_id == KnowledgeAuthorModel.source_id,
                        SorRecordModel.organization_id
                        == KnowledgeAuthorModel.organization_id,
                    ),
                )
                .where(
                    KnowledgeAuthorModel.organization_id == organization_id,
                    KnowledgeAuthorModel.source_id == source_id,
                    KnowledgeAuthorModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == "author",
                    SorRecordModel.vendor_external_id == external_id,
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
            )
        ).one_or_none()
        if result is None:
            return None
        author, record = result
        return KnowledgeDocumentAuthorAudit(
            record_id=record.id,
            external_id=record.vendor_external_id,
            name=author.name,
            primary_email=author.primary_email,
            kind=author.kind,
            avatar_url=author.avatar_url,
        )


def _text_preview(value: str | None, maximum: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    return value[:maximum], len(value) > maximum


def _json_preview(value: object) -> tuple[str, bool]:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        rendered[:PROPERTY_VALUE_PREVIEW_CHARS],
        len(rendered) > PROPERTY_VALUE_PREVIEW_CHARS,
    )


def _order_blocks(
    blocks: list[KnowledgeDocumentBlockAudit],
) -> tuple[KnowledgeDocumentBlockAudit, ...]:
    """Return parent-first source order while terminating on malformed cycles."""
    by_external_id = {block.external_id: block for block in blocks}
    children: dict[str | None, list[KnowledgeDocumentBlockAudit]] = {}
    for block in blocks:
        parent = (
            block.parent_external_id
            if block.parent_external_id in by_external_id
            else None
        )
        children.setdefault(parent, []).append(block)
    for siblings in children.values():
        siblings.sort(key=lambda item: (item.position, item.external_id))

    ordered: list[KnowledgeDocumentBlockAudit] = []
    visited: set[str] = set()

    def visit(block: KnowledgeDocumentBlockAudit) -> None:
        if block.external_id in visited:
            return
        visited.add(block.external_id)
        ordered.append(block)
        for child in children.get(block.external_id, ()):
            visit(child)

    for root in children.get(None, ()):
        visit(root)
    for block in sorted(blocks, key=lambda item: (item.position, item.external_id)):
        visit(block)
    return tuple(ordered)


__all__ = [
    "KnowledgeDocumentAttachmentAudit",
    "KnowledgeDocumentAuditContext",
    "KnowledgeDocumentAuditService",
    "KnowledgeDocumentAuthorAudit",
    "KnowledgeDocumentBlockAudit",
    "KnowledgeDocumentPropertyAudit",
    "KnowledgeDocumentSpaceAudit",
    "KnowledgeDocumentVersionAudit",
]
