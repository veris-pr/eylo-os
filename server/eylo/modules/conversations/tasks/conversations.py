"""Periodic tasks for conversation lifecycle management."""

import logging

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.maintenance import MaintenanceFailure
from eylo.common.database import start_transaction
from eylo.modules.conversations.services.conversations import ConversationService

logger = logging.getLogger(__name__)

CONVERSATION_EXPIRATION_FAILURE = "Conversation expiration failed."


class ConversationExpirationCompleted(BaseModel):
    """Committed expiry count; expiry does not create or remove Agent memories."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    expired_count: int = Field(ge=0)


async def expire_old_conversations() -> (
    ConversationExpirationCompleted | MaintenanceFailure
):
    """Expire inactive conversations.

    Fact extraction used to happen here, once, when a conversation died. Memory
    now forms after every run through the run hooks, so nothing is learned or
    lost at expiry — see `modules/memory/hooks.py`.
    """
    logger.info("[ExpireOldConversationsTask] Starting expiration cycle")
    try:
        async with start_transaction() as db:
            expired = await ConversationService(db).expire_old_conversations()
        logger.info(
            f"[ExpireOldConversationsTask] Expired {len(expired)} conversations"
        )
        return ConversationExpirationCompleted(expired_count=len(expired))
    # The NotConfiguredError re-raise that used to sit here existed for fact
    # extraction, which needed an LLM. Expiring a conversation needs no
    # provider, so there is nothing left to propagate.
    except Exception as error:
        logger.error(
            "[ExpireOldConversationsTask] Failed error_type=%s",
            type(error).__name__,
        )
        return MaintenanceFailure(error=CONVERSATION_EXPIRATION_FAILURE)
