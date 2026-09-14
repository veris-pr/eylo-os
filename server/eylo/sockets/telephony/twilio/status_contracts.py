"""Twilio 2010-04-01 call-progress callback fields and native status values."""

from enum import StrEnum

from pydantic import Field

from eylo.common.contracts.telephony import CallStatus
from eylo.sockets.telephony.status_contracts import (
    CallbackFields,
    CallbackIdentity,
    StatusCallback,
)


class TwilioCallStatus(StrEnum):
    QUEUED = "queued"
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"
    FAILED = "failed"
    CANCELED = "canceled"


_STATUS_MAP: dict[str, CallStatus] = {
    TwilioCallStatus.QUEUED: CallStatus.INITIATED,
    TwilioCallStatus.INITIATED: CallStatus.INITIATED,
    TwilioCallStatus.RINGING: CallStatus.RINGING,
    TwilioCallStatus.IN_PROGRESS: CallStatus.IN_PROGRESS,
    TwilioCallStatus.COMPLETED: CallStatus.COMPLETED,
    TwilioCallStatus.BUSY: CallStatus.BUSY,
    TwilioCallStatus.NO_ANSWER: CallStatus.NO_ANSWER,
    TwilioCallStatus.FAILED: CallStatus.FAILED,
    TwilioCallStatus.CANCELED: CallStatus.CANCELED,
}


class TwilioCallbackIdentity(CallbackIdentity):
    call_sid: str = Field(alias="CallSid", min_length=1)


class TwilioStatusCallback(CallbackFields):
    call_sid: str = Field(alias="CallSid", min_length=1)
    provider_status: str = Field(default="", alias="CallStatus")
    duration_seconds: int | None = Field(default=None, alias="CallDuration", ge=0)

    def to_status(self) -> StatusCallback:
        return self.normalized(_STATUS_MAP.get(self.provider_status))
