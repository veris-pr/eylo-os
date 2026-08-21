"""Canonical external-document projection policy independent of vendor payloads."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel, SorRecordModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorProjectionError

from .contracts import (
    KnowledgeAttachment,
    KnowledgeAuthor,
    KnowledgeBlock,
    KnowledgeDocument,
    KnowledgeProperty,
    KnowledgeSpace,
    KnowledgeVersion,
)
from .models import (
    KnowledgeAttachmentModel,
    KnowledgeAuthorModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeSpaceModel,
    KnowledgeVersionModel,
)

KnowledgeRecordModel = TypeVar("KnowledgeRecordModel", bound=SorProfileRecordModel)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_BODY_BYTES = 1_048_576


class KnowledgeProjectionService:
    """Persist typed document fields beside one exact shared source identity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = SorRepository(session)

    async def upsert_space(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        space: KnowledgeSpace,
    ) -> KnowledgeSpaceModel:
        _validate_space(space)
        return await self._upsert(
            KnowledgeSpaceModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="space",
            vendor_external_id=space.external_id,
            values={"name": space.name, "kind": space.kind},
            search_values=(space.name, space.kind),
        )

    async def upsert_document(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        document: KnowledgeDocument,
    ) -> KnowledgeDocumentModel:
        _validate_document(document)
        return await self._upsert(
            KnowledgeDocumentModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="document",
            vendor_external_id=document.external_id,
            values={
                "title": document.title,
                "space_external_id": document.space_external_id,
                "parent_external_id": document.parent_external_id,
                "path": list(document.path),
                "source_format": document.source_format,
                "normalized_text": document.normalized_text,
                "source_body": document.source_body,
                "content_hash": document.content_hash,
                "version": document.version,
                "lifecycle_state": document.lifecycle_state,
                "author_external_id": document.author_external_id,
                "label_external_ids": list(document.label_external_ids),
                "unsupported_blocks": list(document.unsupported_blocks),
                "source_created_at": document.source_created_at,
                "source_updated_at": document.source_updated_at,
            },
            search_values=(
                document.title,
                document.normalized_text,
                document.lifecycle_state,
                *document.path,
                *document.label_external_ids,
            ),
        )

    async def upsert_block(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        block: KnowledgeBlock,
    ) -> KnowledgeBlockModel:
        _validate_block(block)
        return await self._upsert(
            KnowledgeBlockModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="block",
            vendor_external_id=block.external_id,
            values={
                "document_external_id": block.document_external_id,
                "parent_external_id": block.parent_external_id,
                "kind": block.kind,
                "position": block.order,
                "normalized_text": block.normalized_text,
                "source_body": block.source_body,
                "supported": block.supported,
                "source_created_at": block.source_created_at,
                "source_updated_at": block.source_updated_at,
            },
            search_values=(block.normalized_text, block.kind),
        )

    async def upsert_version(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        version: KnowledgeVersion,
    ) -> KnowledgeVersionModel:
        _validate_version(version)
        return await self._upsert(
            KnowledgeVersionModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="version",
            vendor_external_id=version.external_id,
            values={
                "document_external_id": version.document_external_id,
                "number": version.number,
                "author_external_id": version.author_external_id,
                "message": version.message,
                "source_format": version.source_format,
                "normalized_text": version.normalized_text,
                "source_body": version.source_body,
                "source_created_at": version.created_at,
            },
            search_values=(version.number, version.message, version.normalized_text),
        )

    async def upsert_property(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        property_value: KnowledgeProperty,
    ) -> KnowledgePropertyModel:
        _validate_property(property_value)
        return await self._upsert(
            KnowledgePropertyModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="property",
            vendor_external_id=property_value.external_id,
            values={
                "document_external_id": property_value.document_external_id,
                "property_key": property_value.key,
                "label": property_value.label,
                "value_type": property_value.value_type,
                "value": property_value.value,
                "source_updated_at": property_value.source_updated_at,
            },
            search_values=(
                property_value.key,
                property_value.label,
                property_value.value_type,
                _searchable_json(property_value.value),
            ),
        )

    async def upsert_attachment(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        attachment: KnowledgeAttachment,
    ) -> KnowledgeAttachmentModel:
        _validate_attachment(attachment)
        return await self._upsert(
            KnowledgeAttachmentModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="attachment",
            vendor_external_id=attachment.external_id,
            values={
                "document_external_id": attachment.document_external_id,
                "name": attachment.name,
                "media_type": attachment.media_type,
                "size_bytes": attachment.size_bytes,
                "source_url": attachment.source_url,
                "source_url_expires_at": attachment.source_url_expires_at,
            },
            search_values=(attachment.name, attachment.media_type),
        )

    async def upsert_author(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        author: KnowledgeAuthor,
    ) -> KnowledgeAuthorModel:
        _validate_author(author)
        return await self._upsert(
            KnowledgeAuthorModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind="author",
            vendor_external_id=author.external_id,
            values={
                "name": author.name,
                "primary_email": author.primary_email,
                "kind": author.kind,
                "avatar_url": author.avatar_url,
            },
            search_values=(author.name, author.primary_email, author.kind),
        )

    async def _upsert(
        self,
        model: type[KnowledgeRecordModel],
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: str,
        vendor_external_id: str,
        values: dict[str, object],
        search_values: Sequence[str | None],
    ) -> KnowledgeRecordModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=entity_kind,
            vendor_external_id=vendor_external_id,
        )
        row = await self.session.scalar(
            select(model).where(
                model.organization_id == organization_id,
                model.source_id == source_id,
                model.record_id == record_id,
                model.deleted.is_(False),
            )
        )
        if row is None:
            row = model(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.KNOWLEDGE,
                canonical_entity_kind=entity_kind,
                **values,
            )
            self.session.add(row)
        else:
            for field_name, value in values.items():
                setattr(row, field_name, value)
        _update_search(record, *search_values)
        await self.session.flush()
        return row

    async def _require_record(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: str,
        vendor_external_id: str,
    ) -> SorRecordModel:
        record = await self.records.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            for_update=True,
        )
        if record is None:
            raise SorProjectionError("Canonical document source record not found.")
        if (
            record.profile is not SorProfile.KNOWLEDGE
            or record.canonical_entity_kind != entity_kind
            or record.vendor_external_id != vendor_external_id
        ):
            raise SorProjectionError(
                "Document value does not match its canonical source identity."
            )
        return record


