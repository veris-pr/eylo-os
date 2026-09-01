"""Profile-owned related-record queries for external Documents Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.knowledge.contracts import KnowledgeEntityKind, KnowledgeToolName
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel
from eylo.sor.shared.schemas import SorAgentViewResponse

from .models import (
    KnowledgeAttachmentModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeVersionModel,
)

KNOWLEDGE_AGENT_RELATED_RECORD_LIMIT = 100
KNOWLEDGE_SEARCH_EXCERPT_CHARS = 1_200


@dataclass(frozen=True, slots=True)
class KnowledgeAgentRelatedRecords:
    """One primary document's bounded related canonical projection."""

    parent_record_id: UUID
    entity: str
    records: tuple[SorRecordModel, ...]
    truncated: bool


def knowledge_related_entities(tool_name: str) -> tuple[str, ...]:
    """Return the exact related collections promised by one Documents tool."""
    if tool_name == KnowledgeToolName.GET:
        return (
            KnowledgeEntityKind.PROPERTY.value,
            KnowledgeEntityKind.ATTACHMENT.value,
        )
    if tool_name == KnowledgeToolName.LIST_CHILDREN:
        return (KnowledgeEntityKind.DOCUMENT.value,)
    if tool_name == KnowledgeToolName.GET_VERSION:
        return (KnowledgeEntityKind.VERSION.value,)
    return ()


def shape_knowledge_tool_response(
    projection: SorAgentViewResponse,
    *,
    tool_name: str,
    search: str,
    content_offset: int = 0,
    content_limit_chars: int = 20_000,
) -> dict[str, Any]:
    """Remove raw vendor bodies and bound model-facing document content."""
    data = projection.model_dump(mode="json")
    _remove_source_bodies(data)
    if tool_name == KnowledgeToolName.SEARCH:
        for item in data["items"]:
            _apply_search_excerpt(item, search=search)
        data["content_mode"] = "search_excerpt"
    elif tool_name == KnowledgeToolName.GET:
        for item in data["items"]:
            _apply_content_window(
                item,
                offset=content_offset,
                limit=content_limit_chars,
            )
        data["content_mode"] = "current_content_window"
    return data


def _remove_source_bodies(data: dict[str, Any]) -> None:
    data["fields"] = [
        field for field in data.get("fields", ()) if field.get("key") != "source_body"
    ]
    for item in data.get("items", ()):
        _remove_source_body(item)
    for collection in data.get("related", ()):
        collection["fields"] = [
            field
            for field in collection.get("fields", ())
            if field.get("key") != "source_body"
        ]
        for item in collection.get("items", ()):
            _remove_source_body(item)


def _remove_source_body(item: dict[str, Any]) -> None:
    values = item.get("values")
    if isinstance(values, dict):
        values.pop("source_body", None)


def _apply_search_excerpt(item: dict[str, Any], *, search: str) -> None:
    values = item.get("values")
    if not isinstance(values, dict):
        return
    content = values.get("normalized_text")
    if not isinstance(content, str):
        return
    excerpt, start, end = _content_excerpt(content, search=search)
    values["normalized_text"] = excerpt
    item["content_window"] = {
        "offset": start,
        "end": end,
        "total_chars": len(content),
        "has_more": end < len(content),
        "next_offset": end if end < len(content) else None,
    }


def _apply_content_window(item: dict[str, Any], *, offset: int, limit: int) -> None:
    values = item.get("values")
    if not isinstance(values, dict):
        return
    content = values.get("normalized_text")
    if not isinstance(content, str):
        return
    start = min(offset, len(content))
    end = min(start + limit, len(content))
    values["normalized_text"] = content[start:end]
    item["content_window"] = {
        "offset": start,
        "end": end,
        "total_chars": len(content),
        "has_more": end < len(content),
        "next_offset": end if end < len(content) else None,
    }


