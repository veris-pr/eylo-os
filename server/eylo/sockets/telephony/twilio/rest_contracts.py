"""Consumed Twilio 2010-04-01 call REST contracts; media packets live separately."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CALL_TIMEOUT_SECONDS = 15
CREATE_OPERATION = "telephony.twilio.call.create"
CREATE_FAILURE_OPERATION = "call_create"


class CallbackMethod(StrEnum):
    POST = "POST"


class CallUpdateStatus(StrEnum):
    COMPLETED = "completed"


class CallFailureCode(StrEnum):
    RESPONSE_INVALID = "call_create_response_invalid"


class _Request(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )


class CreateCallRequest(_Request):
    to: str = Field(serialization_alias="To", repr=False)
    from_number: str = Field(serialization_alias="From", repr=False)
    twiml: str = Field(serialization_alias="Twiml", repr=False)
    status_callback: str = Field(serialization_alias="StatusCallback", repr=False)
    status_callback_method: Literal[CallbackMethod.POST] = Field(
        default=CallbackMethod.POST,
        serialization_alias="StatusCallbackMethod",
    )


class EndCallRequest(_Request):
    status: Literal[CallUpdateStatus.COMPLETED] = Field(
        default=CallUpdateStatus.COMPLETED,
        serialization_alias="Status",
    )


class TwimlUpdateRequest(_Request):
    twiml: str = Field(serialization_alias="Twiml", repr=False)


class CreatedCall(BaseModel):
    """Ignore unconsumed provider fields, never coerce a malformed identity."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )
    sid: str | None = None
