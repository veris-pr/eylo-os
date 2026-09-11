"""Best-effort message presentation listeners with no workflow authority."""

from __future__ import annotations

import logging

from eylo.common.database import start_transaction
from eylo.common.exceptions import EntityNotFound
from eylo.events.schema.py_events.base import MessageCreatedEvent
from eylo.modules.conversations.schemas.messages import (
    MessageApiResponseSchema,
    MessageKind,
)
from eylo.modules.conversations.services.conversations import ConversationBaseService
from eylo.modules.conversations.services.messages import MessageService
from eylo.modules.conversations.services.participants import (
    ConversationParticipantService,
)
from eylo.pipelines.websocket.schemas import WsEventAction
from eylo.pipelines.websocket.singleton import S_ws_manager

logger = logging.getLogger(__name__)


async def broadcast_created_message(event: MessageCreatedEvent) -> None:
    """Broadcast a committed user/assistant message as a lossy UI delta."""
    if event.kind not in (MessageKind.ASSISTANT, MessageKind.USER):
        return
    async with start_transaction(ro=True):
        try:
            conversation = await ConversationBaseService().get_(event.conversation_id)
        except EntityNotFound:
            return
        if conversation.deleted:
            return
        message = await MessageService().get_by_conversation_and_id(
            conversation_id=conversation.id,
            message_id=event.message_id,
        )
        if message is None or message.kind != event.kind:
            return
        participants = await ConversationParticipantService().list_by_conversation(
            conversation_id=conversation.id
        )

    contacts = ConversationParticipantService.filter_contact_participants(participants)
    payload = MessageApiResponseSchema.model_validate(message).model_dump(by_alias=True)
    for contact in contacts:
        await S_ws_manager.reply_to_conversation_contact(
            contact_id=contact.entity_id,
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            kind=WsEventAction.MESSAGE_CREATED,
            payload=payload,
        )
