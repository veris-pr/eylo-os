"""Profile-owned related-record queries for external Documents Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel

from .models import (
    KnowledgeAttachmentModel,
    KnowledgeBlockModel,
    KnowledgeDocumentModel,
    KnowledgePropertyModel,
    KnowledgeVersionModel,
)

KNOWLEDGE_AGENT_RELATED_RECORD_LIMIT = 100


@dataclass(frozen=True, slots=True)
class KnowledgeAgentRelatedRecords:
    """One primary document's bounded related canonical projection."""

    parent_record_id: UUID
    entity: str
    records: tuple[SorRecordModel, ...]
    truncated: bool


def knowledge_related_entities(tool_name: str) -> tuple[str, ...]:
    """Return the exact related collections promised by one Documents tool."""
    if tool_name == "docs_get":
        return ("block", "property", "attachment")
    if tool_name == "docs_list_children":
        return ("document",)
    if tool_name == "docs_get_version":
        return ("version",)
    return ()


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
    "KnowledgeAgentRelatedRecords",
    "knowledge_related_entities",
    "read_knowledge_related_records",
]
