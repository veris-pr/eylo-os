"""Profile-owned related-record queries for Support Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel
from eylo.sor.support.contracts import SupportEntityKind, SupportToolName
from eylo.sor.support.models import SupportMessageModel, SupportTicketModel

SUPPORT_AGENT_RELATED_RECORD_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SupportAgentRelatedRecords:
    """One primary record's bounded related Support projection."""

    parent_record_id: UUID
    entity: str
    records: tuple[SorRecordModel, ...]
    truncated: bool


async def read_support_related_records(
    session: AsyncSession,
    *,
    organization_id: UUID,
    tool_name: str,
    parents: tuple[SorRecordModel, ...],
) -> tuple[SupportAgentRelatedRecords, ...]:
    """Read only the explicit relation promised by one Support tool contract."""
    if tool_name == SupportToolName.GET_TICKET:
        entity = SupportEntityKind.MESSAGE.value
        read_one = _ticket_messages
    elif tool_name == SupportToolName.GET_CUSTOMER_HISTORY:
        entity = SupportEntityKind.TICKET.value
        read_one = _customer_tickets
    else:
        return ()

    remaining = SUPPORT_AGENT_RELATED_RECORD_LIMIT
    results: list[SupportAgentRelatedRecords] = []
    for parent in parents:
        if remaining == 0:
            results.append(
                SupportAgentRelatedRecords(
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
        if entity == SupportEntityKind.MESSAGE:
            selected = tuple(reversed(selected))
        remaining -= len(selected)
        results.append(
            SupportAgentRelatedRecords(
                parent_record_id=parent.id,
                entity=entity,
                records=selected,
                truncated=truncated,
            )
        )
    return tuple(results)


async def _ticket_messages(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    rows = list(
        (
            await session.scalars(
                select(SorRecordModel)
                .join(
                    SupportMessageModel,
                    and_(
                        SupportMessageModel.record_id == SorRecordModel.id,
                        SupportMessageModel.source_id == SorRecordModel.source_id,
                        SupportMessageModel.organization_id
                        == SorRecordModel.organization_id,
                    ),
                )
                .where(
                    SorRecordModel.organization_id == organization_id,
                    SorRecordModel.source_id == parent.source_id,
                    SorRecordModel.profile == SorProfile.SUPPORT,
                    SorRecordModel.canonical_entity_kind == "message",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                    SupportMessageModel.ticket_external_id == parent.vendor_external_id,
                    SupportMessageModel.deleted.is_(False),
                )
                .order_by(
                    SupportMessageModel.source_created_at.desc(),
                    SorRecordModel.id.desc(),
                )
                .limit(limit + 1)
            )
        ).all()
    )
    return rows


async def _customer_tickets(
    session: AsyncSession,
    *,
    organization_id: UUID,
    parent: SorRecordModel,
    limit: int,
) -> list[SorRecordModel]:
    return list(
        (
            await session.scalars(
                select(SorRecordModel)
                .join(
                    SupportTicketModel,
                    and_(
                        SupportTicketModel.record_id == SorRecordModel.id,
                        SupportTicketModel.source_id == SorRecordModel.source_id,
                        SupportTicketModel.organization_id
                        == SorRecordModel.organization_id,
                    ),
                )
                .where(
                    SorRecordModel.organization_id == organization_id,
                    SorRecordModel.source_id == parent.source_id,
                    SorRecordModel.profile == SorProfile.SUPPORT,
                    SorRecordModel.canonical_entity_kind == "ticket",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                    SupportTicketModel.requester_external_id
                    == parent.vendor_external_id,
                    SupportTicketModel.deleted.is_(False),
                )
                .order_by(
                    SorRecordModel.source_updated_at.desc().nullslast(),
                    SorRecordModel.projected_at.desc(),
                    SorRecordModel.id.desc(),
                )
                .limit(limit + 1)
            )
        ).all()
    )


__all__ = [
    "SupportAgentRelatedRecords",
    "read_support_related_records",
]
