"""Nova Sonic JSON wire contracts inside Bedrock's typed event-stream chunks.

AWS defines JSON events separately from the SDK chunk union. Unknown event names
are ignored; malformed known events fail before audio, transcript or tool effects.
"""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    Json,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)
from pydantic.alias_generators import to_camel

NovaIdentifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, pattern=r"\S")
]
NovaProbability = Annotated[float, Field(strict=True, ge=0, le=1)]
NovaTokenCount = Annotated[int, Field(strict=True, ge=0)]


class NovaEventType(StrEnum):
    SESSION_START = "sessionStart"
    PROMPT_START = "promptStart"
    CONTENT_START = "contentStart"
    TEXT_INPUT = "textInput"
    AUDIO_INPUT = "audioInput"
    TOOL_RESULT = "toolResult"
    CONTENT_END = "contentEnd"
    PROMPT_END = "promptEnd"
    SESSION_END = "sessionEnd"
    COMPLETION_START = "completionStart"
    TEXT_OUTPUT = "textOutput"
    AUDIO_OUTPUT = "audioOutput"
    TOOL_USE = "toolUse"
    COMPLETION_END = "completionEnd"
    USAGE = "usageEvent"


class NovaRole(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"
    SYSTEM_SPEECH = "SYSTEM_SPEECH"


class NovaContentType(StrEnum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    TOOL = "TOOL"


class NovaGenerationStage(StrEnum):
    FINAL = "FINAL"
    SPECULATIVE = "SPECULATIVE"


class NovaStopReason(StrEnum):
    END_TURN = "END_TURN"
    PARTIAL_TURN = "PARTIAL_TURN"
    TOOL_USE = "TOOL_USE"
    INTERRUPTED = "INTERRUPTED"


class NovaEndpointingSensitivity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NovaTextMode(StrEnum):
    HISTORY = "history"
    INTERACTIVE = "interactive"


class NovaProtocolFailure(StrEnum):
    MALFORMED_EVENT = "malformed_event"
    INVALID_ARGUMENTS = "invalid_arguments"
    INVALID_AUDIO = "invalid_audio"
    IDENTITY_MISMATCH = "identity_mismatch"
    CONTENT_MISMATCH = "content_mismatch"


class NovaProtocolError(RuntimeError):
    """Safe failure code without provider content or validation input."""

    def __init__(self, code: NovaProtocolFailure) -> None:
        self.code = code
        super().__init__("Amazon Nova 2 Sonic returned an invalid event.")


class NovaWireModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
        allow_inf_nan=False,
    )


class NovaTextConfiguration(NovaWireModel):
    media_type: Literal["text/plain"] = "text/plain"


class NovaJsonConfiguration(NovaWireModel):
    media_type: Literal["application/json"] = "application/json"


class NovaAudioConfiguration(NovaWireModel):
    media_type: Literal["audio/lpcm"] = "audio/lpcm"
    sample_rate_hertz: Literal[8000, 16000, 24000]
    sample_size_bits: Literal[16] = 16
    channel_count: Literal[1] = 1
    encoding: Literal["base64"] = "base64"


class NovaInputAudioConfiguration(NovaAudioConfiguration):
    audio_type: Literal["SPEECH"] = "SPEECH"


class NovaOutputAudioConfiguration(NovaInputAudioConfiguration):
    voice_id: NovaIdentifier


class NovaInferenceConfiguration(NovaWireModel):
    max_tokens: Annotated[int, Field(strict=True, gt=0)]
    top_p: NovaProbability
    temperature: NovaProbability


class NovaTurnDetectionConfiguration(NovaWireModel):
    endpointing_sensitivity: NovaEndpointingSensitivity


class NovaToolInputSchema(NovaWireModel):
    definition: str = Field(
        validation_alias="json", serialization_alias="json", strict=True
    )


class NovaToolSpec(NovaWireModel):
    name: NovaIdentifier
    description: str = Field(strict=True)
    input_schema: NovaToolInputSchema


class NovaToolDefinition(NovaWireModel):
    tool_spec: NovaToolSpec


class NovaToolConfiguration(NovaWireModel):
    tools: tuple[NovaToolDefinition, ...]


class NovaToolResultConfiguration(NovaWireModel):
    tool_use_id: NovaIdentifier
    type: Literal[NovaContentType.TEXT] = NovaContentType.TEXT
    text_input_configuration: NovaTextConfiguration = Field(
        default_factory=NovaTextConfiguration
    )


class NovaSessionStart(NovaWireModel):
    event_name: ClassVar[NovaEventType] = NovaEventType.SESSION_START
    inference_configuration: NovaInferenceConfiguration
    turn_detection_configuration: NovaTurnDetectionConfiguration


class NovaPromptStart(NovaWireModel):
    event_name: ClassVar[NovaEventType] = NovaEventType.PROMPT_START
    prompt_name: NovaIdentifier
    text_output_configuration: NovaTextConfiguration = Field(
        default_factory=NovaTextConfiguration
    )
    audio_output_configuration: NovaOutputAudioConfiguration
    tool_use_output_configuration: NovaJsonConfiguration | None = None
    tool_configuration: NovaToolConfiguration | None = None


class NovaInputContent(NovaWireModel):
    prompt_name: NovaIdentifier
    content_name: NovaIdentifier


class NovaTextStart(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.CONTENT_START
    type: Literal[NovaContentType.TEXT] = NovaContentType.TEXT
    role: NovaRole
    interactive: bool = Field(strict=True)
    text_input_configuration: NovaTextConfiguration = Field(
        default_factory=NovaTextConfiguration
    )


class NovaAudioStart(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.CONTENT_START
    type: Literal[NovaContentType.AUDIO] = NovaContentType.AUDIO
    role: Literal[NovaRole.USER] = NovaRole.USER
    interactive: Literal[True] = True
    audio_input_configuration: NovaInputAudioConfiguration


class NovaToolResultStart(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.CONTENT_START
    type: Literal[NovaContentType.TOOL] = NovaContentType.TOOL
    role: Literal[NovaRole.TOOL] = NovaRole.TOOL
    interactive: Literal[False] = False
    tool_result_input_configuration: NovaToolResultConfiguration


class NovaTextInput(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.TEXT_INPUT
    content: str = Field(strict=True)


class NovaAudioInput(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.AUDIO_INPUT
    content: str = Field(strict=True)


class NovaToolResult(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.TOOL_RESULT
    content: str = Field(strict=True)


class NovaResultContent(NovaWireModel):
    result: str = Field(strict=True)


class NovaContentEnd(NovaInputContent):
    event_name: ClassVar[NovaEventType] = NovaEventType.CONTENT_END


class NovaPromptEnd(NovaWireModel):
    event_name: ClassVar[NovaEventType] = NovaEventType.PROMPT_END
    prompt_name: NovaIdentifier


class NovaSessionEnd(NovaWireModel):
    event_name: ClassVar[NovaEventType] = NovaEventType.SESSION_END


NovaClientEvent = (
    NovaSessionStart
    | NovaPromptStart
    | NovaTextStart
    | NovaAudioStart
    | NovaToolResultStart
    | NovaTextInput
    | NovaAudioInput
    | NovaToolResult
    | NovaContentEnd
    | NovaPromptEnd
    | NovaSessionEnd
)


def encode_nova_event(event: NovaClientEvent) -> bytes:
    """Serialize one validated vendor event; keep SDK byte framing in the adapter."""
    return json.dumps(
        {
            "event": {
                event.event_name.value: event.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            }
        },
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class NovaCompletionIdentity(NovaWireModel):
    """Vendor extensions are allowed, but never substitute required identity."""

    model_config = ConfigDict(extra="ignore")

    session_id: NovaIdentifier
    prompt_name: NovaIdentifier
    completion_id: NovaIdentifier


class NovaCompletionStart(NovaCompletionIdentity):
    pass


class NovaOutputContent(NovaCompletionIdentity):
    content_id: NovaIdentifier


class NovaGenerationMetadata(NovaWireModel):
    model_config = ConfigDict(extra="ignore")
    generation_stage: NovaGenerationStage


class NovaTextOutputStart(NovaOutputContent):
    type: Literal[NovaContentType.TEXT]
    role: Literal[NovaRole.USER, NovaRole.ASSISTANT]
    additional_model_fields: Json[NovaGenerationMetadata]
    text_output_configuration: NovaTextConfiguration


class NovaAudioOutputStart(NovaOutputContent):
    type: Literal[NovaContentType.AUDIO]
    role: Literal[NovaRole.ASSISTANT]
    audio_output_configuration: NovaAudioConfiguration


class NovaToolOutputStart(NovaOutputContent):
    type: Literal[NovaContentType.TOOL]
    role: Literal[NovaRole.TOOL]
    tool_use_output_configuration: NovaJsonConfiguration


NovaOutputStart = Annotated[
    NovaTextOutputStart | NovaAudioOutputStart | NovaToolOutputStart,
    Field(discriminator="type"),
]


class NovaTextOutput(NovaOutputContent):
    content: str = Field(strict=True)


class NovaAudioOutput(NovaOutputContent):
    content: str = Field(strict=True)


class NovaToolUse(NovaOutputContent):
    tool_use_id: NovaIdentifier
    tool_name: NovaIdentifier
    content: str = Field(strict=True)


class NovaOutputContentEnd(NovaOutputContent):
    type: NovaContentType
    stop_reason: NovaStopReason


class NovaCompletionEnd(NovaCompletionIdentity):
    stop_reason: NovaStopReason


class NovaTokenUsage(NovaWireModel):
    model_config = ConfigDict(extra="ignore")
    speech_tokens: NovaTokenCount
    text_tokens: NovaTokenCount


class NovaUsageTotals(NovaWireModel):
    model_config = ConfigDict(extra="ignore")
    input: NovaTokenUsage
    output: NovaTokenUsage


class NovaUsageDetails(NovaWireModel):
    model_config = ConfigDict(extra="ignore")
    delta: NovaUsageTotals
    total: NovaUsageTotals


class NovaUsageEvent(NovaCompletionIdentity):
    details: NovaUsageDetails
    total_input_tokens: NovaTokenCount
    total_output_tokens: NovaTokenCount
    total_tokens: NovaTokenCount


NovaServerEvent = (
    NovaCompletionStart
    | NovaTextOutputStart
    | NovaAudioOutputStart
    | NovaToolOutputStart
    | NovaTextOutput
    | NovaAudioOutput
    | NovaToolUse
    | NovaOutputContentEnd
    | NovaCompletionEnd
    | NovaUsageEvent
)
_OUTPUT_START = TypeAdapter(NovaOutputStart)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class NovaEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: dict[str, JsonValue] = Field(min_length=1, max_length=1)


def _reject_constant(value: str) -> float:
    raise ValueError("Non-finite JSON number.")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number.")
    return number


def _json_object(payload: str | bytes) -> dict[str, JsonValue]:
    return _JSON_OBJECT.validate_python(
        json.loads(payload, parse_constant=_reject_constant, parse_float=_finite_float),
        strict=True,
    )


def parse_nova_tool_arguments(payload: str) -> dict[str, JsonValue]:
    """Malformed or non-object tool input is never replaced with empty arguments."""
    try:
        return _json_object(payload)
    except (ValueError, ValidationError, RecursionError) as error:
        raise NovaProtocolError(NovaProtocolFailure.INVALID_ARGUMENTS) from error


def parse_nova_event(payload: bytes) -> NovaServerEvent | None:
    """Validate known events before dispatch; tolerate unrelated future event names."""
    try:
        envelope = NovaEnvelope.model_validate(_json_object(payload))
        name, data = next(iter(envelope.event.items()))
        try:
            kind = NovaEventType(name)
        except ValueError:
            return None
        match kind:
            case NovaEventType.COMPLETION_START:
                return NovaCompletionStart.model_validate(data)
            case NovaEventType.CONTENT_START:
                return _OUTPUT_START.validate_python(data)
            case NovaEventType.TEXT_OUTPUT:
                return NovaTextOutput.model_validate(data)
            case NovaEventType.AUDIO_OUTPUT:
                return NovaAudioOutput.model_validate(data)
            case NovaEventType.TOOL_USE:
                return NovaToolUse.model_validate(data)
            case NovaEventType.CONTENT_END:
                return NovaOutputContentEnd.model_validate(data)
            case NovaEventType.COMPLETION_END:
                return NovaCompletionEnd.model_validate(data)
            case NovaEventType.USAGE:
                return NovaUsageEvent.model_validate(data)
            case _:
                return None
    except (ValueError, ValidationError, RecursionError) as error:
        raise NovaProtocolError(NovaProtocolFailure.MALFORMED_EVENT) from error