def _validate_space(space: KnowledgeSpace) -> None:
    _required(space.external_id, maximum=512, field="space external ID")
    _required(space.name, maximum=1_000_000, field="space name")
    _required(space.kind, maximum=96, field="space kind")
    _optional(space.source_url, maximum=2_048, field="space source URL")
    _mapping(space.custom_fields, field="space custom fields")


def _validate_document(document: KnowledgeDocument) -> None:
    _required(document.external_id, maximum=512, field="document external ID")
    _required(document.title, maximum=1_000_000, field="document title")
    _optional(document.space_external_id, maximum=512, field="document space")
    _optional(document.parent_external_id, maximum=512, field="document parent")
    _identities(document.path, maximum_items=128, field="document path")
    _required(document.source_format, maximum=96, field="document source format")
    _bounded_text(document.normalized_text, field="document normalized text")
    _json_value(document.source_body, field="document source body")
    if _SHA256_PATTERN.fullmatch(document.content_hash) is None:
        raise SorProjectionError("Document content hash is invalid.")
    _optional(document.version, maximum=160, field="document version")
    _optional(
        document.lifecycle_state,
        maximum=96,
        field="document lifecycle state",
    )
    _optional(document.author_external_id, maximum=512, field="document author")
    _identities(
        document.label_external_ids,
        maximum_items=256,
        field="document labels",
    )
    _identities(
        document.unsupported_blocks,
        maximum_items=128,
        maximum_length=160,
        field="document unsupported blocks",
    )
    _aware_optional(document.source_created_at, field="document creation")
    _aware_optional(document.source_updated_at, field="document update")
    _optional(document.source_url, maximum=2_048, field="document source URL")
    _mapping(document.custom_fields, field="document custom fields")


def _validate_block(block: KnowledgeBlock) -> None:
    _required(block.external_id, maximum=512, field="block external ID")
    _required(block.document_external_id, maximum=512, field="block document")
    _optional(block.parent_external_id, maximum=512, field="block parent")
    _required(block.kind, maximum=160, field="block kind")
    if block.order < 0:
        raise SorProjectionError("Document block order is invalid.")
    _optional(block.normalized_text, maximum=1_000_000, field="block text")
    _json_value(block.source_body, field="block source body")
    _aware_optional(block.source_created_at, field="block creation")
    _aware_optional(block.source_updated_at, field="block update")


