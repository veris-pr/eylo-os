"""Vonage WebSocket control fields; binary PCM is not parsed as JSON."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Event(StrEnum):
    DTMF = "websocket:dtmf"
    LEGACY_DTMF = "dtmf"
    LEGACY_INPUT = "input"
    LEGACY_START = "start"


class Action(StrEnum):
    CLEAR = "clear"


class _WireValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class ClearCommand(_WireValue):
    """Discard queued carrier playback; transport acceptance is not an acknowledgement."""

    model_config = ConfigDict(extra="forbid")
    action: Literal[Action.CLEAR] = Action.CLEAR


class LegacyDtmf(_WireValue):
    digit: str | None = Field(default=None, repr=False, exclude=True)
    digits: str | None = Field(default=None, repr=False, exclude=True)


class StreamMessage(_WireValue):
    event: str = ""
    digit: str | None = Field(default=None, repr=False, exclude=True)
    digits: LegacyDtmf | str | None = Field(default=None, repr=False, exclude=True)
    dtmf: LegacyDtmf | str | None = Field(default=None, repr=False, exclude=True)

    @property
    def keypad_digits(self) -> str | None:
        if self.event == Event.DTMF:
            return self.digit or None
        data = self.digits or self.dtmf
        if isinstance(data, LegacyDtmf):
            return data.digits or data.digit or None
        return data or None
