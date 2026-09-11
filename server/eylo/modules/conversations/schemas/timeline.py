"""Content-free conversation facts serialized into the user-session timeline."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.common.contracts.messages import (
    MessageContentKind,
    MessageKind,
    RequestStatus,
)
from eylo.modules.conversations.models.conversations import ConversationChannels


class _ConversationTimelineFact(BaseModel):
    """Keep event details closed, immutable, and free of message content."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    def to_payload(self) -> dict[str, JsonValue]:
        """Preserve explicit nulls in the existing timeline wire representation."""
        return self.model_dump(mode="json")


class MessageCreatedTimelineFact(_ConversationTimelineFact):
    """A message's identity and classification, never its text or tool arguments."""

    conversation_id: UUID
    kind: MessageKind
    content_kind: MessageContentKind
    request_id: UUID | None
    request_status: RequestStatus | None


class RequestStatusTimelineFact(_ConversationTimelineFact):
    """The authoritative request-state transition observed by the writer."""

    conversation_id: UUID
    previous_status: RequestStatus | None
    current_status: RequestStatus


class ConversationParticipationTimelineFact(_ConversationTimelineFact):
    """Channel and published Agent selected for a session's conversation link."""

    channel: ConversationChannels
    agent_id: UUID


class MessageRunQueuedTimelineFact(_ConversationTimelineFact):
    """Message-owned origin and pinned Agent identity for its newly filed run."""

    agent_id: UUID
    agent_revision: int
    conversation_id: UUID
    origin_message_id: UUID
