"""Apply normalized carrier observations through the committed call lifecycle."""

import asyncio
import logging

import arrow

from eylo.common.contracts.telephony import CallEndedReason
from eylo.common.database import start_transaction
from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.call import (
    CallEndedEvent,
    CallRingingEvent,
)
from eylo.modules.telephony.lifecycle import CallLifecycleConflict, record_call_status
from eylo.modules.telephony.provider_config_domain import TelephonyProvider
from eylo.modules.telephony.schemas import CallStatus
from eylo.modules.telephony.services import TelephonyCallService
from eylo.pipelines.telephony.sessions import S_CALLS
from eylo.sockets.telephony.status_contracts import StatusCallback

logger = logging.getLogger(__name__)


CALL_LOOKUP_ATTEMPTS = 3
CALL_LOOKUP_RETRY_SECONDS = 0.3
PROVIDER_CALLBACK_SOURCE = "provider_callback"


TERMINAL_CALL_STATUSES = (
    CallStatus.COMPLETED,
    CallStatus.BUSY,
    CallStatus.NO_ANSWER,
    CallStatus.FAILED,
    CallStatus.CANCELED,
)

STATUS_TO_ENDED_REASON: dict[CallStatus, CallEndedReason] = {
    CallStatus.BUSY: CallEndedReason.CUSTOMER_BUSY,
    CallStatus.NO_ANSWER: CallEndedReason.CUSTOMER_DID_NOT_ANSWER,
    CallStatus.FAILED: CallEndedReason.ERROR_PROVIDER_DISCONNECTED,
    CallStatus.CANCELED: CallEndedReason.MANUALLY_CANCELED,
}


class StatusCallbackHandler:
    """Apply authenticated carrier observations and emit committed lifecycle events."""

    async def handle(
        self,
        callback: StatusCallback,
        provider: TelephonyProvider,
    ) -> None:
        """Unknown future provider statuses are acknowledged without lifecycle writes."""
        if callback.status is None:
            logger.warning(
                "[%s] Ignored unrecognized callback status for call %s",
                provider,
                callback.call_sid,
            )
            return

        await self._update_call_status(
            call_sid=callback.call_sid,
            status=callback.status,
            provider=provider,
            provider_status=callback.provider_status,
            duration_seconds=callback.duration_seconds,
        )

    async def _update_call_status(
        self,
        call_sid: str,
        status: CallStatus,
        provider: TelephonyProvider,
        provider_status: str | None = None,
        ended_reason: CallEndedReason | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        """Update call record from webhook status.

        Raises on DB failure so the route can return 5xx for provider retry.
        Retries briefly when the call is active in memory but not yet persisted
        (race between webhook and CallStartedEvent DB insert).
        """
        call = None
        # Retry loop: webhook can arrive before persist_call_started inserts the row
        for attempt in range(CALL_LOOKUP_ATTEMPTS):
            async with start_transaction():
                svc = TelephonyCallService()
                call = await svc.get_by_call_sid(call_sid)
            if call:
                break
            # Only retry if the call is active in memory (race), not truly unknown
            if not S_CALLS.find_by_provider_call(provider, call_sid):
                logger.debug(
                    f"[{provider}] Call {call_sid} not in DB or memory, skipping"
                )
                return
            logger.debug(
                f"[{provider}] Call {call_sid} active but not in DB yet, "
                f"retry {attempt + 1}/{CALL_LOOKUP_ATTEMPTS}"
            )
            await asyncio.sleep(CALL_LOOKUP_RETRY_SECONDS * (attempt + 1))

        if not call:
            logger.warning(
                f"[{provider}] Call {call_sid} not in DB after retries, skipping"
            )
            return
        if call.provider != provider:
            raise CallLifecycleConflict(
                "Call provider does not match callback provider."
            )

        is_terminal = status in TERMINAL_CALL_STATUSES
        terminal_reason: CallEndedReason | None = None
        if is_terminal:
            terminal_reason = ended_reason or STATUS_TO_ENDED_REASON.get(status)

        lifecycle_result = await record_call_status(
            organization_id=call.organization_id,
            call_sid=call_sid,
            status=status.value,
            provider_status=provider_status,
            ended_reason=terminal_reason.value if terminal_reason is not None else None,
            ended_at=arrow.utcnow().datetime if is_terminal else None,
            duration_seconds=duration_seconds if is_terminal else None,
            source=PROVIDER_CALLBACK_SOURCE,
        )
        update_result = lifecycle_result.update
        updated_call = update_result.call
        if updated_call and updated_call.status != status.value:
            logger.info(
                "[%s] Ignored stale call status event for %s: incoming=%s persisted=%s",
                provider,
                call_sid,
                status,
                updated_call.status,
            )
            return
        if not updated_call:
            return
        if update_result.ignored:
            logger.info(
                "[%s] Ignored duplicate call status event for %s: incoming=%s persisted=%s",
                provider,
                call_sid,
                status,
                updated_call.status,
            )
            return
        logger.info("[%s] Updated call %s → %s", provider, call_sid, status)

        # Resolve WS-routable session_id: prefer live session, fall back to DB id
        call_for_event = updated_call
        session_id = S_CALLS.resolve_session_id(
            provider,
            call_sid,
            call_for_event.organization_id,
        ) or str(call_for_event.id)

        # Emit ringing event for outbound calls
        if (
            status == CallStatus.RINGING
            and update_result.status_changed
            and call_for_event.organization_id
        ):
            emit_ephemeral(
                CallRingingEvent(
                    message=f"Call ringing ({provider})",
                    session_id=session_id,
                    organization_id=call_for_event.organization_id,
                    call_sid=call_sid,
                    conversation_id=call_for_event.conversation_id,
                    provider=provider,
                    provider_config_id=call_for_event.provider_config_id,
                    provider_config_revision=(call_for_event.provider_config_revision),
                    from_number=call_for_event.from_number,
                    to_number=call_for_event.to_number,
                    agent_id=call_for_event.agent_id,
                    agent_revision=call_for_event.agent_revision,
                ),
            )

        # Emit ended event only for the first transition into a terminal status.
        if (
            is_terminal
            and update_result.entered_terminal_status
            and call_for_event.organization_id
        ):
            reason = ended_reason or STATUS_TO_ENDED_REASON.get(
                status, CallEndedReason.UNKNOWN
            )
            emit_ephemeral(
                CallEndedEvent(
                    message=f"Call ended ({provider}): {reason}",
                    session_id=session_id,
                    organization_id=call_for_event.organization_id,
                    call_sid=call_sid,
                    conversation_id=call_for_event.conversation_id,
                    provider=provider,
                    provider_config_id=call_for_event.provider_config_id,
                    provider_config_revision=(call_for_event.provider_config_revision),
                    from_number=call_for_event.from_number,
                    to_number=call_for_event.to_number,
                    agent_id=call_for_event.agent_id,
                    agent_revision=call_for_event.agent_revision,
                    ended_reason=reason,
                    duration_seconds=duration_seconds,
                    terminal_status=status,
                    data={
                        "campaign_id": call_for_event.campaign_id,
                        "campaign_contact_id": (call_for_event.campaign_contact_id),
                        "campaign_attempt_id": call_for_event.campaign_attempt_id,
                    }
                    if call_for_event.campaign_id
                    else {},
                ),
            )
