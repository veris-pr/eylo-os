"""Resolve contact ownership and exact Agent authority for one widget chat."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.conversations.exceptions import ConversationNotFound
from eylo.modules.conversations.schemas.participants import ParticipantKind
from eylo.modules.conversations.services.conversations import ConversationBaseService
from eylo.modules.conversations.services.participants import (
    ConversationParticipantService,
)


class WidgetConversationAuthority(BaseModel):
    """Validated contact and pinned primary-agent authority for one conversation."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    contact_id: UUID
    conversation_id: UUID
    agent_id: UUID
    agent_revision: int = Field(gt=0)


async def resolve_widget_conversation_authority(
    *,
    organization_id: UUID,
    contact_id: UUID,
    conversation_id: UUID,
    session: AsyncSession,
) -> WidgetConversationAuthority:
    """Resolve one contact-owned chat and its single active primary Agent."""
    await ConversationBaseService(session).get_by_organization_contact_and_id(
        organization_id=organization_id,
        contact_id=contact_id,
        pk=conversation_id,
    )
    participants = await ConversationParticipantService(session).list_by_conversation(
        conversation_id
    )
    authorities: list[WidgetConversationAuthority] = []
    for participant in participants:
        agent_id = participant.agent_id
        agent_revision = participant.agent_revision
        if (
            participant.entity_kind == ParticipantKind.AGENT
            and participant.is_primary
            and participant.is_active
            and not participant.deleted
            and agent_id is not None
            and agent_revision is not None
        ):
            authorities.append(
                WidgetConversationAuthority(
                    organization_id=organization_id,
                    contact_id=contact_id,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    agent_revision=agent_revision,
                )
            )
    if len(authorities) != 1:
        raise ConversationNotFound
    return authorities[0]


__all__ = [
    "WidgetConversationAuthority",
    "resolve_widget_conversation_authority",
]
