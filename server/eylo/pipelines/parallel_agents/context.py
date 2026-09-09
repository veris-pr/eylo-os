"""Bind task tools to their exact actor without changing the live conversation."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from eylo.common.database import start_transaction
from eylo.modules.agents.domain import ResolvedExecutableAgent
from eylo.modules.contacts.service import ContactService
from eylo.modules.conversations.models.conversations import ConversationChannels
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.participants import (
    ParticipantInDb,
    ParticipantKind,
)
from eylo.modules.conversations.services.conversations import ConversationService
from eylo.modules.conversations.services.messages import MessageService
from eylo.modules.conversations.services.participants import (
    ConversationParticipantService,
)
from eylo.pipelines.system_tools.availability import refresh_context_tool_availability


class AgentTaskConversationContext(ConversationContext):
    """Worker-local context with a real actor, not a live-conversation handoff.

    Existing tool APIs call ``get_primary_agent`` for their executing actor.
    Here that getter selects the task participant; the stored participant flags
    and conversation's pinned voice policy remain unchanged.
    """

    execution_participant: ParticipantInDb = Field(exclude=True, repr=False)

    @model_validator(mode="after")
    def require_exact_task_actor(self) -> AgentTaskConversationContext:
        agent = self.primary_agent
        actor = self.execution_participant
        if (
            agent is None
            or agent.deleted
            or agent.organization_id != self.conversation.organization_id
            or actor.deleted
            or not actor.is_active
            or actor.entity_kind is not ParticipantKind.AGENT
            or actor.conversation_id != self.conversation.id
            or actor.agent_id != agent.id
            or actor.entity_id != str(agent.id)
            or actor.agent_revision != agent.published_revision
            or actor.agent_revision is None
            or not any(participant == actor for participant in self.participants)
        ):
            raise ValueError("Task context requires its exact persisted agent actor.")
        return self

    def get_primary_agent(self) -> ParticipantInDb:
        """Select execution authority without promoting its persisted participant."""
        return self.execution_participant


async def build_task_conversation_context(
    *,
    organization_id: UUID,
    conversation_id: UUID,
    executable: ResolvedExecutableAgent,
) -> AgentTaskConversationContext:
    """Hydrate task ownership in a DB-only scope, never the parent's model context."""
    agent = executable.agent
    if agent.organization_id != organization_id or agent.deleted:
        raise ValueError("Task agent does not belong to the conversation organization.")

    async with start_transaction() as session:
        conversation = await ConversationService(session).get_(conversation_id)
        if conversation.deleted or conversation.organization_id != organization_id:
            raise ValueError("Task conversation is unavailable.")
        participant_service = ConversationParticipantService(session)
        actor = await participant_service.ensure_agent_actor(
            conversation_id=conversation_id, agent=agent
        )
        participants = await participant_service.list_by_conversation(conversation_id)
        participants = [
            participant for participant in participants if not participant.deleted
        ]
        primary_contact = next(
            (
                participant
                for participant in participants
                if participant.entity_kind is ParticipantKind.CONTACT
                and participant.is_primary
                and participant.is_active
            ),
            None,
        )
        if primary_contact is None:
            raise ValueError("Task conversation has no active primary contact.")
        contact = await ContactService(session).get_(UUID(primary_contact.entity_id))
        if contact.deleted or contact.organization_id != organization_id:
            raise ValueError("Task contact is unavailable.")
        context = AgentTaskConversationContext(
            conversation=conversation,
            participants=participants,
            execution_participant=actor,
            primary_agent=agent,
            primary_contact=contact,
            messages=await MessageService(session).list_by_conversation(
                conversation_id
            ),
            system_prompt=executable.system_prompt,
            tools=list(executable.tools),
            external_id=conversation.external_id,
            widget_interfaces_enabled=conversation.channel
            is ConversationChannels.WIDGET,
        )
        await refresh_context_tool_availability(context, session=session)
    return context
