"""Typed external-document records distinct from Eylo Knowledgebases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from eylo.sor.shared.contracts import SorExternalRecord, SorLifecycleAdapter


@dataclass(frozen=True, slots=True)
class KnowledgeSpace:
    external_id: str
    name: str
    kind: str
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    external_id: str
    title: str
    space_external_id: str | None
    parent_external_id: str | None
    path: tuple[str, ...]
    source_format: str
    normalized_text: str
    source_body: object | None
    content_hash: str
    version: str | None
    lifecycle_state: str | None
    author_external_id: str | None
    label_external_ids: tuple[str, ...]
    unsupported_blocks: tuple[str, ...]
    source_created_at: datetime | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeBlock:
    external_id: str
    document_external_id: str
    parent_external_id: str | None
    kind: str
    order: int
    normalized_text: str | None
    source_body: object | None
    supported: bool
    source_created_at: datetime | None
    source_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeVersion:
    external_id: str
    document_external_id: str
    number: str
    author_external_id: str | None
    message: str | None
    source_format: str | None
    normalized_text: str | None
    source_body: object | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeProperty:
    external_id: str
    document_external_id: str
    key: str
    label: str
    value_type: str
    value: object | None
    source_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeAttachment:
    external_id: str
    document_external_id: str
    name: str
    media_type: str | None
    size_bytes: int | None
    source_url: str | None
    source_url_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeAuthor:
    external_id: str
    name: str
    primary_email: str | None
    kind: str | None
    avatar_url: str | None


@runtime_checkable
class KnowledgeAdapter(SorLifecycleAdapter, Protocol):
    """External-knowledge normalization port; never an internal KB adapter."""

    def normalize_space(self, record: SorExternalRecord) -> KnowledgeSpace: ...

    def normalize_document(self, record: SorExternalRecord) -> KnowledgeDocument: ...

    def normalize_block(self, record: SorExternalRecord) -> KnowledgeBlock: ...

    def normalize_version(self, record: SorExternalRecord) -> KnowledgeVersion: ...

    def normalize_property(self, record: SorExternalRecord) -> KnowledgeProperty: ...

    def normalize_attachment(
        self,
        record: SorExternalRecord,
    ) -> KnowledgeAttachment: ...

    def normalize_author(self, record: SorExternalRecord) -> KnowledgeAuthor: ...


__all__ = [
    "KnowledgeAdapter",
    "KnowledgeAttachment",
    "KnowledgeAuthor",
    "KnowledgeBlock",
    "KnowledgeDocument",
    "KnowledgeProperty",
    "KnowledgeSpace",
    "KnowledgeVersion",
]
