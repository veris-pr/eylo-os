"""Plivo v1 call callbacks; CallStatus is distinct from the Event field."""

from enum import StrEnum

from pydantic import Field

from eylo.common.contracts.telephony import CallStatus
from eylo.sockets.telephony.status_contracts import (
    CallbackFields,
    CallbackIdentity,
    StatusCallback,
)


class PlivoCallStatus(StrEnum):
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    FAILED = "failed"
    TIMEOUT = "timeout"
    NO_ANSWER = "no-answer"


_STATUS_MAP: dict[str, CallStatus] = {
    PlivoCallStatus.RINGING: CallStatus.RINGING,
    PlivoCallStatus.IN_PROGRESS: CallStatus.IN_PROGRESS,
    PlivoCallStatus.COMPLETED: CallStatus.COMPLETED,
    PlivoCallStatus.BUSY: CallStatus.BUSY,
    PlivoCallStatus.FAILED: CallStatus.FAILED,
    PlivoCallStatus.TIMEOUT: CallStatus.NO_ANSWER,
    PlivoCallStatus.NO_ANSWER: CallStatus.NO_ANSWER,
}


class PlivoCallbackIdentity(CallbackIdentity):
    call_sid: str = Field(alias="CallUUID", min_length=1)


class PlivoStatusCallback(CallbackFields):
    call_sid: str = Field(alias="CallUUID", min_length=1)
    provider_status: str = Field(default="", alias="CallStatus")
    duration_seconds: int | None = Field(default=None, alias="Duration", ge=0)

    def to_status(self) -> StatusCallback:
        return self.normalized(_STATUS_MAP.get(self.provider_status))
