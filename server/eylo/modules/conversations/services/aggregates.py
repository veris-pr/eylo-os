"""Application services for the `conversations` domain."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.services import EyloBaseService
from eylo.modules.conversations.models.conversations import ConversationsModel
from eylo.modules.conversations.repositories.aggregates import (
    ConversationAggregateRepository,
    ConversationAggregateRows,
)
from eylo.modules.conversations.schemas.aggregates import (
    AgentSummary,
    ContactSummary,
    ConversationAggregateResponse,
    MessageSummary,
    ParticipantSummary,
)
from eylo.modules.conversations.schemas.messages import MessageKind


class ConversationAggregateService(
    EyloBaseService[ConversationAggregateResponse, ConversationsModel]
):
    """Service for conversation aggregate operations.

    Provides methods to fetch conversations with all related data (contacts,
    agents, messages, participants) in a single operation.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        """Initialize the service with an aggregate repository.

        Args:
            repository: ConversationAggregateRepository instance

        """
        self._repository = ConversationAggregateRepository(db)

    @property
    def schema(self) -> type[ConversationAggregateResponse]:
        """Return the schema class for this service.

        Returns:
            ConversationAggregateResponse schema class

        """
        return ConversationAggregateResponse

    @property
    def repository(self) -> ConversationAggregateRepository:
        """Return the repository instance.

        Returns:
            ConversationAggregateRepository instance

        """
        return self._repository

    async def get_conversation_with_relations(
        self,
        conversation_id: UUID,
        organization_id: UUID,
        include_messages: bool = True,
        message_limit: int = 50,
        message_offset: int = 0,
        include_participants: bool = True,
        message_kinds: list[MessageKind] | None = None,
    ) -> ConversationAggregateResponse | None:
        """Fetch a single conversation with all related data.

        Args:
            conversation_id: Conversation UUID
            organization_id: Organization UUID
            include_messages: Whether to include messages
            message_limit: Max messages to return
            message_offset: Number of messages to skip (for pagination)
            include_participants: Whether to include participants

        Returns:
            ConversationAggregateResponse instance or None if not found

        """
        results = await self.repository.get_aggregates_by_ids(
            conversation_ids=[conversation_id],
            organization_id=organization_id,
            include_messages=include_messages,
            message_limit=message_limit,
            message_offset=message_offset,
            include_participants=include_participants,
            message_kinds=message_kinds,
        )

        if not results:
            return None

        return self._map_rows_to_schema(results[0])

    async def get_conversations_with_relations(
        self,
        conversation_ids: list[UUID],
        organization_id: UUID,
        include_messages: bool = True,
        message_limit: int = 50,
        message_offset: int = 0,
        include_participants: bool = True,
        message_kinds: list[MessageKind] | None = None,
    ) -> list[ConversationAggregateResponse]:
        """Fetch multiple conversations with all related data.

        Args:
            conversation_ids: List of conversation UUIDs
            organization_id: Organization UUID
            include_messages: Whether to include messages
            message_limit: Max messages to return
            message_offset: Number of messages to skip per conversation (for pagination)
            include_participants: Whether to include participants

        Returns:
            List of ConversationAggregateResponse instances

        """
        aggregates = await self.repository.get_aggregates_by_ids(
            conversation_ids=conversation_ids,
            organization_id=organization_id,
            include_messages=include_messages,
            message_limit=message_limit,
            message_offset=message_offset,
            include_participants=include_participants,
            message_kinds=message_kinds,
        )

        return [self._map_rows_to_schema(aggregate) for aggregate in aggregates]

    def _map_rows_to_schema(
        self, aggregate: ConversationAggregateRows
    ) -> ConversationAggregateResponse:
        """Project selected fields; attached rows never escape in API output."""
        conversation = aggregate.conversation
        contact = aggregate.contact
        primary_agent = aggregate.primary_agent

        # Map contact to ContactSummary
        contact_summary = None
        if contact:
            contact_summary = ContactSummary(
                id=contact.id,
                name=contact.name,
                primary_email=contact.primary_email,
                primary_phone=contact.primary_phone,
            )

        # Map primary agent to AgentSummary
        primary_agent_summary = None
        if primary_agent:
            primary_agent_summary = AgentSummary(
                id=primary_agent.id,
                name=primary_agent.name,
                slug=primary_agent.slug,
                status=primary_agent.status.value,
            )

        # Map all agents to AgentSummary
        all_agents_summary = [
            AgentSummary(
                id=agent.id,
                name=agent.name,
                slug=agent.slug,
                status=agent.status.value,
            )
            for agent in aggregate.all_agents
        ]

        # Map participants to ParticipantSummary
        participants_summary = [
            ParticipantSummary(
                id=entry.participant.id,
                entity_kind=entry.participant.entity_kind,
                entity_id=entry.participant.entity_id,
                has_initiated=entry.participant.has_initiated,
                is_active=entry.participant.is_active,
                is_primary=entry.participant.is_primary,
                joined_at=entry.participant.joined_at,
                left_at=entry.participant.left_at,
                entity_name=entry.entity_name,
            )
            for entry in aggregate.participants
        ]

        sender_kinds = {
            participant.id: participant.entity_kind
            for participant in participants_summary
        }
        messages_summary: list[MessageSummary] = []
        for row in aggregate.messages:
            message = MessageSummary.model_validate(row, from_attributes=True)
            message.sender_kind = sender_kinds.get(row.sender_participant_id)
            messages_summary.append(message)

        # Build ConversationAggregateResponse
        return ConversationAggregateResponse(
            id=conversation.id,
            organization_id=conversation.organization_id,
            external_id=conversation.external_id,
            channel=conversation.channel,
            status=conversation.status,
            title=conversation.title,
            has_triggered_title_generation=(
                conversation.has_triggered_title_generation or False
            ),
            ended_at=conversation.ended_at,
            swarm_id=conversation.swarm_id,
            swarm_revision=conversation.swarm_revision,
            meta=conversation.meta,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            contact=contact_summary,
            primary_agent=primary_agent_summary,
            all_agents=all_agents_summary,
            participants=participants_summary,
            messages=messages_summary,
            message_count=aggregate.message_count,
        )
