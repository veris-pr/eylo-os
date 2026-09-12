"""Exotel v1 connect-call wire values; no platform routing or persistence policy."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONNECT_TIMEOUT_SECONDS = 20
CONNECT_TIME_LIMIT_SECONDS = 15 * 60
CONNECT_OPERATION = "telephony.exotel.call.create"


class CallType(StrEnum):
    TRANSACTIONAL = "trans"


class ConnectFailureCode(StrEnum):
    REJECTED = "call_create_rejected"
    UNCONFIRMED = "call_create_unconfirmed"
    RESPONSE_INVALID = "call_create_response_invalid"


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", populate_by_name=True,
        hide_input_in_errors=True,
    )


class ConnectParameters(_WireValue):
    """Consume only the packed custom field; other carriers' routing stays opaque."""

    model_config = ConfigDict(extra="ignore")

    custom_field: str | None = Field(default=None, alias="CustomField", repr=False)
    custom_field_value: str | None = Field(default=None, repr=False)

    @property
    def packed_custom_field(self) -> str | None:
        return self.custom_field or self.custom_field_value or None


class ConnectRequest(_WireValue):
    """Form aliases preserve Exotel's customer-leg and applet semantics."""

    from_number: str = Field(serialization_alias="From", repr=False)
    caller_id: str = Field(serialization_alias="CallerId", repr=False)
    url: str = Field(serialization_alias="Url")
    call_type: Literal[CallType.TRANSACTIONAL] = Field(
        default=CallType.TRANSACTIONAL, serialization_alias="CallType"
    )
    time_limit: int = Field(default=CONNECT_TIME_LIMIT_SECONDS, serialization_alias="TimeLimit")
    custom_field: str | None = Field(default=None, serialization_alias="CustomField", repr=False)
    status_callback: str | None = Field(default=None, serialization_alias="StatusCallback", repr=False)


class CreatedCall(_WireValue):
    model_config = ConfigDict(extra="ignore", validate_by_name=False)

    sid: str | None = Field(default=None, alias="Sid")


class ConnectResponse(_WireValue):
    """Read the documented Call.Sid, retaining explicit legacy flat-ID compatibility."""

    model_config = ConfigDict(extra="ignore", validate_by_name=False)

    call: CreatedCall | None = Field(default=None, alias="Call")
    call_sid: str | None = Field(default=None, alias="CallSid")
    sid: str | None = None

    @property
    def provider_reference(self) -> str | None:
        identity = (self.call.sid if self.call else None) or self.call_sid or self.sid
        if not identity:
            return None
        return identity.strip() or None
