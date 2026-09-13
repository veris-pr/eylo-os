"""Flat, typed carrier-call UI deltas; routing and config authority stay private."""

from uuid import UUID

from pydantic import Field

from eylo.common.contracts.telephony import CallEndedReason
from eylo.events.schema.py_events.call import (
    CallDirection,
    CallEndedEvent,
    CallState,
    CallStateEvent,
    CallTransferredEvent,
    CallTransferringEvent,
)
from eylo.pipelines.websocket.voice_lifecycle import VoiceLifecyclePayload


class CallLifecyclePayload(VoiceLifecyclePayload):
    """Only declared observations reach clients, never arbitrary event-data keys."""

    state: CallState
    call_sid: str
    direction: CallDirection
    provider: str
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    from_number: str | None = Field(default=None, repr=False)
    to_number: str | None = Field(default=None, repr=False)
    campaign_id: UUID | None = None
    campaign_contact_id: UUID | None = None
    campaign_attempt_id: UUID | None = None
    termination_failure_code: str | None = None
    ended_reason: CallEndedReason | None = None
    duration_seconds: float | None = None
    transfer_to: str | None = Field(default=None, repr=False)

    @classmethod
    def from_event(cls, event: CallStateEvent, *, timestamp: float) -> "CallLifecyclePayload":
        """Translate typed event identity and subtype data into the existing flat wire shape."""
        context = event.context
        data = context.data
        return cls(
            message=event.message,
            timestamp=timestamp,
            state=event.state,
            call_sid=context.call_sid,
            direction=context.direction,
            provider=context.provider,
            agent_id=context.agent_id,
            conversation_id=context.conversation_id,
            from_number=context.from_number or None,
            to_number=context.to_number or None,
            campaign_id=data.campaign_id,
            campaign_contact_id=data.campaign_contact_id,
            campaign_attempt_id=data.campaign_attempt_id,
            termination_failure_code=data.termination_failure_code,
            ended_reason=event.ended_reason if isinstance(event, CallEndedEvent) else None,
            duration_seconds=event.duration_seconds if isinstance(event, CallEndedEvent) else None,
            transfer_to=(
                event.transfer_to
                if isinstance(event, (CallTransferringEvent, CallTransferredEvent))
                else data.transfer_to
            ),
        )
