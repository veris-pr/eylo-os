"""File canonical voice-message facts inside the message transaction."""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.messages import MessageInDb, MessageKind, RequestStatus
from eylo.events.durable.domain import DurableEventEnvelope
from eylo.events.durable.service import DurableEventService
from eylo.events.durable.voice_contracts import (
    VOICE_MESSAGE_EVENT_TYPE,
    VOICE_MESSAGE_EVENT_VERSION,
    VOICE_MESSAGE_SEGMENT_CONSUMER,
    VOICE_MESSAGE_SUBJECT_TYPE,
)
from eylo.modules.conversations.models.conversations import ConversationsModel

_ASSISTANT_TERMINAL_STATUSES = (
    RequestStatus.COMPLETED,
    RequestStatus.FAILED,
    RequestStatus.INTERRUPTED,
    RequestStatus.SKIPPED,
)


async def file_voice_message_fact(
    *,
    session: AsyncSession,
    message: MessageInDb,
) -> UUID | None:
    """File one stable fact when a canonical message is a final V1 voice class."""
    if not _is_final_voice_timeline_message(message):
        return None
    organization_id = await session.scalar(
        select(ConversationsModel.organization_id).where(
            ConversationsModel.id == message.conversation_id,
            ConversationsModel.deleted.is_(False),
        )
    )
    if organization_id is None:
        raise ValueError("Canonical voice message conversation is unavailable.")

    occurred_at = message.created_at
    recorded_at = _recorded_at(message, occurred_at)
    event_id = uuid5(
        NAMESPACE_URL,
        f"eylo:{VOICE_MESSAGE_EVENT_TYPE}:v1:{organization_id}:{message.id}",
    )
    await DurableEventService(session).file(
        envelope=DurableEventEnvelope(
            event_id=event_id,
            organization_id=organization_id,
            subject_type=VOICE_MESSAGE_SUBJECT_TYPE,
            subject_id=message.id,
            event_type=VOICE_MESSAGE_EVENT_TYPE,
            event_version=VOICE_MESSAGE_EVENT_VERSION,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            payload={},
        ),
        consumer_names=(VOICE_MESSAGE_SEGMENT_CONSUMER,),
    )
    return event_id


def _is_final_voice_timeline_message(message: MessageInDb) -> bool:
    meta = message.meta
    if meta is None or meta.voice_session_row_id is None:
        return False
    if message.kind in (MessageKind.USER, MessageKind.TOOL_USE):
        return True
    if message.kind is not MessageKind.ASSISTANT:
        return False
    if meta.speech_turn_outcome is not None:
        return True
    return message.request_status in _ASSISTANT_TERMINAL_STATUSES


def _recorded_at(message: MessageInDb, occurred_at: datetime) -> datetime:
    meta = message.meta
    if message.kind is MessageKind.ASSISTANT and (
        meta is None or meta.speech_turn_outcome is None
    ):
        return max(message.updated_at, occurred_at)
    return occurred_at
