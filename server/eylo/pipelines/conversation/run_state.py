"""Mutable conversation-only persistence state for one framework turn."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema

from eylo.framework.agents.hooks import RunHooks
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.messages import MessageInDb
from eylo.pipelines.agent_execution_context import PlatformRunState


class ConversationRunState(PlatformRunState[ConversationContext]):
    """Keep authoritative message links current across tool completion and resume."""

    last_message_id: UUID
    active_user_message: MessageInDb = Field(repr=False, exclude=True)
    request_id: UUID | None
    tool_use_messages: dict[str, MessageInDb] = Field(
        default_factory=dict, repr=False, exclude=True
    )
    pending_model_response_cursor: int = 0
    lifecycle_hooks: SkipJsonSchema[InstanceOf[RunHooks] | None] = Field(
        default=None, repr=False, exclude=True
    )


def require_conversation_run_state(local_context: object) -> ConversationRunState:
    if not isinstance(local_context, ConversationRunState):
        raise ValueError("Conversation callbacks require ConversationRunState.")
    return local_context
