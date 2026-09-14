"""Ephemeral carrier observations with pinned identity and typed product references.

These UI deltas follow committed call lifecycle writes. Durable call outcomes
remain owned by the telephony module, not by these best-effort observations.
"""

from enum import Enum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.common.contracts.telephony import CallEndedReason, CallStatus


class CallState(str, Enum):
    """Telephony call states."""

    STARTED = "started"
    RINGING = "ringing"
    CONNECTED = "connected"
    ENDED = "ended"
    TRANSFERRING = "transferring"
    TRANSFERRED = "transferred"


class CallDirection(str, Enum):
    """Call direction."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class _CallEventValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True, allow_inf_nan=False,
    )


class CallEventData(_CallEventValue):
    """Known product references and control outcomes, never a vendor payload."""

    campaign_id: UUID | None = None
    campaign_contact_id: UUID | None = None
    campaign_attempt_id: UUID | None = None
    transfer_to: str | None = Field(default=None, repr=False)
    termination_failure_code: str | None = None


class CallEventContext(_CallEventValue):
    """Identity is resolved by the producer; listeners never infer authority."""

    session_id: str = Field(min_length=1, repr=False)
    organization_id: UUID
    call_sid: str = Field(min_length=1)
    conversation_id: UUID | None = None
    direction: CallDirection
    # Config and socket catalogs have separate owners. The producer translates
    # its validated provider to a name; events do not own a third catalog.
    provider: str = Field(min_length=1)
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0, strict=True)
    from_number: str | None = Field(default=None, repr=False)
    to_number: str | None = Field(default=None, repr=False)
    agent_id: UUID | None = None
    agent_revision: int | None = Field(default=None, gt=0, strict=True)
    data: CallEventData = Field(default_factory=CallEventData)

    @model_validator(mode="after")
    def exact_agent_ref(self) -> Self:
        if (self.agent_id is None) != (self.agent_revision is None):
            raise ValueError("Call events require a complete exact agent reference.")
        return self


class CallStateEvent(_CallEventValue):
    context: CallEventContext
    state: CallState
    message: str


class CallStartedEvent(CallStateEvent):
    """Event emitted when a call is initiated.

    For outbound: emitted when VoiceService.initiate_outbound_call places the call.
    For inbound: emitted when media_stream accepts the WebSocket connection.
    """

    state: Literal[CallState.STARTED] = CallState.STARTED


class CallRingingEvent(CallStateEvent):
    """Event emitted when the provider confirms the phone is ringing.

    Primarily relevant for outbound calls. Set via provider status webhooks.
    """

    state: Literal[CallState.RINGING] = CallState.RINGING


class CallConnectedEvent(CallStateEvent):
    """Event emitted when the call is connected and media stream is active.

    Emitted from media_stream.py when the first media packet arrives
    or when the call session is fully initialized.
    """

    state: Literal[CallState.CONNECTED] = CallState.CONNECTED


class CallEndedEvent(CallStateEvent):
    """Event emitted when a call terminates.

    Includes the ended_reason for campaign analytics, retry logic,
    and agent performance tracking.
    """

    state: Literal[CallState.ENDED] = CallState.ENDED
    ended_reason: CallEndedReason
    duration_seconds: float | None = Field(
        None, description="Call duration in seconds (if available)"
    )
    terminal_status: Literal[
        CallStatus.COMPLETED, CallStatus.BUSY, CallStatus.NO_ANSWER,
        CallStatus.FAILED, CallStatus.CANCELED,
    ] | None = None


class CallTransferringEvent(CallStateEvent):
    """Event emitted when a call transfer is initiated via transfer_call tool."""

    state: Literal[CallState.TRANSFERRING] = CallState.TRANSFERRING
    transfer_to: str = Field(repr=False)


class CallTransferredEvent(CallStateEvent):
    """Event emitted when a call transfer completes successfully."""

    state: Literal[CallState.TRANSFERRED] = CallState.TRANSFERRED
    transfer_to: str = Field(repr=False)
