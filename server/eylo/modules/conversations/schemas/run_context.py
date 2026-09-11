"""Conversation-owned context pinned when a user message files an AgentRun."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eylo.common.contracts.session_state import SessionChannel


class ConversationRunContextKind(StrEnum):
    """Stable persisted discriminator, distinct from parallel task manifests."""

    MESSAGE = "conversation_message"


class ConversationRunContext(BaseModel):
    """Routing facts only; message content and authority remain on product rows."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[ConversationRunContextKind.MESSAGE] = (
        ConversationRunContextKind.MESSAGE
    )
    conversation_id: UUID
    channel: SessionChannel
    is_voice: bool
