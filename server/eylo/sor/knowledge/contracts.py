"""Typed external-document records distinct from Eylo Knowledgebases."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from eylo.sor.shared.contracts import (
    SorCanonicalPayload,
    SorCanonicalRecord,
    SorCommandPayload,
    SorExternalRecord,
    SorLifecycleAdapter,
)
from eylo.sor.shared.json_values import SorJsonValue


class KnowledgeBodyRepresentation(str, Enum):
    """Supported source-body representations with specialized console renderers."""

    MARKDOWN = "markdown"
    CONFLUENCE_STORAGE = "storage"


class KnowledgeSourceFormat(str, Enum):
    """Exact source formats currently normalized by executable adapters."""

    CONFLUENCE_STORAGE = "confluence_storage"
    LINEAR_MARKDOWN = "linear_markdown"
    NOTION_MARKDOWN = "notion_markdown"


class KnowledgeEntityKind(StrEnum):
    """Stable canonical external-knowledge entity vocabulary."""

    SPACE = "space"
    DOCUMENT = "document"
    BLOCK = "block"
    VERSION = "version"
    PROPERTY = "property"
    ATTACHMENT = "attachment"
    AUTHOR = "author"


class KnowledgeToolName(StrEnum):
    """Stable model-visible external-knowledge tool names."""

    SEARCH = "docs_search"
    GET = "docs_get"
    LIST_CHILDREN = "docs_list_children"
    GET_VERSION = "docs_get_version"
    DESCRIBE_FIELDS = "docs_describe_fields"
    CREATE = "docs_create"
    UPDATE = "docs_update"
    APPEND = "docs_append"
    COMMENT = "docs_comment"


class KnowledgeCreateCommandPayload(SorCommandPayload):
    """One document creation request before vendor parent validation."""

    title: str = Field(min_length=1, max_length=10_000)
    normalized_text: str | None = Field(default=None, max_length=1_000_000)
    space_external_id: str | None = Field(default=None, min_length=1, max_length=320)
    parent_external_id: str | None = Field(default=None, min_length=1, max_length=320)


class KnowledgeUpdateCommandPayload(SorCommandPayload):
    """Current document title/content fields supported by executable adapters."""

    title: str | None = Field(default=None, min_length=1, max_length=10_000)
    normalized_text: str | None = Field(default=None, max_length=1_000_000)

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeUpdateCommandPayload":
        if self.title is None and self.normalized_text is None:
            raise ValueError("A document update requires title or content.")
        return self


class KnowledgeTextCommandPayload(SorCommandPayload):
    """One non-empty append or comment body."""

    normalized_text: str = Field(min_length=1, max_length=1_000_000)


KNOWLEDGE_COMMAND_PAYLOAD_TYPES: Mapping[
    KnowledgeToolName, type[SorCommandPayload]
] = {
    KnowledgeToolName.CREATE: KnowledgeCreateCommandPayload,
    KnowledgeToolName.UPDATE: KnowledgeUpdateCommandPayload,
    KnowledgeToolName.APPEND: KnowledgeTextCommandPayload,
    KnowledgeToolName.COMMENT: KnowledgeTextCommandPayload,
}


class KnowledgeSourceBody(SorCanonicalPayload):
    """Discriminated source body retained for specialized human rendering."""

    representation: KnowledgeBodyRepresentation
    value: str

    def to_wire(self) -> dict[str, object]:
        """Convert the typed renderer contract at a JSON persistence boundary."""
        return self.model_dump(mode="json")


def knowledge_source_body(
    representation: KnowledgeBodyRepresentation,
    value: str,
) -> KnowledgeSourceBody:
    """Build the typed source body from one bounded representation."""
    return KnowledgeSourceBody(representation=representation, value=value)


class KnowledgeSpacePayload(SorCanonicalPayload):
    name: str
    kind: str


class KnowledgeDocumentPayload(SorCanonicalPayload):
    title: str
    space_external_id: str | None = None
    parent_external_id: str | None = None
    path: tuple[str, ...] = ()
    source_format: KnowledgeSourceFormat
    normalized_text: str
    source_body: KnowledgeSourceBody | None = None
    content_hash: str
    version: str | None = None
    lifecycle_state: str | None = None
    author_external_id: str | None = None
    label_external_ids: tuple[str, ...] = ()
    unsupported_blocks: tuple[str, ...] = ()
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class KnowledgeBlockPayload(SorCanonicalPayload):
    document_external_id: str
    parent_external_id: str | None = None
    kind: str
    order: int
    normalized_text: str | None = None
    source_body: KnowledgeSourceBody | None = None
    supported: bool
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None


class KnowledgeVersionPayload(SorCanonicalPayload):
    document_external_id: str
    number: str
    author_external_id: str | None = None
    message: str | None = None
    source_format: KnowledgeSourceFormat | None = None
    normalized_text: str | None = None
    source_body: KnowledgeSourceBody | None = None
    source_created_at: datetime


class KnowledgePropertyPayload(SorCanonicalPayload):
    document_external_id: str
    key: str
    label: str
    value_type: str
    value: SorJsonValue = None
    source_updated_at: datetime | None = None


class KnowledgeAttachmentPayload(SorCanonicalPayload):
    document_external_id: str
    name: str
    media_type: str | None = None
    size_bytes: int | None = None
    source_url: str | None = None
    source_url_expires_at: datetime | None = None


class KnowledgeAuthorPayload(SorCanonicalPayload):
    name: str
    primary_email: str | None = None
    kind: str | None = None
    avatar_url: str | None = None


KnowledgePayload = (
    KnowledgeSpacePayload
    | KnowledgeDocumentPayload
    | KnowledgeBlockPayload
    | KnowledgeVersionPayload
    | KnowledgePropertyPayload
    | KnowledgeAttachmentPayload
    | KnowledgeAuthorPayload
)


KNOWLEDGE_PAYLOAD_TYPES: Mapping[KnowledgeEntityKind, type[SorCanonicalPayload]] = {
    KnowledgeEntityKind.SPACE: KnowledgeSpacePayload,
    KnowledgeEntityKind.DOCUMENT: KnowledgeDocumentPayload,
    KnowledgeEntityKind.BLOCK: KnowledgeBlockPayload,
    KnowledgeEntityKind.VERSION: KnowledgeVersionPayload,
    KnowledgeEntityKind.PROPERTY: KnowledgePropertyPayload,
    KnowledgeEntityKind.ATTACHMENT: KnowledgeAttachmentPayload,
    KnowledgeEntityKind.AUTHOR: KnowledgeAuthorPayload,
}


class KnowledgeSpace(SorCanonicalRecord):
    external_id: str
    name: str
    kind: str
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class KnowledgeDocument(SorCanonicalRecord):
    external_id: str
    title: str
    space_external_id: str | None
    parent_external_id: str | None
    path: tuple[str, ...]
    source_format: KnowledgeSourceFormat
    normalized_text: str
    source_body: KnowledgeSourceBody | None = Field(repr=False, exclude=True)
    content_hash: str
    version: str | None
    lifecycle_state: str | None
    author_external_id: str | None
    label_external_ids: tuple[str, ...]
    unsupported_blocks: tuple[str, ...]
    source_created_at: datetime | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class KnowledgeBlock(SorCanonicalRecord):
    external_id: str
    document_external_id: str
    parent_external_id: str | None
    kind: str
    order: int
    normalized_text: str | None
    source_body: KnowledgeSourceBody | None = Field(repr=False, exclude=True)
    supported: bool
    source_created_at: datetime | None
    source_updated_at: datetime | None


class KnowledgeVersion(SorCanonicalRecord):
    external_id: str
    document_external_id: str
    number: str
    author_external_id: str | None
    message: str | None
    source_format: KnowledgeSourceFormat | None
    normalized_text: str | None
    source_body: KnowledgeSourceBody | None = Field(repr=False, exclude=True)
    created_at: datetime


class KnowledgeProperty(SorCanonicalRecord):
    external_id: str
    document_external_id: str
    key: str
    label: str
    value_type: str
    value: SorJsonValue
    source_updated_at: datetime | None


class KnowledgeAttachment(SorCanonicalRecord):
    external_id: str
    document_external_id: str
    name: str
    media_type: str | None
    size_bytes: int | None
    source_url: str | None
    source_url_expires_at: datetime | None


class KnowledgeAttachmentContent(SorCanonicalRecord):
    """Bounded source bytes returned only at an authenticated read boundary."""

    content: bytes = Field(repr=False, exclude=True)
    media_type: str | None


class KnowledgeAuthor(SorCanonicalRecord):
    external_id: str
    name: str
    primary_email: str | None
    kind: str | None
    avatar_url: str | None


@runtime_checkable
class KnowledgeAdapter(SorLifecycleAdapter, Protocol):
    """External-knowledge port with pure, I/O-free record normalization."""

    def normalize_space(
        self,
        record: SorExternalRecord,
        payload: KnowledgeSpacePayload,
    ) -> KnowledgeSpace: ...

    def normalize_document(
        self,
        record: SorExternalRecord,
        payload: KnowledgeDocumentPayload,
    ) -> KnowledgeDocument: ...

    def normalize_block(
        self,
        record: SorExternalRecord,
        payload: KnowledgeBlockPayload,
    ) -> KnowledgeBlock: ...

    def normalize_version(
        self,
        record: SorExternalRecord,
        payload: KnowledgeVersionPayload,
    ) -> KnowledgeVersion: ...

    def normalize_property(
        self,
        record: SorExternalRecord,
        payload: KnowledgePropertyPayload,
    ) -> KnowledgeProperty: ...

    def normalize_attachment(
        self,
        record: SorExternalRecord,
        payload: KnowledgeAttachmentPayload,
    ) -> KnowledgeAttachment: ...

    def normalize_author(
        self,
        record: SorExternalRecord,
        payload: KnowledgeAuthorPayload,
    ) -> KnowledgeAuthor: ...


@runtime_checkable
class KnowledgeAttachmentReader(Protocol):
    """Optional vendor port for current attachment content."""

    async def read_attachment_content(
        self,
        *,
        document_external_id: str,
        attachment_external_id: str,
        maximum_bytes: int,
    ) -> KnowledgeAttachmentContent: ...


__all__ = [
    "KNOWLEDGE_COMMAND_PAYLOAD_TYPES",
    "KNOWLEDGE_PAYLOAD_TYPES",
    "KnowledgeAdapter",
    "KnowledgeAttachment",
    "KnowledgeAttachmentPayload",
    "KnowledgeAttachmentContent",
    "KnowledgeAttachmentReader",
    "KnowledgeAuthor",
    "KnowledgeAuthorPayload",
    "KnowledgeBlock",
    "KnowledgeBlockPayload",
    "KnowledgeBodyRepresentation",
    "KnowledgeCreateCommandPayload",
    "KnowledgeDocument",
    "KnowledgeDocumentPayload",
    "KnowledgeEntityKind",
    "KnowledgePayload",
    "KnowledgeProperty",
    "KnowledgePropertyPayload",
    "KnowledgeSourceBody",
    "KnowledgeSourceFormat",
    "KnowledgeSpace",
    "KnowledgeSpacePayload",
    "KnowledgeVersion",
    "KnowledgeVersionPayload",
    "KnowledgeToolName",
    "KnowledgeTextCommandPayload",
    "KnowledgeUpdateCommandPayload",
    "knowledge_source_body",
]
