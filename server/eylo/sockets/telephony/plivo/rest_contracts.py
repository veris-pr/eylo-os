"""Plivo v1 outbound call wire values; request IDs are not live call UUIDs."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CREATE_ORIGIN = "https://api.plivo.com"
CREATE_OPERATION = "telephony.plivo.call.create"
CREATE_TIMEOUT_SECONDS = 20


class CallbackMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class CreateFailureCode(StrEnum):
    REJECTED = "call_create_rejected"
    UNCONFIRMED = "call_create_unconfirmed"
    RESPONSE_INVALID = "call_create_response_invalid"


class CreateCallRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    from_number: str = Field(serialization_alias="from", repr=False)
    to: str = Field(repr=False)
    answer_url: str = Field(repr=False)
    answer_method: Literal[CallbackMethod.GET] = CallbackMethod.GET
    hangup_url: str | None = Field(default=None, repr=False)
    hangup_method: Literal[CallbackMethod.POST] | None = None


class CreateCallResponse(BaseModel):
    """The single-destination create response acknowledges one request, not a call."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )
    request_uuid: str = Field(min_length=1)
