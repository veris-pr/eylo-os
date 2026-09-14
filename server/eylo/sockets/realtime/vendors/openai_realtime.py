"""OpenAI realtime WebSocket adapter with native wire contracts.

Audio is PCM 24kHz in/out; browser input is resampled from 16kHz.
Vendor event objects are translated here, never passed to platform pipelines.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import AsyncIterator
from typing import Final, Literal, TypeAlias
from urllib.parse import urlencode

import websockets
from openai.types.realtime import (
    AudioTranscription,
    ConversationItemCreateEvent,
    ConversationItemInputAudioTranscriptionCompletedEvent,
    InputAudioBufferAppendEvent,
    InputAudioBufferSpeechStartedEvent,
    RealtimeAudioConfig,
    RealtimeAudioConfigInput,
    RealtimeAudioConfigOutput,
    RealtimeConversationItemFunctionCall,
    RealtimeConversationItemFunctionCallOutput,
    RealtimeErrorEvent,
    RealtimeFunctionTool,
    RealtimeResponseCreateParams,
    RealtimeSessionCreateRequest,
    RealtimeToolsConfig,
    ResponseAudioDeltaEvent,
    ResponseAudioTranscriptDeltaEvent,
    ResponseAudioTranscriptDoneEvent,
    ResponseCreateEvent,
    ResponseDoneEvent,
    ResponseFunctionCallArgumentsDoneEvent,
    ResponseOutputItemAddedEvent,
    SessionUpdateEvent,
)
from openai.types.realtime.realtime_audio_formats import AudioPCM
from openai.types.realtime.realtime_audio_input_turn_detection import ServerVad
from pydantic import TypeAdapter

from eylo.audio.ops import StreamingResampler
from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.vendors.openai_utils import extract_openai_function_declarations
from eylo.sockets.realtime.base import (
    RealtimeAdapter,
    RealtimeCapabilities,
    RealtimeSessionUpdateMode,
)
from eylo.sockets.realtime.config import RealtimeSessionConfig
from eylo.sockets.realtime.events import (
    VENDOR_OUTPUT_SAMPLE_RATE,
    AudioDataEvent,
    ErrorEvent,
    InputTranscriptEvent,
    OutputTranscriptEvent,
    RealtimeEvent,
    SessionStartedEvent,
    ToolCallEvent,
    TurnCompleteEvent,
    UserSpeechStartedEvent,
)
from eylo.sockets.realtime.vendors.openai_wire import (
    OpenAIRealtimeEventType,
    OpenAIRealtimeProtocolError,
    OpenAIRealtimeProtocolFailure,
    OpenAIRealtimeServerEvent,
    OpenAIRealtimeSessionEvent,
    OpenAIRealtimeStreamState,
    OpenAIRealtimeToolIdentity,
    parse_openai_realtime_event,
    parse_openai_tool_arguments,
)

logger = logging.getLogger(__name__)

_OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
_OPENAI_PCM_RATE: Final[Literal[24000]] = 24000
_RESPONSE_COMPLETED: Final[Literal["completed"]] = "completed"
_RESPONSE_FAILED: Final[Literal["failed"]] = "failed"
_RESPONSE_INCOMPLETE: Final[Literal["incomplete"]] = "incomplete"
_INVALID_REQUEST_ERROR = "invalid_request_error"

_OpenAIClientEvent: TypeAlias = (
    InputAudioBufferAppendEvent
    | SessionUpdateEvent
    | ConversationItemCreateEvent
    | ResponseCreateEvent
)
_CLIENT_EVENT = TypeAdapter(_OpenAIClientEvent)


def _resample_16k_to_24k(audio_16k: bytes, resampler: StreamingResampler) -> bytes:
    """Use the session-owned resampler; PCM frames may arrive in uneven chunks."""
    return resampler.process(audio_16k)


class OpenAIRealtimeAdapter(RealtimeAdapter):
    def __init__(self, config: RealtimeSessionConfig, *, api_key: str) -> None:
        super().__init__(config)
        self._api_key = api_key
        self._ws: websockets.ClientConnection | None = None
        self._stream = OpenAIRealtimeStreamState()
        self._upsampler = StreamingResampler(from_rate=16000, to_rate=_OPENAI_PCM_RATE)

    @property
    def capabilities(self) -> RealtimeCapabilities:
        return RealtimeCapabilities(
            session_update_mode=RealtimeSessionUpdateMode.IN_PLACE
        )

    async def connect(self) -> None:
        url = f"{_OPENAI_REALTIME_URL}?{urlencode({'model': self._config.model})}"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        self._ws = await websockets.connect(url, additional_headers=headers)
        await self._send_session_update()
        self._connected = True
        logger.info("OpenAI Realtime connected", extra={"model": self._config.model})

    async def verify_ready(self) -> None:
        """Require a valid session acknowledgement, not just its event label."""
        if not self._connected or not self._ws:
            raise RuntimeError("OpenAI Realtime session is not connected.")
        while True:
            event = parse_openai_realtime_event(await self._ws.recv())
            if (
                isinstance(event, OpenAIRealtimeSessionEvent)
                and event.type == OpenAIRealtimeEventType.SESSION_UPDATED
            ):
                return
            if isinstance(event, RealtimeErrorEvent):
                raise RuntimeError("OpenAI Realtime rejected the session config.")

    async def disconnect(self) -> None:
        self._connected = False
        self._stream.pending_tools.clear()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("OpenAI WebSocket close error ignored")
            finally:
                self._ws = None

    async def _send(self, event: _OpenAIClientEvent) -> None:
        """Validate SDK objects again before JSON serialization; preserve omitted fields."""
        if self._ws is None:
            return
        validated = _CLIENT_EVENT.validate_python(
            event.model_dump(exclude_unset=True), strict=True
        )
        await self._ws.send(
            validated.model_dump_json(exclude_unset=True, exclude_none=True)
        )

    async def send_audio(self, audio_data: bytes) -> None:
        if self._ws is None:
            return
        resampled = _resample_16k_to_24k(audio_data, self._upsampler)
        await self._send(
            InputAudioBufferAppendEvent(
                type="input_audio_buffer.append",
                audio=base64.b64encode(resampled).decode("ascii"),
            )
        )

    async def request_speech(self, text: str) -> None:
        """Trigger one audio response with per-response instructions."""
        if self._ws is None:
            raise RuntimeError("OpenAI Realtime session is not connected.")
        await self._send(
            ResponseCreateEvent(
                type="response.create",
                response=RealtimeResponseCreateParams(
                    instructions=(
                        "Speak exactly the following message, without adding "
                        f"anything: {text}"
                    ),
                ),
            )
        )

    async def receive(self) -> AsyncIterator[RealtimeEvent]:
        if self._ws is None:
            return
        try:
            async for raw in self._ws:
                event = parse_openai_realtime_event(raw)
                if event is not None:
                    for translated in self._translate(event):
                        yield translated
        except websockets.ConnectionClosed:
            logger.warning("OpenAI WebSocket closed")
            yield ErrorEvent(
                message="OpenAI WebSocket closed",
                code="connection_closed",
                is_recoverable=False,
            )
        except Exception as error:
            logger.error(
                "OpenAI receive failed",
                extra={"error_type": type(error).__name__},
            )
            yield ErrorEvent(
                message="OpenAI receive failed",
                code="receive_error",
                is_recoverable=False,
            )

    async def send_tool_result(self, tool_call_id: str, result: str) -> None:
        if self._ws is None:
            return
        await self._send(
            ConversationItemCreateEvent(
                type="conversation.item.create",
                item=RealtimeConversationItemFunctionCallOutput(
                    type="function_call_output", call_id=tool_call_id, output=result
                ),
            )
        )
        # A function result is input to a new response, not the end of the turn.
        await self._send(ResponseCreateEvent(type="response.create"))

    async def update_session(
        self,
        *,
        system_prompt: str | None = None,
        tools: list[ToolRecord] | None = None,
        voice: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Apply supported settings without reconnect; commit locally only after send."""
        if self._ws is None:
            return
        if temperature is not None:
            raise ValueError("OpenAI Realtime does not support temperature.")
        updated = self._config.updated(
            system_prompt=system_prompt, tools=tools, voice=voice
        )
        if system_prompt is None and tools is None and voice is None:
            return
        await self._send(
            SessionUpdateEvent(
                type="session.update",
                session=RealtimeSessionCreateRequest(
                    type="realtime",
                    instructions=updated.system_prompt
                    if system_prompt is not None
                    else None,
                    tools=self._format_tools(updated.tools)
                    if tools is not None
                    else None,
                    audio=RealtimeAudioConfig(
                        output=RealtimeAudioConfigOutput(voice=updated.voice)
                    )
                    if voice is not None
                    else None,
                ),
            )
        )
        self._config = updated

    async def _send_session_update(self) -> None:
        """Build only explicitly configured options; absent values retain vendor semantics."""
        config = self._config
        audio_format = AudioPCM(type="audio/pcm", rate=_OPENAI_PCM_RATE)
        await self._send(
            SessionUpdateEvent(
                type="session.update",
                session=RealtimeSessionCreateRequest(
                    type="realtime",
                    instructions=config.system_prompt,
                    output_modalities=["audio"],
                    audio=RealtimeAudioConfig(
                        input=RealtimeAudioConfigInput(
                            format=audio_format,
                            transcription=AudioTranscription(
                                model=config.input_transcription_model
                            )
                            if config.input_transcription_model is not None
                            else None,
                            turn_detection=ServerVad(
                                type="server_vad",
                                create_response=True,
                                interrupt_response=True,
                                threshold=config.vad_threshold,
                                silence_duration_ms=config.vad_silence_ms,
                            ),
                        ),
                        output=RealtimeAudioConfigOutput(
                            format=audio_format, voice=config.voice
                        ),
                    ),
                    tools=self._format_tools() or None,
                ),
            )
        )

    def _format_tools(
        self, tools: list[ToolRecord] | None = None
    ) -> RealtimeToolsConfig:
        """Use the native flat function format, without Chat's wrapper or strict flag."""
        declarations = extract_openai_function_declarations(
            tools if tools is not None else self._config.tools
        )
        return [
            RealtimeFunctionTool(
                type="function",
                name=declaration["name"],
                description=declaration.get("description"),
                parameters=declaration.get("parameters"),
            )
            for declaration in declarations
        ]

    def _translate(self, event: OpenAIRealtimeServerEvent) -> list[RealtimeEvent]:
        """Consume validated native events; only normalized values leave the adapter."""
        if isinstance(event, OpenAIRealtimeSessionEvent):
            if event.type == OpenAIRealtimeEventType.SESSION_CREATED:
                return [SessionStartedEvent(session_id=event.session.id)]
        elif isinstance(event, ResponseAudioDeltaEvent):
            try:
                audio = base64.b64decode(event.delta, validate=True)
            except (binascii.Error, ValueError):
                raise OpenAIRealtimeProtocolError(
                    OpenAIRealtimeProtocolFailure.INVALID_AUDIO
                ) from None
            if audio:
                return [
                    AudioDataEvent(audio=audio, sample_rate=VENDOR_OUTPUT_SAMPLE_RATE)
                ]
        elif isinstance(event, ResponseAudioTranscriptDeltaEvent):
            return [OutputTranscriptEvent(text=event.delta, is_final=False)]
        elif isinstance(event, ResponseAudioTranscriptDoneEvent):
            return [OutputTranscriptEvent(text=event.transcript, is_final=True)]
        elif isinstance(event, ConversationItemInputAudioTranscriptionCompletedEvent):
            return [InputTranscriptEvent(text=event.transcript, is_final=True)]
        elif isinstance(event, ResponseOutputItemAddedEvent):
            if isinstance(event.item, RealtimeConversationItemFunctionCall):
                if not event.item.call_id or not event.item.id:
                    raise OpenAIRealtimeProtocolError(
                        OpenAIRealtimeProtocolFailure.TOOL_IDENTITY_MISMATCH
                    )
                self._stream.pending_tools[event.item.call_id] = (
                    OpenAIRealtimeToolIdentity(
                        response_id=event.response_id,
                        item_id=event.item.id,
                        name=event.item.name,
                    )
                )
        elif isinstance(event, ResponseFunctionCallArgumentsDoneEvent):
            identity = self._stream.pending_tools.pop(event.call_id, None)
            if (
                identity is None
                or identity.response_id != event.response_id
                or identity.item_id != event.item_id
            ):
                raise OpenAIRealtimeProtocolError(
                    OpenAIRealtimeProtocolFailure.TOOL_IDENTITY_MISMATCH
                )
            return [
                ToolCallEvent(
                    tool_call_id=event.call_id,
                    tool_name=identity.name,
                    arguments=parse_openai_tool_arguments(event.arguments),
                )
            ]
        elif isinstance(event, ResponseDoneEvent):
            response = event.response
            self._stream.finish_response(response.id)
            events: list[RealtimeEvent] = []
            if response.status in {_RESPONSE_FAILED, _RESPONSE_INCOMPLETE}:
                events.append(
                    ErrorEvent(
                        message="OpenAI Realtime response did not complete",
                        code=f"response_{response.status}",
                        is_recoverable=True,
                    )
                )
            has_tool_calls = any(
                isinstance(item, RealtimeConversationItemFunctionCall)
                for item in response.output or ()
            )
            if (
                response.status is not None and response.status != _RESPONSE_COMPLETED
            ) or not has_tool_calls:
                events.append(TurnCompleteEvent())
            return events
        elif isinstance(event, InputAudioBufferSpeechStartedEvent):
            return [UserSpeechStartedEvent()]
        elif isinstance(event, RealtimeErrorEvent):
            return [
                ErrorEvent(
                    message=event.error.message,
                    code=event.error.code or "",
                    is_recoverable=event.error.type != _INVALID_REQUEST_ERROR,
                )
            ]
        return []
