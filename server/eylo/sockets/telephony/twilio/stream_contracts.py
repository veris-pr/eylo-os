"""Consumed Twilio Media Streams fields and Eylo-supplied custom parameters."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Event(StrEnum):
    START = "start"
    MEDIA = "media"
    DTMF = "dtmf"
    CLEAR = "clear"


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class RoutingParameters(_WireValue):
    organization_id: str | None = Field(default=None, alias="OrgId")
    agent_id: str | None = Field(default=None, alias="AgentId")
    call_sid: str = Field(default="", alias="CallSid")
    from_number: str = Field(default="", alias="From", repr=False)
    to_number: str = Field(default="", alias="To", repr=False)
    direction: str = Field(default="INBOUND", alias="Direction")
    initial_message: str | None = Field(
        default=None, alias="InitialMessage", repr=False, exclude=True
    )
    stream_token: str | None = Field(
        default=None, alias="StreamToken", repr=False, exclude=True
    )
    legacy_stream_token: str | None = Field(
        default=None, alias="stream_token", repr=False, exclude=True
    )

    @property
    def requires_stream_token(self) -> bool:
        # Presence, including null/empty routing, must not bypass token verification.
        return bool(self.model_fields_set & ROUTING_FIELDS)


ROUTING_FIELDS = frozenset(
    {"organization_id", "agent_id", "initial_message", "direction"}
)


class Start(_WireValue):
    call_sid: str = Field(default="", alias="callSid")
    stream_sid: str | None = Field(default=None, alias="streamSid")
    custom_parameters: RoutingParameters = Field(
        default_factory=RoutingParameters,
        alias="customParameters",
        repr=False,
        exclude=True,
    )


class Media(_WireValue):
    payload: str = Field(default="", repr=False, exclude=True)
    timestamp: str | int = ""
    track: str = "inbound"


class Dtmf(_WireValue):
    digit: str | None = Field(default=None, repr=False, exclude=True)
    digits: str | None = Field(default=None, repr=False, exclude=True)


class StreamMessage(_WireValue):
    # Unknown event names are ignored, not coerced into a supported control event.
    event: str = ""
    sequence_number: str | int | None = Field(default=None, alias="sequenceNumber")
    start: Start | None = Field(default=None, repr=False, exclude=True)
    media: Media | None = Field(default=None, repr=False, exclude=True)
    dtmf: Dtmf | None = Field(default=None, repr=False, exclude=True)


class _OutboundValue(_WireValue):
    model_config = ConfigDict(extra="forbid")


class OutboundAudio(_OutboundValue):
    """Raw mu-law audio already base64 encoded for native transport."""

    payload: str = Field(repr=False)


class MediaCommand(_OutboundValue):
    event: Literal[Event.MEDIA] = Event.MEDIA
    stream_sid: str = Field(serialization_alias="streamSid")
    media: OutboundAudio = Field(repr=False)


class ClearCommand(_OutboundValue):
    event: Literal[Event.CLEAR] = Event.CLEAR
    stream_sid: str = Field(serialization_alias="streamSid")
