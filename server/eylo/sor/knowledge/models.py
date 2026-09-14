"""Typed canonical projection tables for external document systems."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eylo.sor.knowledge.contracts import KnowledgeEntityKind
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel


class KnowledgeSpaceModel(SorProfileRecordModel):
    """Canonical site, workspace, space, or data-source container."""

    __tablename__ = "sor_knowledge_spaces"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.SPACE,
        ),
        Index("ix_sor_knowledge_spaces_source_name", "source_id", "name"),
        Index("ix_sor_knowledge_spaces_source_kind", "source_id", "kind"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(96), nullable=False)


class KnowledgeDocumentModel(SorProfileRecordModel):
    """Canonical source document with normalized and loss-aware source content."""

    __tablename__ = "sor_knowledge_documents"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.DOCUMENT,
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_knowledge_documents_content_hash",
        ),
        CheckConstraint(
            "cardinality(path) <= 128",
            name="ck_sor_knowledge_documents_path",
        ),
        CheckConstraint(
            "cardinality(label_external_ids) <= 256",
            name="ck_sor_knowledge_documents_labels",
        ),
        CheckConstraint(
            "cardinality(unsupported_blocks) <= 128",
            name="ck_sor_knowledge_documents_unsupported_blocks",
        ),
        CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_documents_source_body",
        ),
        Index("ix_sor_knowledge_documents_source_title", "source_id", "title"),
        Index(
            "ix_sor_knowledge_documents_source_space",
            "source_id",
            "space_external_id",
        ),
        Index(
            "ix_sor_knowledge_documents_source_parent",
            "source_id",
            "parent_external_id",
        ),
        Index(
            "ix_sor_knowledge_documents_source_updated",
            "source_id",
            "source_updated_at",
        ),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    space_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parent_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    path: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    source_format: Mapped[str] = mapped_column(String(96), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_body: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(96), nullable=True)
    author_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    label_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    unsupported_blocks: Mapped[list[str]] = mapped_column(
        ARRAY(String(160)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeBlockModel(SorProfileRecordModel):
    """One ordered source block whose unsupported status remains explicit."""

    __tablename__ = "sor_knowledge_blocks"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.BLOCK,
        ),
        CheckConstraint("position >= 0", name="ck_sor_knowledge_blocks_position"),
        CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_blocks_source_body",
        ),
        Index(
            "ix_sor_knowledge_blocks_source_document_position",
            "source_id",
            "document_external_id",
            "position",
        ),
        Index(
            "ix_sor_knowledge_blocks_source_parent",
            "source_id",
            "parent_external_id",
        ),
    )

    document_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    kind: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_body: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    supported: Mapped[bool] = mapped_column(nullable=False)
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeVersionModel(SorProfileRecordModel):
    """One source-provided document revision; no synthetic history."""

    __tablename__ = "sor_knowledge_versions"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.VERSION,
        ),
        CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_versions_source_body",
        ),
        Index(
            "ix_sor_knowledge_versions_source_document_created",
            "source_id",
            "document_external_id",
            "source_created_at",
        ),
    )

    document_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    number: Mapped[str] = mapped_column(String(160), nullable=False)
    author_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_format: Mapped[str | None] = mapped_column(String(96), nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_body: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class KnowledgePropertyModel(SorProfileRecordModel):
    """One source document property retained with its native value type."""

    __tablename__ = "sor_knowledge_properties"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.PROPERTY,
        ),
        CheckConstraint(
            "octet_length(value::text) <= 1048576",
            name="ck_sor_knowledge_properties_value",
        ),
        Index(
            "ix_sor_knowledge_properties_source_document_key",
            "source_id",
            "document_external_id",
            "property_key",
        ),
    )

    document_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    property_key: Mapped[str] = mapped_column(String(512), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeAttachmentModel(SorProfileRecordModel):
    """Document file metadata; content ingestion is deliberately separate."""

    __tablename__ = "sor_knowledge_attachments"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.ATTACHMENT,
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_sor_knowledge_attachments_size",
        ),
        Index(
            "ix_sor_knowledge_attachments_source_document",
            "source_id",
            "document_external_id",
        ),
        Index("ix_sor_knowledge_attachments_source_name", "source_id", "name"),
    )

    document_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(320), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeAuthorModel(SorProfileRecordModel):
    """Source-side author identity used only for document audit and commands."""

    __tablename__ = "sor_knowledge_authors"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.KNOWLEDGE,
            entity_kind=KnowledgeEntityKind.AUTHOR,
        ),
        Index("ix_sor_knowledge_authors_source_name", "source_id", "name"),
        Index(
            "ix_sor_knowledge_authors_source_email",
            "source_id",
            "primary_email",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_email: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(96), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "KnowledgeAttachmentModel",
    "KnowledgeAuthorModel",
    "KnowledgeBlockModel",
    "KnowledgeDocumentModel",
    "KnowledgePropertyModel",
    "KnowledgeSpaceModel",
    "KnowledgeVersionModel",
]