def _content_excerpt(content: str, *, search: str) -> tuple[str, int, int]:
    if len(content) <= KNOWLEDGE_SEARCH_EXCERPT_CHARS:
        return content, 0, len(content)
    normalized_search = search.strip().casefold()
    normalized_content = content.casefold()
    match_at = normalized_content.find(normalized_search) if normalized_search else -1
    if match_at < 0 and normalized_search:
        match_at = next(
            (
                normalized_content.find(term)
                for term in normalized_search.split()
                if normalized_content.find(term) >= 0
            ),
            -1,
        )
    center = match_at if match_at >= 0 else 0
    start = max(0, center - KNOWLEDGE_SEARCH_EXCERPT_CHARS // 3)
    end = min(len(content), start + KNOWLEDGE_SEARCH_EXCERPT_CHARS)
    start = max(0, end - KNOWLEDGE_SEARCH_EXCERPT_CHARS)
    return content[start:end], start, end


async def read_knowledge_related_records(
    session: AsyncSession,
    *,
    organization_id: UUID,
    entity: str,
    parents: tuple[SorRecordModel, ...],
) -> tuple[KnowledgeAgentRelatedRecords, ...]:
    """Read one explicit, source-local document relation with a global bound."""
    readers = {
        "attachment": _document_attachments,
        "block": _document_blocks,
        "document": _document_children,
        "property": _document_properties,
        "version": _document_versions,
    }
    read_one = readers.get(entity)
    if read_one is None:
        return ()

    remaining = KNOWLEDGE_AGENT_RELATED_RECORD_LIMIT
    results: list[KnowledgeAgentRelatedRecords] = []
    for parent in parents:
        if remaining == 0:
            results.append(
                KnowledgeAgentRelatedRecords(
                    parent_record_id=parent.id,
                    entity=entity,
                    records=(),
                    truncated=True,
                )
            )
            continue
        rows = await read_one(
            session,
            organization_id=organization_id,
            parent=parent,
            limit=remaining,
        )
        truncated = len(rows) > remaining
        selected = tuple(rows[:remaining])
        remaining -= len(selected)
        results.append(
            KnowledgeAgentRelatedRecords(
                parent_record_id=parent.id,
                entity=entity,
                records=selected,
                truncated=truncated,
            )
        )
    return tuple(results)


async def _document_blocks(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return await _related_rows(
        session,
        organization_id=organization_id,
        parent=parent,
        model=KnowledgeBlockModel,
        entity="block",
        relation=KnowledgeBlockModel.document_external_id == parent.vendor_external_id,
        order_by=(KnowledgeBlockModel.position.asc(), SorRecordModel.id.asc()),
        limit=limit,
    )


async def _document_properties(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return await _related_rows(
        session,
        organization_id=organization_id,
        parent=parent,
        model=KnowledgePropertyModel,
        entity="property",
        relation=(
            KnowledgePropertyModel.document_external_id == parent.vendor_external_id
        ),
        order_by=(KnowledgePropertyModel.label.asc(), SorRecordModel.id.asc()),
        limit=limit,
    )


async def _document_attachments(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return await _related_rows(
        session,
        organization_id=organization_id,
        parent=parent,
        model=KnowledgeAttachmentModel,
        entity="attachment",
        relation=(
            KnowledgeAttachmentModel.document_external_id == parent.vendor_external_id
        ),
        order_by=(KnowledgeAttachmentModel.name.asc(), SorRecordModel.id.asc()),
        limit=limit,
    )


async def _document_children(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return await _related_rows(
        session,
        organization_id=organization_id,
        parent=parent,
        model=KnowledgeDocumentModel,
        entity="document",
        relation=(
            KnowledgeDocumentModel.parent_external_id == parent.vendor_external_id
        ),
        order_by=(KnowledgeDocumentModel.title.asc(), SorRecordModel.id.asc()),
        limit=limit,
    )


async def _document_versions(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return await _related_rows(
        session,
        organization_id=organization_id,
        parent=parent,
        model=KnowledgeVersionModel,
        entity="version",
        relation=(
            KnowledgeVersionModel.document_external_id == parent.vendor_external_id
        ),
        order_by=(
            KnowledgeVersionModel.source_created_at.desc(),
            SorRecordModel.id.desc(),
        ),
        limit=limit,
    )


async def _related_rows(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    model,
    entity: str,
    relation,
    order_by: tuple,
    limit: int,
) -> list[SorRecordModel]:
    return list(
        (
            await session.scalars(
                select(SorRecordModel)
                .join(
                    model,
                    and_(
                        model.record_id == SorRecordModel.id,
                        model.source_id == SorRecordModel.source_id,
                        model.organization_id == SorRecordModel.organization_id,
                    ),
                )
                .where(
                    SorRecordModel.organization_id == organization_id,
                    SorRecordModel.source_id == parent.source_id,
                    SorRecordModel.profile == SorProfile.KNOWLEDGE,
                    SorRecordModel.canonical_entity_kind == entity,
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                    relation,
                    model.deleted.is_(False),
                )
                .order_by(*order_by)
                .limit(limit + 1)
            )
        ).all()
    )


__all__ = [
    "KNOWLEDGE_SEARCH_EXCERPT_CHARS",
    "KnowledgeAgentRelatedRecords",
    "knowledge_related_entities",
    "read_knowledge_related_records",
    "shape_knowledge_tool_response",
]
