"""Vonage Voice v1 event callbacks used by the call lifecycle."""

from enum import StrEnum

from pydantic import Field

from eylo.common.contracts.telephony import CallStatus
from eylo.sockets.telephony.status_contracts import (
    CallbackFields,
    CallbackIdentity,
    StatusCallback,
)


class VonageCallStatus(StrEnum):
    STARTED = "started"
    RINGING = "ringing"
    ANSWERED = "answered"
    COMPLETED = "completed"
    BUSY = "busy"
    TIMEOUT = "timeout"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNANSWERED = "unanswered"


_STATUS_MAP: dict[str, CallStatus] = {
    VonageCallStatus.STARTED: CallStatus.INITIATED,
    VonageCallStatus.RINGING: CallStatus.RINGING,
    VonageCallStatus.ANSWERED: CallStatus.IN_PROGRESS,
    VonageCallStatus.COMPLETED: CallStatus.COMPLETED,
    VonageCallStatus.BUSY: CallStatus.BUSY,
    VonageCallStatus.TIMEOUT: CallStatus.NO_ANSWER,
    VonageCallStatus.FAILED: CallStatus.FAILED,
    VonageCallStatus.REJECTED: CallStatus.FAILED,
    VonageCallStatus.CANCELLED: CallStatus.CANCELED,
    VonageCallStatus.UNANSWERED: CallStatus.NO_ANSWER,
}


class VonageCallbackIdentity(CallbackIdentity):
    call_sid: str = Field(alias="uuid", min_length=1)


class VonageStatusCallback(CallbackFields):
    call_sid: str = Field(alias="uuid", min_length=1)
    provider_status: str = Field(default="", alias="status")
    duration_seconds: int | None = Field(default=None, alias="duration", ge=0)

    def to_status(self) -> StatusCallback:
        return self.normalized(_STATUS_MAP.get(self.provider_status))
