"""Platform-normalized realtime events.

Every vendor adapter translates its protocol into these types.
The pipelines.voice.realtime.RealtimeManager only sees these — never
vendor-specific objects.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictBytes,
    StrictStr,
    TypeAdapter,
)

from eylo.common.contracts.conversation import REALTIME_MESSAGE_SOURCE

# Sentinel used in message meta to skip the agent loop for realtime-persisted messages.
# Referenced in: manager.py (_persist_turn) and listeners/py_events/messages.py
REALTIME_SOURCE = REALTIME_MESSAGE_SOURCE

# Both Gemini Live and OpenAI Realtime output 24kHz PCM.
VENDOR_OUTPUT_SAMPLE_RATE = 24000


class RealtimeEventType(str, Enum):
    AUDIO_DATA = "audio_data"
    USER_SPEECH_STARTED = "user_speech_started"
    INPUT_TRANSCRIPT = "input_transcript"
    OUTPUT_TRANSCRIPT = "output_transcript"
    TOOL_CALL = "tool_call"
    INTERRUPTION = "interruption"
    TURN_COMPLETE = "turn_complete"
    SESSION_STARTED = "session_started"
    GO_AWAY = "go_away"
    ERROR = "error"


class _RealtimeEvent(BaseModel):
    """Closed normalized envelope; event identity cannot drift from its payload."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class AudioDataEvent(_RealtimeEvent):
    """Raw PCM S16LE mono output; sample_rate describes the actual vendor bytes."""

    type: Literal[RealtimeEventType.AUDIO_DATA] = RealtimeEventType.AUDIO_DATA
    audio: StrictBytes = b""
    sample_rate: int = Field(default=VENDOR_OUTPUT_SAMPLE_RATE, strict=True, gt=0)


class UserSpeechStartedEvent(_RealtimeEvent):
    """The provider detected user speech; this is not always an interruption."""

    type: Literal[RealtimeEventType.USER_SPEECH_STARTED] = (
        RealtimeEventType.USER_SPEECH_STARTED
    )


class InputTranscriptEvent(_RealtimeEvent):
    """User speech transcription from the vendor."""

    type: Literal[RealtimeEventType.INPUT_TRANSCRIPT] = (
        RealtimeEventType.INPUT_TRANSCRIPT
    )
    text: StrictStr = ""
    is_final: StrictBool = False


class OutputTranscriptEvent(_RealtimeEvent):
    """Model speech transcription from the vendor."""

    type: Literal[RealtimeEventType.OUTPUT_TRANSCRIPT] = (
        RealtimeEventType.OUTPUT_TRANSCRIPT
    )
    text: StrictStr = ""
    is_final: StrictBool = False


class ToolCallEvent(_RealtimeEvent):
    """Vendor requests tool execution."""

    type: Literal[RealtimeEventType.TOOL_CALL] = RealtimeEventType.TOOL_CALL
    tool_call_id: StrictStr = ""
    tool_name: StrictStr = ""
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class InterruptionEvent(_RealtimeEvent):
    """User interrupted model speech (VAD-detected)."""

    type: Literal[RealtimeEventType.INTERRUPTION] = RealtimeEventType.INTERRUPTION


class TurnCompleteEvent(_RealtimeEvent):
    """Model finished a full response turn."""

    type: Literal[RealtimeEventType.TURN_COMPLETE] = RealtimeEventType.TURN_COMPLETE


class SessionStartedEvent(_RealtimeEvent):
    """Vendor session is ready to receive audio."""

    type: Literal[RealtimeEventType.SESSION_STARTED] = RealtimeEventType.SESSION_STARTED
    session_id: StrictStr = ""


class GoAwayEvent(_RealtimeEvent):
    """Vendor signals imminent disconnection — reconnect now."""

    type: Literal[RealtimeEventType.GO_AWAY] = RealtimeEventType.GO_AWAY
    time_left_ms: int = Field(default=0, strict=True, ge=0)


class ErrorEvent(_RealtimeEvent):
    """Vendor-side error."""

    type: Literal[RealtimeEventType.ERROR] = RealtimeEventType.ERROR
    message: StrictStr = ""
    code: StrictStr = ""
    is_recoverable: StrictBool = True


RealtimeEvent: TypeAlias = Annotated[
    AudioDataEvent
    | UserSpeechStartedEvent
    | InputTranscriptEvent
    | OutputTranscriptEvent
    | ToolCallEvent
    | InterruptionEvent
    | TurnCompleteEvent
    | SessionStartedEvent
    | GoAwayEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
_REALTIME_EVENT = TypeAdapter(RealtimeEvent)


def validate_realtime_event(value: object) -> RealtimeEvent:
    """Revalidate adapter output before any event-driven platform effect."""
    return _REALTIME_EVENT.validate_python(value)
