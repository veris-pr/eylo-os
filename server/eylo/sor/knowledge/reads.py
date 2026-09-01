"""Explicit Documents field contracts for shared SOR audit queries."""

from __future__ import annotations

from collections.abc import Callable

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import (
    SorProfileRecordModel,
    SorRecordModel,
    SorSourceModel,
)
from eylo.sor.shared.query import SorGridColumnImportance, SorGridColumnKind
from eylo.sor.shared.reads import SorEntityReadSpec, SorReadFieldSpec

from .models import (
    KnowledgeAttachmentModel,
    KnowledgeAuthorModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeSpaceModel,
    KnowledgeVersionModel,
)


def _extension_value(
    name: str,
) -> Callable[[SorRecordModel, SorProfileRecordModel | None, SorSourceModel], object]:
    return lambda _record, extension, _source: (
        getattr(extension, name) if extension is not None else None
    )


def _field(
    *,
    key: str,
    label: str,
    kind: SorGridColumnKind,
    importance: SorGridColumnImportance,
    expression,
    attribute: str,
    default_visible: bool = True,
    filterable: bool = True,
    sortable: bool = True,
    groupable: bool = False,
    wraps: bool = False,
    reference_entity: str | None = None,
) -> SorReadFieldSpec:
    return SorReadFieldSpec(
        key=key,
        label=label,
        kind=kind,
        importance=importance,
        expression=expression,
        read_value=_extension_value(attribute),
        default_visible=default_visible,
        filterable=filterable,
        sortable=sortable,
        groupable=groupable,
        wraps=wraps,
        reference_entity=reference_entity,
        value_key=attribute,
    )


KNOWLEDGE_SPACE_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="space",
    model=KnowledgeSpaceModel,
    fields=(
        _field(
            key="name",
            label="Name",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeSpaceModel.name,
            attribute="name",
        ),
        _field(
            key="kind",
            label="Kind",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeSpaceModel.kind,
            attribute="kind",
            groupable=True,
        ),
    ),
)

KNOWLEDGE_DOCUMENT_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="document",
    model=KnowledgeDocumentModel,
    fields=(
        _field(
            key="title",
            label="Title",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeDocumentModel.title,
            attribute="title",
            wraps=True,
        ),
        _field(
            key="lifecycle_state",
            label="State",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeDocumentModel.lifecycle_state,
            attribute="lifecycle_state",
            groupable=True,
        ),
        _field(
            key="space_external_id",
            label="Space",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.space_external_id,
            attribute="space_external_id",
            groupable=True,
            reference_entity="space",
        ),
        _field(
            key="parent_external_id",
            label="Parent",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.parent_external_id,
            attribute="parent_external_id",
            default_visible=False,
            groupable=True,
            reference_entity="document",
        ),
        _field(
            key="source_format",
            label="Format",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.source_format,
            attribute="source_format",
            default_visible=False,
            groupable=True,
        ),
        _field(
            key="version",
            label="Version",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.version,
            attribute="version",
        ),
        _field(
            key="author_external_id",
            label="Author",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.author_external_id,
            attribute="author_external_id",
            default_visible=False,
            groupable=True,
            reference_entity="author",
        ),
        _field(
            key="label_external_ids",
            label="Labels",
            kind=SorGridColumnKind.STRING_ARRAY,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeDocumentModel.label_external_ids,
            attribute="label_external_ids",
            sortable=False,
            wraps=True,
        ),
        _field(
            key="source_created_at",
            label="Created",
            kind=SorGridColumnKind.DATETIME,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeDocumentModel.source_created_at,
            attribute="source_created_at",
            default_visible=False,
        ),
        _field(
            key="normalized_text",
            label="Content",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeDocumentModel.normalized_text,
            attribute="normalized_text",
            default_visible=False,
            wraps=True,
        ),
        _field(
            key="content_hash",
            label="Content hash",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeDocumentModel.content_hash,
            attribute="content_hash",
            default_visible=False,
            filterable=False,
        ),
        _field(
            key="unsupported_blocks",
            label="Unsupported blocks",
            kind=SorGridColumnKind.STRING_ARRAY,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeDocumentModel.unsupported_blocks,
            attribute="unsupported_blocks",
            default_visible=False,
            sortable=False,
            wraps=True,
        ),
    ),
)

KNOWLEDGE_BLOCK_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="block",
    model=KnowledgeBlockModel,
    fields=(
        _field(
            key="document_external_id",
            label="Document",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeBlockModel.document_external_id,
            attribute="document_external_id",
            groupable=True,
            reference_entity="document",
        ),
        _field(
            key="kind",
            label="Kind",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeBlockModel.kind,
            attribute="kind",
            groupable=True,
        ),
        _field(
            key="normalized_text",
            label="Content",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeBlockModel.normalized_text,
            attribute="normalized_text",
            wraps=True,
        ),
        _field(
            key="position",
            label="Order",
            kind=SorGridColumnKind.NUMBER,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeBlockModel.position,
            attribute="position",
        ),
        _field(
            key="parent_external_id",
            label="Parent block",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeBlockModel.parent_external_id,
            attribute="parent_external_id",
            default_visible=False,
            groupable=True,
            reference_entity="block",
        ),
        _field(
            key="supported",
            label="Supported",
            kind=SorGridColumnKind.BOOLEAN,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeBlockModel.supported,
            attribute="supported",
            groupable=True,
        ),
    ),
)

