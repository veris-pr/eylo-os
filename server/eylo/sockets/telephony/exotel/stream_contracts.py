"""Exotel AgentStream fields and explicitly supported packed routing compatibility."""

import html
import json
import logging
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

logger = logging.getLogger(__name__)
CUSTOM_PARAMETERS = TypeAdapter(dict[str, JsonValue])


class Event(StrEnum):
    START = "start"
    MEDIA = "media"
    DTMF = "dtmf"
    LEGACY_DIGITS = "digits"
    CLEAR = "clear"


class CustomFieldKey(StrEnum):
    STANDARD = "CustomField"
    LOWERCASE = "customfield"


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class RoutingParameters(_WireValue):
    org_id: str | None = None
    alternate_org_id: str | None = Field(default=None, alias="OrgId")
    agent_id: str | None = None
    alternate_agent_id: str | None = Field(default=None, alias="AgentId")
    direction: str | None = None
    alternate_direction: str | None = Field(default=None, alias="Direction")
    initial_message: str | None = Field(
        default=None, alias="InitialMessage", repr=False, exclude=True
    )
    alternate_initial_message: str | None = Field(
        default=None, alias="initial_message", repr=False, exclude=True
    )
    stream_token: str | None = Field(
        default=None, alias="StreamToken", repr=False, exclude=True
    )
    alternate_stream_token: str | None = Field(
        default=None, alias="stream_token", repr=False, exclude=True
    )

    @property
    def requires_stream_token(self) -> bool:
        return bool(self.model_fields_set & ROUTING_FIELDS)


ROUTING_FIELDS = frozenset(
    {
        "org_id",
        "alternate_org_id",
        "agent_id",
        "alternate_agent_id",
        "direction",
        "alternate_direction",
        "initial_message",
        "alternate_initial_message",
    }
)


def unpack_routing(raw: dict[str, JsonValue]) -> RoutingParameters:
    """Preserve packed-key/value precedence without logging tokens or caller data."""
    values = dict(raw)
    for key in raw:
        unescaped = html.unescape(key)
        if unescaped.startswith("{") and unescaped.endswith("}"):
            _merge_packed_parameters(values, unescaped)
    packed = raw.get(CustomFieldKey.STANDARD) or raw.get(CustomFieldKey.LOWERCASE)
    if isinstance(packed, str):
        _merge_packed_parameters(values, html.unescape(packed))
    return RoutingParameters.model_validate(values)


def _merge_packed_parameters(target: dict[str, JsonValue], packed: str) -> None:
    try:
        decoded = json.loads(packed)
    except json.JSONDecodeError:
        logger.warning("Exotel packed custom parameters are not valid JSON.")
        return
    if isinstance(decoded, dict):
        target.update(CUSTOM_PARAMETERS.validate_python(decoded))


class Start(_WireValue):
    call_sid: str = ""
    from_number: str = Field(default="", alias="from", repr=False)
    to_number: str = Field(default="", alias="to", repr=False)
    custom_parameters: dict[str, JsonValue] | None = Field(
        default=None, repr=False, exclude=True
    )


class Media(_WireValue):
    payload: str = Field(default="", repr=False, exclude=True)
    timestamp: str | int = ""
    track: str = "inbound"
    sequence_number: str | int = 0


class Dtmf(_WireValue):
    digit: str | None = Field(default=None, repr=False, exclude=True)
    digits: str | None = Field(default=None, repr=False, exclude=True)


class StreamMessage(_WireValue):
    event: str = ""
    stream_sid: str = ""
    sequence_number: str | int | None = None
    start: Start | None = Field(default=None, repr=False, exclude=True)
    media: Media | None = Field(default=None, repr=False, exclude=True)
    dtmf: Dtmf | str | None = Field(default=None, repr=False, exclude=True)
    digits: Dtmf | str | None = Field(default=None, repr=False, exclude=True)
    digit: str | None = Field(default=None, repr=False, exclude=True)

    @property
    def keypad_digits(self) -> str | None:
        data = self.dtmf or self.digits
        if isinstance(data, Dtmf):
            return data.digit or data.digits or None
        return data or self.digit or None


class _OutboundValue(_WireValue):
    model_config = ConfigDict(extra="forbid")


class OutboundAudio(_OutboundValue):
    payload: str = Field(repr=False)
    timestamp: str


class MediaCommand(_OutboundValue):
    """Retain the existing ordinal representation; sequencing is owned by the sender."""

    event: Literal[Event.MEDIA] = Event.MEDIA
    sequence_number: str
    stream_sid: str
    media: OutboundAudio = Field(repr=False)


class ClearCommand(_OutboundValue):
    event: Literal[Event.CLEAR] = Event.CLEAR
    stream_sid: str
