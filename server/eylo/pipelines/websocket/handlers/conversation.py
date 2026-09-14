"""Route conversation list, read, and start commands for a contact."""

import logging
from uuid import UUID

from fastapi import status
from pydantic import ValidationError

from eylo.modules.conversations.controllers.ws_conversations import (
    ConversationWsController,
)
from eylo.modules.conversations.schemas.websocket import (
    WsConversationCreatedRef,
    WsConversationReadReceipt,
)
from eylo.modules.session_context.schemas import SessionContext
from eylo.pipelines.websocket.schemas import (
    WsEventAction,
    WsRequestEvent,
    WsResponse,
)
from eylo.pipelines.websocket.singleton import S_ws_manager

logger = logging.getLogger(__name__)


async def handle_conversation_query(
    event: WsRequestEvent, ctx: SessionContext
) -> WsResponse:
    """Handle conversation query using aggregate service for efficient data fetching.

    Returns conversations with all related data (contacts, agents, messages, participants)
    in a single response to minimize round-trips.
    """
    contact_id = await _get_session_contact_id(ctx)
    return await ConversationWsController().handle_conversation_aggregate_query(
        event,
        ctx,
        contact_id,
    )


async def handle_conversation_read(
    event: WsRequestEvent, ctx: SessionContext
) -> WsResponse:
    contact_id = await _get_session_contact_id(ctx)
    response = await ConversationWsController().handle_conversation_read(
        event,
        ctx,
        contact_id,
    )
    if (
        contact_id is not None
        and response.status == status.HTTP_200_OK
        and response.kind == WsEventAction.CONVERSATION_READ
        and isinstance(response.data, dict)
    ):
        try:
            receipt = WsConversationReadReceipt.model_validate(response.data)
        except ValidationError:
            logger.error(
                "Invalid conversation read receipt organization_id=%s",
                ctx.organization_id,
            )
            return response
        await S_ws_manager.reply_to_conversation_contact(
            contact_id=contact_id,
            organization_id=ctx.organization_id,
            conversation_id=receipt.conversation_id,
            payload=response.data,
            kind=response.kind,
        )
    return response


async def handle_start_conversation(
    event: WsRequestEvent, ctx: SessionContext
) -> WsResponse:
    contact_id = await _get_session_contact_id(ctx)
    response = await ConversationWsController().handle_start_conversation(
        event,
        ctx,
        contact_id,
    )
    if (
        response.status == status.HTTP_200_OK
        and response.kind == WsEventAction.CONVERSATION_CREATED
    ):
        try:
            conversation = WsConversationCreatedRef.model_validate(response.data)
        except ValidationError:
            logger.error(
                "Invalid created conversation reference organization_id=%s",
                ctx.organization_id,
            )
            return response
        await S_ws_manager.associate_conversation_session(
            conversation.id,
            session_id=ctx.session_id,
            organization_id=ctx.organization_id,
        )
    return response


async def _get_session_contact_id(ctx: SessionContext) -> UUID | None:
    return await S_ws_manager.get_contact_for_session(
        organization_id=ctx.organization_id,
        session_id=ctx.session_id,
    )