def _validate_version(version: KnowledgeVersion) -> None:
    _required(version.external_id, maximum=512, field="version external ID")
    _required(version.document_external_id, maximum=512, field="version document")
    _required(version.number, maximum=160, field="version number")
    _optional(version.author_external_id, maximum=512, field="version author")
    _optional(version.message, maximum=1_000_000, field="version message")
    _optional(version.source_format, maximum=96, field="version source format")
    _optional(version.normalized_text, maximum=1_000_000, field="version text")
    _json_value(version.source_body, field="version source body")
    _aware(version.created_at, field="version creation")


def _validate_property(property_value: KnowledgeProperty) -> None:
    _required(property_value.external_id, maximum=512, field="property external ID")
    _required(
        property_value.document_external_id,
        maximum=512,
        field="property document",
    )
    _required(property_value.key, maximum=512, field="property key")
    _required(property_value.label, maximum=1_000_000, field="property label")
    _required(property_value.value_type, maximum=160, field="property value type")
    _json_value(property_value.value, field="property value", allow_scalar=True)
    _aware_optional(property_value.source_updated_at, field="property update")


def _validate_attachment(attachment: KnowledgeAttachment) -> None:
    _required(attachment.external_id, maximum=512, field="attachment external ID")
    _required(
        attachment.document_external_id,
        maximum=512,
        field="attachment document",
    )
    _required(attachment.name, maximum=1_000_000, field="attachment name")
    _optional(attachment.media_type, maximum=320, field="attachment media type")
    _optional(attachment.source_url, maximum=2_048, field="attachment source URL")
    if attachment.size_bytes is not None and not 0 <= attachment.size_bytes < 2**63:
        raise SorProjectionError("Document attachment size is outside the supported range.")
    _aware_optional(
        attachment.source_url_expires_at,
        field="attachment source URL expiry",
    )


def _validate_author(author: KnowledgeAuthor) -> None:
    _required(author.external_id, maximum=512, field="author external ID")
    _required(author.name, maximum=1_000_000, field="author name")
    _optional(author.primary_email, maximum=1_024, field="author email")
    _optional(author.kind, maximum=96, field="author kind")
    _optional(author.avatar_url, maximum=2_048, field="author avatar URL")


def _required(value: str, *, maximum: int, field: str) -> None:
    if not value or len(value) > maximum:
        raise SorProjectionError(f"Document {field} is invalid.")


def _optional(value: str | None, *, maximum: int, field: str) -> None:
    if value is not None and len(value) > maximum:
        raise SorProjectionError(f"Document {field} is too large.")


def _bounded_text(value: str, *, field: str) -> None:
    if len(value) > 1_000_000:
        raise SorProjectionError(f"Document {field} is too large.")


def _identities(
    values: Sequence[str],
    *,
    maximum_items: int,
    field: str,
    maximum_length: int = 512,
) -> None:
    if (
        len(values) > maximum_items
        or len(values) != len(set(values))
        or any(not value or len(value) > maximum_length for value in values)
    ):
        raise SorProjectionError(f"Document {field} are invalid.")


def _aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SorProjectionError(f"Document {field} timestamp must be timezone-aware.")


def _aware_optional(value: datetime | None, *, field: str) -> None:
    if value is not None:
        _aware(value, field=field)


def _mapping(value: Mapping[str, object], *, field: str) -> None:
    if any(not isinstance(key, str) or not key for key in value):
        raise SorProjectionError(f"Document {field} are invalid.")
    _json_size(value, field=field)


def _json_value(
    value: object | None,
    *,
    field: str,
    allow_scalar: bool = False,
) -> None:
    allowed = (dict, list, str, int, float, bool) if allow_scalar else (dict, list, str)
    if value is not None and not isinstance(value, allowed):
        raise SorProjectionError(f"Document {field} is invalid.")
    _json_size(value, field=field)


def _json_size(value: object | None, *, field: str) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise SorProjectionError(f"Document {field} is not valid JSON.") from error
    if len(encoded) > _MAX_BODY_BYTES:
        raise SorProjectionError(f"Document {field} is too large.")


def _searchable_json(value: object | None) -> str | None:
    if value is None:
        return None
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    return encoded[:10_000]


def _update_search(record: SorRecordModel, *values: str | None) -> None:
    record.search_text = " ".join(value for value in values if value)[:1_000_000]
    record.search_vector = func.to_tsvector("simple", record.search_text)


__all__ = ["KnowledgeProjectionService"]