KNOWLEDGE_VERSION_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="version",
    model=KnowledgeVersionModel,
    fields=(
        _field(
            key="document_external_id",
            label="Document",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeVersionModel.document_external_id,
            attribute="document_external_id",
            groupable=True,
            reference_entity="document",
        ),
        _field(
            key="number",
            label="Version",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeVersionModel.number,
            attribute="number",
        ),
        _field(
            key="author_external_id",
            label="Author",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeVersionModel.author_external_id,
            attribute="author_external_id",
            groupable=True,
            reference_entity="author",
        ),
        _field(
            key="message",
            label="Message",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeVersionModel.message,
            attribute="message",
            wraps=True,
        ),
        _field(
            key="source_created_at",
            label="Created",
            kind=SorGridColumnKind.DATETIME,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeVersionModel.source_created_at,
            attribute="source_created_at",
        ),
    ),
)

KNOWLEDGE_PROPERTY_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="property",
    model=KnowledgePropertyModel,
    fields=(
        _field(
            key="label",
            label="Property",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgePropertyModel.label,
            attribute="label",
        ),
        _field(
            key="value",
            label="Value",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgePropertyModel.value,
            attribute="value",
            filterable=False,
            sortable=False,
            wraps=True,
        ),
        _field(
            key="document_external_id",
            label="Document",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgePropertyModel.document_external_id,
            attribute="document_external_id",
            groupable=True,
            reference_entity="document",
        ),
        _field(
            key="key",
            label="Key",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgePropertyModel.property_key,
            attribute="property_key",
            default_visible=False,
        ),
        _field(
            key="value_type",
            label="Value type",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgePropertyModel.value_type,
            attribute="value_type",
            groupable=True,
        ),
    ),
)

KNOWLEDGE_ATTACHMENT_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="attachment",
    model=KnowledgeAttachmentModel,
    fields=(
        _field(
            key="name",
            label="Name",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeAttachmentModel.name,
            attribute="name",
        ),
        _field(
            key="document_external_id",
            label="Document",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeAttachmentModel.document_external_id,
            attribute="document_external_id",
            groupable=True,
            reference_entity="document",
        ),
        _field(
            key="media_type",
            label="Media type",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeAttachmentModel.media_type,
            attribute="media_type",
            groupable=True,
        ),
        _field(
            key="size_bytes",
            label="Size",
            kind=SorGridColumnKind.NUMBER,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeAttachmentModel.size_bytes,
            attribute="size_bytes",
        ),
        _field(
            key="source_url",
            label="Source file",
            kind=SorGridColumnKind.LINK,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeAttachmentModel.source_url,
            attribute="source_url",
            default_visible=False,
        ),
        _field(
            key="source_url_expires_at",
            label="URL expires",
            kind=SorGridColumnKind.DATETIME,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeAttachmentModel.source_url_expires_at,
            attribute="source_url_expires_at",
            default_visible=False,
        ),
    ),
)

KNOWLEDGE_AUTHOR_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.KNOWLEDGE,
    entity="author",
    model=KnowledgeAuthorModel,
    fields=(
        _field(
            key="name",
            label="Name",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeAuthorModel.name,
            attribute="name",
        ),
        _field(
            key="primary_email",
            label="Email",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=KnowledgeAuthorModel.primary_email,
            attribute="primary_email",
        ),
        _field(
            key="kind",
            label="Kind",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=KnowledgeAuthorModel.kind,
            attribute="kind",
            groupable=True,
        ),
        _field(
            key="avatar_url",
            label="Avatar",
            kind=SorGridColumnKind.LINK,
            importance=SorGridColumnImportance.METADATA,
            expression=KnowledgeAuthorModel.avatar_url,
            attribute="avatar_url",
            default_visible=False,
        ),
    ),
)

KNOWLEDGE_READ_SPECS = {
    spec.entity: spec
    for spec in (
        KNOWLEDGE_SPACE_READ_SPEC,
        KNOWLEDGE_DOCUMENT_READ_SPEC,
        KNOWLEDGE_BLOCK_READ_SPEC,
        KNOWLEDGE_VERSION_READ_SPEC,
        KNOWLEDGE_PROPERTY_READ_SPEC,
        KNOWLEDGE_ATTACHMENT_READ_SPEC,
        KNOWLEDGE_AUTHOR_READ_SPEC,
    )
}


__all__ = [
    "KNOWLEDGE_ATTACHMENT_READ_SPEC",
    "KNOWLEDGE_AUTHOR_READ_SPEC",
    "KNOWLEDGE_BLOCK_READ_SPEC",
    "KNOWLEDGE_DOCUMENT_READ_SPEC",
    "KNOWLEDGE_PROPERTY_READ_SPEC",
    "KNOWLEDGE_READ_SPECS",
    "KNOWLEDGE_SPACE_READ_SPEC",
    "KNOWLEDGE_VERSION_READ_SPEC",
]
