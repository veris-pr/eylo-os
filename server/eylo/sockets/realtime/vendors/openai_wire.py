"""OpenAI-owned realtime wire validation; SDK objects never cross the socket."""

import json
import math
from enum import Enum
from typing import Annotated, Final, Literal, NoReturn, TypeAlias

from openai.types.realtime import (
    ConversationItemInputAudioTranscriptionCompletedEvent,
    InputAudioBufferSpeechStartedEvent,
    RealtimeErrorEvent,
    RealtimeSessionCreateRequest,
    ResponseAudioDeltaEvent,
    ResponseAudioTranscriptDeltaEvent,
    ResponseAudioTranscriptDoneEvent,
    ResponseDoneEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictStr,
    TypeAdapter,
)


class OpenAIRealtimeEventType(str, Enum):
    """Events consumed by this adapter, not an exhaustive vendor event catalog."""

    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    AUDIO_DELTA = "response.output_audio.delta"
    TRANSCRIPT_DELTA = "response.output_audio_transcript.delta"
    TRANSCRIPT_DONE = "response.output_audio_transcript.done"
    INPUT_TRANSCRIPTION_DONE = "conversation.item.input_audio_transcription.completed"
    OUTPUT_ITEM_ADDED = "response.output_item.added"
    OUTPUT_ITEM_DONE = "response.output_item.done"
    FUNCTION_CALL_DONE = "response.function_call_arguments.done"
    RESPONSE_DONE = "response.done"
    SPEECH_STARTED = "input_audio_buffer.speech_started"
    ERROR = "error"


class OpenAIRealtimeProtocolFailure(str, Enum):
    MALFORMED_EVENT = "malformed_event"
    INVALID_AUDIO = "invalid_audio"
    INVALID_ARGUMENTS = "invalid_arguments"
    TOOL_IDENTITY_MISMATCH = "tool_identity_mismatch"


class OpenAIRealtimeProtocolError(RuntimeError):
    """Safe protocol failure; vendor payloads are never part of error text."""

    def __init__(self, kind: OpenAIRealtimeProtocolFailure) -> None:
        self.kind = kind
        super().__init__(f"OpenAI Realtime protocol error: {kind.value}.")


class OpenAIRealtimeSession(RealtimeSessionCreateRequest):
    """The server adds an ID missing from the pinned SDK's shared request type."""

    id: StrictStr = Field(min_length=1)


class OpenAIRealtimeSessionEvent(BaseModel):
    """Typed session notification around the SDK's native session settings."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", strict=True, hide_input_in_errors=True
    )

    type: Literal[
        OpenAIRealtimeEventType.SESSION_CREATED,
        OpenAIRealtimeEventType.SESSION_UPDATED,
    ]
    event_id: StrictStr
    session: OpenAIRealtimeSession


OpenAIRealtimeServerEvent: TypeAlias = Annotated[
    OpenAIRealtimeSessionEvent
    | ResponseAudioDeltaEvent
    | ResponseAudioTranscriptDeltaEvent
    | ResponseAudioTranscriptDoneEvent
    | ConversationItemInputAudioTranscriptionCompletedEvent
    | ResponseOutputItemAddedEvent
    | ResponseOutputItemDoneEvent
    | ResponseFunctionCallArgumentsDoneEvent
    | ResponseDoneEvent
    | InputAudioBufferSpeechStartedEvent
    | RealtimeErrorEvent,
    Field(discriminator="type"),
]
_SERVER_EVENT = TypeAdapter(OpenAIRealtimeServerEvent)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_RESPONSE_IN_PROGRESS: Final[Literal["in_progress"]] = "in_progress"
_LEGACY_EVENT_TYPES = {
    "response.audio.delta": OpenAIRealtimeEventType.AUDIO_DELTA,
    "response.audio_transcript.delta": OpenAIRealtimeEventType.TRANSCRIPT_DELTA,
    "response.audio_transcript.done": OpenAIRealtimeEventType.TRANSCRIPT_DONE,
}


class _EventHeader(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)

    type: StrictStr = Field(min_length=1)


def _reject_non_json_number(value: str) -> NoReturn:
    raise ValueError("Non-finite numbers are not JSON values.")


def _parse_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        _reject_non_json_number(value)
    return number


def _parse_json_object(raw: str | bytes) -> dict[str, JsonValue]:
    payload: object = json.loads(
        raw,
        parse_constant=_reject_non_json_number,
        parse_float=_parse_finite_float,
    )
    return _JSON_OBJECT.validate_python(payload, strict=True)


def parse_openai_realtime_event(raw: str | bytes) -> OpenAIRealtimeServerEvent | None:
    """Ignore future/unused event kinds; reject malformed consumed events.

    The three pre-GA audio labels retain their existing translation. No default
    IDs, transcripts, arguments, or acknowledgements are fabricated on readback.
    """
    try:
        payload = _parse_json_object(raw)
        header = _EventHeader.model_validate(payload)
        try:
            event_type = OpenAIRealtimeEventType(
                _LEGACY_EVENT_TYPES.get(header.type, header.type)
            )
        except ValueError:
            return None
        # JSON keys are confined to the wire discriminator compatibility boundary.
        payload["type"] = event_type.value
        event = _SERVER_EVENT.validate_python(payload, strict=True)
        if isinstance(event, ResponseDoneEvent):
            response = event.response
            # The SDK shares optional resource fields with partial representations.
            # A terminal notification must actually identify a terminal response.
            if (
                not response.id
                or response.status is None
                or response.status == _RESPONSE_IN_PROGRESS
                or response.output is None
            ):
                raise OpenAIRealtimeProtocolError(
                    OpenAIRealtimeProtocolFailure.MALFORMED_EVENT
                )
        return event
    except (ValueError, TypeError):
        raise OpenAIRealtimeProtocolError(
            OpenAIRealtimeProtocolFailure.MALFORMED_EVENT
        ) from None


def parse_openai_tool_arguments(arguments: str) -> dict[str, JsonValue]:
    """A function must supply a JSON object; invalid/partial JSON is not an empty call."""
    try:
        return _parse_json_object(arguments)
    except (ValueError, TypeError):
        raise OpenAIRealtimeProtocolError(
            OpenAIRealtimeProtocolFailure.INVALID_ARGUMENTS
        ) from None


class OpenAIRealtimeToolIdentity(BaseModel):
    """Bind streamed arguments to the originating response and output item."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    response_id: StrictStr = Field(min_length=1)
    item_id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)


class OpenAIRealtimeStreamState(BaseModel):
    """Only unfinished function identities live here; never raw arguments/audio."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    pending_tools: dict[str, OpenAIRealtimeToolIdentity] = Field(default_factory=dict)

    def finish_response(self, response_id: str | None) -> None:
        self.pending_tools = {
            call_id: identity
            for call_id, identity in self.pending_tools.items()
            if identity.response_id != response_id
        }
