"""Tenant-scoped read model for the organization Conversations Console."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import SQLColumnExpression, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eylo.modules.conversations.models.conversations import ConversationsModel
from eylo.modules.conversations.models.participants import ParticipantsModel
from eylo.modules.conversations.schemas.conversations import (
    ConversationApiResponseSchema,
    ConversationFilterSchema,
    ConversationSort,
    ConversationSortDirection,
)
from eylo.modules.conversations.schemas.participants import ParticipantKind


class ConversationListResult(BaseModel):
    """A validated page and full filtered count; snapshots omit conversation data."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    items: list[ConversationApiResponseSchema] = Field(exclude=True, repr=False)
    total: int = Field(ge=0)


class ConversationOperatorService:
    """Query complete organization data without changing Conversation state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        organization_id: UUID,
        filters: ConversationFilterSchema,
        limit: int,
        offset: int,
    ) -> ConversationListResult:
        predicates = self._predicates(
            organization_id=organization_id,
            filters=filters,
        )
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(ConversationsModel)
                .where(*predicates)
            )
            or 0
        )
        primary_order = self._sort_column(filters.sort)
        if filters.direction is ConversationSortDirection.ASC:
            order = primary_order.asc().nulls_last()
            stable_order = ConversationsModel.id.asc()
        else:
            order = primary_order.desc().nulls_last()
            stable_order = ConversationsModel.id.desc()

        models = list(
            await self._session.scalars(
                select(ConversationsModel)
                .where(*predicates)
                .order_by(order, stable_order)
                .limit(limit)
                .offset(offset)
            )
        )
        return ConversationListResult(
            items=[
                ConversationApiResponseSchema.model_validate(model)
                for model in models
            ],
            total=total,
        )

    @staticmethod
    def _predicates(
        *,
        organization_id: UUID,
        filters: ConversationFilterSchema,
    ) -> Sequence[ColumnElement[bool]]:
        predicates = [
            ConversationsModel.organization_id == organization_id,
            ConversationsModel.deleted.is_(False),
        ]
        if filters.conversation_ids is not None:
            predicates.append(ConversationsModel.id.in_(filters.conversation_ids))
        if filters.status:
            predicates.append(ConversationsModel.status.in_(filters.status))
        if filters.channel:
            predicates.append(ConversationsModel.channel.in_(filters.channel))
        if filters.query:
            predicates.append(
                ConversationsModel.title.ilike(
                    _literal_contains_pattern(filters.query.strip()),
                    escape="\\",
                )
            )
        if filters.agent_id is not None:
            predicates.append(
                exists(
                    select(1).where(
                        ParticipantsModel.conversation_id == ConversationsModel.id,
                        ParticipantsModel.deleted.is_(False),
                        ParticipantsModel.is_active.is_(True),
                        ParticipantsModel.entity_kind == ParticipantKind.AGENT.value,
                        or_(
                            ParticipantsModel.agent_id == filters.agent_id,
                            ParticipantsModel.entity_id == str(filters.agent_id),
                        ),
                    )
                )
            )
        return predicates

    @staticmethod
    def _sort_column(
        sort: ConversationSort,
    ) -> SQLColumnExpression[str | datetime | None]:
        return {
            ConversationSort.TITLE: func.lower(ConversationsModel.title),
            ConversationSort.CREATED_AT: ConversationsModel.created_at,
            ConversationSort.UPDATED_AT: ConversationsModel.updated_at,
            ConversationSort.ENDED_AT: ConversationsModel.ended_at,
        }[sort]


def _literal_contains_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


__all__ = ["ConversationListResult", "ConversationOperatorService"]
