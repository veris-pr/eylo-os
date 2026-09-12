"""Profile-owned related-record queries for external Documents Agent tools."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eylo.sor.knowledge.contracts import KnowledgeEntityKind, KnowledgeToolName
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel, SorRecordModel
from eylo.sor.shared.schemas import SorAgentRecordResponse, SorAgentViewResponse

from .models import (
    KnowledgeAttachmentModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeVersionModel,
)
from .read_contracts import (
    KNOWLEDGE_CONTENT_DEFAULT_CHARS,
    KNOWLEDGE_NORMALIZED_TEXT_FIELD,
    KNOWLEDGE_SOURCE_BODY_FIELD,
    KnowledgeContentMode,
    KnowledgeContentWindow,
    KnowledgeWindowRecordResponse,
    KnowledgeWindowViewResponse,
)

KNOWLEDGE_AGENT_RELATED_RECORD_LIMIT = 100
KNOWLEDGE_SEARCH_EXCERPT_CHARS = 1_200


class KnowledgeAgentRelatedRecords(BaseModel):
    """One primary document's bounded related canonical projection."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    parent_record_id: UUID
    entity: str
    records: SkipJsonSchema[tuple[InstanceOf[SorRecordModel], ...]] = Field(
        repr=False, exclude=True
    )
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
    content_limit_chars: int = KNOWLEDGE_CONTENT_DEFAULT_CHARS,
) -> KnowledgeWindowViewResponse | SorAgentViewResponse:
    """Remove raw vendor bodies and bound model-facing document content."""
    data = projection.model_copy()
    _remove_source_bodies(data)
    if tool_name == KnowledgeToolName.SEARCH:
        return KnowledgeWindowViewResponse.from_view(
            data,
            items=tuple(
                _apply_search_excerpt(item, search=search) for item in data.items
            ),
            mode=KnowledgeContentMode.SEARCH_EXCERPT,
        )
    if tool_name == KnowledgeToolName.GET:
        return KnowledgeWindowViewResponse.from_view(
            data,
            items=tuple(
                _apply_content_window(
                    item, offset=content_offset, limit=content_limit_chars
                )
                for item in data.items
            ),
            mode=KnowledgeContentMode.CURRENT_CONTENT_WINDOW,
        )
    return data


def _remove_source_bodies(data: SorAgentViewResponse) -> None:
    data.fields = tuple(
        field for field in data.fields if field.key != KNOWLEDGE_SOURCE_BODY_FIELD
    )
    data.items = tuple(_remove_source_body(item) for item in data.items)
    data.related = tuple(collection.model_copy() for collection in data.related)
    for collection in data.related:
        collection.fields = tuple(
            field
            for field in collection.fields
            if field.key != KNOWLEDGE_SOURCE_BODY_FIELD
        )
        collection.items = tuple(_remove_source_body(item) for item in collection.items)


def _remove_source_body(item: SorAgentRecordResponse) -> SorAgentRecordResponse:
    result = item.model_copy()
    result.values = {
        key: value
        for key, value in item.values.items()
        if key != KNOWLEDGE_SOURCE_BODY_FIELD
    }
    return result


def _apply_search_excerpt(
    item: SorAgentRecordResponse, *, search: str
) -> KnowledgeWindowRecordResponse | SorAgentRecordResponse:
    content = item.values.get(KNOWLEDGE_NORMALIZED_TEXT_FIELD)
    if not isinstance(content, str):
        return item
    excerpt, start, end = _content_excerpt(content, search=search)
    item.values[KNOWLEDGE_NORMALIZED_TEXT_FIELD] = excerpt
    return _with_content_window(item, start=start, end=end, total_chars=len(content))


def _apply_content_window(
    item: SorAgentRecordResponse, *, offset: int, limit: int
) -> KnowledgeWindowRecordResponse | SorAgentRecordResponse:
    content = item.values.get(KNOWLEDGE_NORMALIZED_TEXT_FIELD)
    if not isinstance(content, str):
        return item
    start = min(offset, len(content))
    end = min(start + limit, len(content))
    item.values[KNOWLEDGE_NORMALIZED_TEXT_FIELD] = content[start:end]
    return _with_content_window(item, start=start, end=end, total_chars=len(content))


def _with_content_window(
    item: SorAgentRecordResponse, *, start: int, end: int, total_chars: int
) -> KnowledgeWindowRecordResponse:
    return KnowledgeWindowRecordResponse.from_record(
        item,
        KnowledgeContentWindow(
            offset=start,
            end=end,
            total_chars=total_chars,
            has_more=end < total_chars,
            next_offset=end if end < total_chars else None,
        ),
    )


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
        KnowledgeEntityKind.ATTACHMENT: _document_attachments,
        KnowledgeEntityKind.BLOCK: _document_blocks,
        KnowledgeEntityKind.DOCUMENT: _document_children,
        KnowledgeEntityKind.PROPERTY: _document_properties,
        KnowledgeEntityKind.VERSION: _document_versions,
    }
    try:
        selected_entity = KnowledgeEntityKind(entity)
    except ValueError:
        return ()
    read_one = readers.get(selected_entity)
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
        entity=KnowledgeEntityKind.BLOCK,
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
        entity=KnowledgeEntityKind.PROPERTY,
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
        entity=KnowledgeEntityKind.ATTACHMENT,
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
        entity=KnowledgeEntityKind.DOCUMENT,
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
        entity=KnowledgeEntityKind.VERSION,
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
    model: type[SorProfileRecordModel],
    entity: KnowledgeEntityKind,
    relation: ColumnElement[bool],
    order_by: tuple[
        ColumnElement[int]
        | ColumnElement[str]
        | ColumnElement[UUID]
        | ColumnElement[datetime],
        ...,
    ],
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
