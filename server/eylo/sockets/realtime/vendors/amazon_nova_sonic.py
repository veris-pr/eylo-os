"""Amazon Nova 2 Sonic bidirectional speech adapter.

The adapter owns Bedrock's event protocol. Eylo's turn, interruption, tool,
recording, and call-lifecycle policy remains in ``pipelines.voice``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable
from enum import StrEnum
from typing import Literal, TypeVar
from uuid import uuid4

from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
from aws_sdk_bedrock_runtime.config import Config
from aws_sdk_bedrock_runtime.models import (
    BidirectionalInputPayloadPart,
    InvokeModelWithBidirectionalStreamInput,
    InvokeModelWithBidirectionalStreamInputChunk,
    InvokeModelWithBidirectionalStreamOperationInput,
    InvokeModelWithBidirectionalStreamOperationOutput,
    InvokeModelWithBidirectionalStreamOutput,
    InvokeModelWithBidirectionalStreamOutputChunk,
    InvokeModelWithBidirectionalStreamOutputInternalServerException,
    InvokeModelWithBidirectionalStreamOutputModelStreamErrorException,
    InvokeModelWithBidirectionalStreamOutputModelTimeoutException,
    InvokeModelWithBidirectionalStreamOutputServiceUnavailableException,
    InvokeModelWithBidirectionalStreamOutputThrottlingException,
    InvokeModelWithBidirectionalStreamOutputValidationException,
)
from pydantic import BaseModel, ConfigDict, Field
from smithy_aws_core.identity import StaticCredentialsResolver
from smithy_core.aio.eventstream import DuplexEventStream
from smithy_core.aio.interfaces.eventstream import EventReceiver

from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.llm.vendors.openai_utils import (
    extract_openai_function_declarations,
)
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
    GoAwayEvent,
    InputTranscriptEvent,
    InterruptionEvent,
    OutputTranscriptEvent,
    RealtimeEvent,
    SessionStartedEvent,
    ToolCallEvent,
    TurnCompleteEvent,
)
from eylo.sockets.realtime.vendors import amazon_nova_sonic_wire as wire

logger = logging.getLogger(__name__)

_INPUT_AUDIO_CONFIG = wire.NovaInputAudioConfiguration(sample_rate_hertz=16000)
_SESSION_LIMIT_SECONDS = 8 * 60
_TURN_BOUNDARY_ROTATION_SECONDS = 7 * 60
_FORCED_ROTATION_SECONDS = 7 * 60 + 45
_SDK_RECEIVE_DRAIN_SECONDS = 5.0
_SDK_CLOSE_SECONDS = 10.0

NovaStream = DuplexEventStream[
    InvokeModelWithBidirectionalStreamInput,
    InvokeModelWithBidirectionalStreamOutput,
    InvokeModelWithBidirectionalStreamOperationOutput,
]
NovaOutput = tuple[
    InvokeModelWithBidirectionalStreamOperationOutput,
    EventReceiver[InvokeModelWithBidirectionalStreamOutput],
]
_SDKResult = TypeVar("_SDKResult")


class NovaStreamError(StrEnum):
    INTERNAL_SERVER = "InternalServer"
    MODEL_TIMEOUT = "ModelTimeout"
    SERVICE_UNAVAILABLE = "ServiceUnavailable"
    THROTTLING = "Throttling"
    VALIDATION = "Validation"
    MODEL_STREAM = "ModelStreamError"
    UNKNOWN = "stream_error"


class NovaContentState(BaseModel):
    """One validated output block and its text fragments, owned by this stream."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    start: wire.NovaOutputStart
    fragments: list[str] = Field(default_factory=list)


class NovaHistoryEntry(BaseModel):
    """Only final user/spoken assistant text is eligible for reconnect replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal[wire.NovaRole.USER, wire.NovaRole.ASSISTANT]
    text: str


def _consume_detached_sdk_result(task: asyncio.Future[_SDKResult]) -> None:
    """Consume a shielded SDK await after Eylo stops waiting for it."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as error:
        logger.debug(
            "Detached Amazon Nova operation completed with error_type=%s",
            type(error).__name__,
        )


async def _await_cancellation_unsafe_sdk(
    operation: Awaitable[_SDKResult],
    pending_tasks: set[asyncio.Future[_SDKResult]],
) -> _SDKResult:
    """Keep task cancellation out of AWS CRT response futures.

    AWS CRT's response-body callback does not guard ``Future.set_result``
    against cancellation. Shielding its awaitable lets Eylo stop its consumer
    immediately without corrupting the SDK-owned future while the stream
    receives the session-end response.
    """
    task = asyncio.ensure_future(operation)
    pending_tasks.add(task)
    task.add_done_callback(pending_tasks.discard)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(_consume_detached_sdk_result)
        raise


class AmazonNovaSonicAdapter(RealtimeAdapter):
    """Translate Nova Sonic's event stream to Eylo's Realtime contract."""

    def __init__(
        self,
        config: RealtimeSessionConfig,
        *,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        session_token: str | None = None,
    ) -> None:
        super().__init__(config)
        sdk_config = Config(
            endpoint_uri=f"https://bedrock-runtime.{region}.amazonaws.com",
            region=region,
            aws_access_key_id=access_key_id,
            aws_credentials_identity_resolver=StaticCredentialsResolver(),
            aws_secret_access_key=secret_access_key,
            aws_session_token=session_token,
        )
        self._client = BedrockRuntimeClient(config=sdk_config)
        self._stream: NovaStream | None = None
        self._send_lock = asyncio.Lock()
        self._generation = 0
        self._session_started_emitted = False
        self._prompt_name = ""
        self._audio_content_name = ""
        self._content_state: dict[str, NovaContentState] = {}
        self._conversation_history: list[NovaHistoryEntry] = []
        self._pending_tools: dict[str, wire.NovaToolUse] = {}
        self._session_id: str | None = None
        self._pending_policy_inputs: list[frozenset[str]] = []
        self._sdk_output_tasks: set[asyncio.Future[NovaOutput]] = set()
        self._sdk_receive_tasks: set[
            asyncio.Future[InvokeModelWithBidirectionalStreamOutput | None]
        ] = set()
        self._sdk_close_tasks: set[asyncio.Future[None]] = set()
        self._connected_at = 0.0
        self._rotation_requested = False

    @property
    def capabilities(self) -> RealtimeCapabilities:
        return RealtimeCapabilities(
            session_update_mode=RealtimeSessionUpdateMode.RECONNECT
        )

    async def connect(self) -> None:
        if self._connected:
            return
        self._generation += 1
        self._prompt_name = str(uuid4())
        self._audio_content_name = str(uuid4())
        self._content_state.clear()
        self._pending_tools.clear()
        self._session_id = None
        self._session_started_emitted = False
        self._rotation_requested = False

        stream = await self._client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(
                model_id=self._config.model
            )
        )
        self._stream = stream
        try:
            await self._send_initial_events()
        except BaseException:
            self._stream = None
            await self._close_stream(stream)
            raise
        self._connected = True
        self._connected_at = time.monotonic()
        logger.info(
            "Amazon Nova 2 Sonic connected",
            extra={"model": self._config.model},
        )

    async def verify_ready(self) -> None:
        """Validate Nova's authenticated stream and ordered session setup.

        Nova emits its first output only after user audio. ``connect`` already
        invokes the model stream and sends the complete session/prompt/audio
        input preamble, so those successful operations are its non-invasive
        readiness proof.
        """
        if not self._connected or self._stream is None:
            raise RuntimeError("Amazon Nova 2 Sonic session is not connected.")

    async def disconnect(self) -> None:
        stream = self._stream
        self._connected = False
        self._stream = None
        try:
            if stream is not None:
                try:
                    async with self._send_lock:
                        for event in (
                            self._content_end(self._audio_content_name),
                            wire.NovaPromptEnd(prompt_name=self._prompt_name),
                            wire.NovaSessionEnd(),
                        ):
                            await self._send_event_to_stream(stream, event)
                except Exception as error:
                    logger.debug(
                        "Amazon Nova 2 Sonic close events failed error_type=%s",
                        type(error).__name__,
                    )
                finally:
                    await self._close_stream(stream)
        finally:
            self._content_state.clear()
            self._pending_tools.clear()
            self._session_id = None
            self._session_started_emitted = False
            self._pending_policy_inputs.clear()

    async def _close_stream(self, stream: NovaStream) -> None:
        """Bound caller wait; keep late SDK cleanup owned and shielded."""
        try:
            async with asyncio.timeout(_SDK_CLOSE_SECONDS):
                await _await_cancellation_unsafe_sdk(
                    self._close_native_stream(stream), self._sdk_close_tasks
                )
        except TimeoutError:
            logger.warning(
                "Amazon Nova 2 Sonic close exceeded %.1fs; "
                "tracked native cleanup continues in background.",
                _SDK_CLOSE_SECONDS,
            )

    async def _close_native_stream(self, stream: NovaStream) -> None:
        """Include output acquired after setup failed, not only an exposed receiver."""
        try:
            await stream.input_stream.close()
        except Exception as error:
            logger.debug(
                "Amazon Nova 2 Sonic input close failed error_type=%s",
                type(error).__name__,
            )
        await self._drain_sdk_receive_tasks()
        try:
            _, output_stream = await stream.await_output()
            await output_stream.close()
        except Exception as error:
            logger.debug(
                "Amazon Nova 2 Sonic output close failed error_type=%s",
                type(error).__name__,
            )

    async def _drain_sdk_receive_tasks(self) -> None:
        """Let native response callbacks settle without cancelling their futures."""
        pending = {
            task
            for task in (*self._sdk_output_tasks, *self._sdk_receive_tasks)
            if not task.done()
        }
        if not pending:
            return
        _, still_pending = await asyncio.wait(
            pending,
            timeout=_SDK_RECEIVE_DRAIN_SECONDS,
        )
        if still_pending:
            logger.warning(
                "Amazon Nova 2 Sonic response drain exceeded %.1fs; "
                "native reads continue in background.",
                _SDK_RECEIVE_DRAIN_SECONDS,
            )

    async def send_audio(self, audio_data: bytes) -> None:
        if not audio_data:
            return
        await self._send_event(
            wire.NovaAudioInput(
                prompt_name=self._prompt_name,
                content_name=self._audio_content_name,
                content=base64.b64encode(audio_data).decode("ascii"),
            )
        )

    async def request_speech(self, text: str) -> None:
        if not self._connected:
            raise RuntimeError("Amazon Nova 2 Sonic session is not connected.")
        instruction = (
            "Speak exactly the following message, without adding anything: "
            f"{json.dumps(text, ensure_ascii=False)}"
        )
        self._pending_policy_inputs.append(
            frozenset(
                filter(None, {_normalize_text(instruction), _normalize_text(text)})
            )
        )
        await self._send_text_sequence(
            role=wire.NovaRole.USER,
            text=instruction,
            mode=wire.NovaTextMode.INTERACTIVE,
        )

    async def receive(self) -> AsyncIterator[RealtimeEvent]:
        stream = self._stream
        generation = self._generation
        if stream is None:
            return
        try:
            while self._connected and generation == self._generation:
                rotation_timeout = max(
                    0.0,
                    _FORCED_ROTATION_SECONDS - (time.monotonic() - self._connected_at),
                )
                try:
                    async with asyncio.timeout(rotation_timeout):
                        output = await _await_cancellation_unsafe_sdk(
                            stream.await_output(),
                            self._sdk_output_tasks,
                        )
                        result = await _await_cancellation_unsafe_sdk(
                            output[1].receive(),
                            self._sdk_receive_tasks,
                        )
                except TimeoutError:
                    if not self._connected or generation != self._generation:
                        return
                    self._rotation_requested = True
                    yield GoAwayEvent(time_left_ms=self._rotation_time_left_ms())
                    return
                if not self._connected or generation != self._generation:
                    return
                if result is None:
                    return
                if isinstance(result, InvokeModelWithBidirectionalStreamOutputChunk):
                    payload = result.value.bytes_
                    if payload is None:
                        raise wire.NovaProtocolError(
                            wire.NovaProtocolFailure.MALFORMED_EVENT
                        )
                    for event in self._translate(wire.parse_nova_event(payload)):
                        yield event
                    continue
                error = self._translate_stream_error(result)
                yield error
                if not error.is_recoverable:
                    return
        except wire.NovaProtocolError as error:
            yield ErrorEvent(
                message=str(error),
                code=error.code.value,
                is_recoverable=False,
            )
        except StopAsyncIteration:
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._connected and generation == self._generation:
                logger.error(
                    "Amazon Nova 2 Sonic receive failed error_type=%s",
                    type(error).__name__,
                )
                yield ErrorEvent(
                    message="Amazon Nova 2 Sonic receive failed",
                    code="receive_error",
                    is_recoverable=False,
                )

    async def send_tool_result(self, tool_call_id: str, result: str) -> None:
        if tool_call_id not in self._pending_tools:
            raise wire.NovaProtocolError(wire.NovaProtocolFailure.IDENTITY_MISMATCH)
        content_name = str(uuid4())
        await self._send_events(
            [
                wire.NovaToolResultStart(
                    prompt_name=self._prompt_name,
                    content_name=content_name,
                    tool_result_input_configuration=wire.NovaToolResultConfiguration(
                        tool_use_id=tool_call_id
                    ),
                ),
                wire.NovaToolResult(
                    prompt_name=self._prompt_name,
                    content_name=content_name,
                    content=wire.NovaResultContent(result=result).model_dump_json(),
                ),
                self._content_end(content_name),
            ]
        )
        self._pending_tools.pop(tool_call_id, None)

    async def update_session(
        self,
        *,
        system_prompt: str | None = None,
        tools: list[ToolRecord] | None = None,
        voice: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Reconnect and replay finalized history for handoffs/config changes."""
        updated = self._config.updated(
            system_prompt=system_prompt,
            tools=tools,
            voice=voice,
            temperature=temperature,
        )
        await self.disconnect()
        self._config = updated
        await self.connect()

    async def _send_initial_events(self) -> None:
        max_tokens = self._config.max_tokens
        top_p = self._config.top_p
        temperature = self._config.temperature
        endpointing_sensitivity = self._config.endpointing_sensitivity
        if max_tokens is None:
            raise RuntimeError("Amazon Nova 2 Sonic requires max_tokens.")
        if top_p is None:
            raise RuntimeError("Amazon Nova 2 Sonic requires top_p.")
        if temperature is None:
            raise RuntimeError("Amazon Nova 2 Sonic requires temperature.")
        if endpointing_sensitivity is None:
            raise RuntimeError("Amazon Nova 2 Sonic requires endpointing_sensitivity.")
        session_start = wire.NovaSessionStart(
            inference_configuration=wire.NovaInferenceConfiguration(
                max_tokens=max_tokens, top_p=top_p, temperature=temperature
            ),
            turn_detection_configuration=wire.NovaTurnDetectionConfiguration(
                endpointing_sensitivity=wire.NovaEndpointingSensitivity(
                    endpointing_sensitivity.value
                )
            ),
        )
        tools = self._format_tools()
        prompt_start = wire.NovaPromptStart(
            prompt_name=self._prompt_name,
            audio_output_configuration=wire.NovaOutputAudioConfiguration(
                sample_rate_hertz=VENDOR_OUTPUT_SAMPLE_RATE, voice_id=self._config.voice
            ),
            tool_use_output_configuration=wire.NovaJsonConfiguration()
            if tools
            else None,
            tool_configuration=wire.NovaToolConfiguration(tools=tools)
            if tools
            else None,
        )
        await self._send_events([session_start, prompt_start])
        if self._config.system_prompt.strip():
            await self._send_text_sequence(
                role=wire.NovaRole.SYSTEM,
                text=self._config.system_prompt,
                mode=wire.NovaTextMode.HISTORY,
            )
        for entry in self._replayable_history():
            await self._send_text_sequence(
                role=entry.role, text=entry.text, mode=wire.NovaTextMode.HISTORY
            )
        await self._send_event(
            wire.NovaAudioStart(
                prompt_name=self._prompt_name,
                content_name=self._audio_content_name,
                audio_input_configuration=_INPUT_AUDIO_CONFIG,
            )
        )

    async def _send_text_sequence(
        self,
        *,
        role: wire.NovaRole,
        text: str,
        mode: wire.NovaTextMode,
    ) -> None:
        content_name = str(uuid4())
        await self._send_events(
            [
                wire.NovaTextStart(
                    prompt_name=self._prompt_name,
                    content_name=content_name,
                    role=role,
                    interactive=mode is wire.NovaTextMode.INTERACTIVE,
                ),
                wire.NovaTextInput(
                    prompt_name=self._prompt_name,
                    content_name=content_name,
                    content=text,
                ),
                self._content_end(content_name),
            ]
        )

    async def _send_event(self, event: wire.NovaClientEvent) -> None:
        await self._send_events([event])

    async def _send_events(self, events: list[wire.NovaClientEvent]) -> None:
        stream = self._stream
        if stream is None:
            raise RuntimeError("Amazon Nova 2 Sonic session is not connected.")
        async with self._send_lock:
            for event in events:
                await self._send_event_to_stream(stream, event)

    @staticmethod
    async def _send_event_to_stream(
        stream: NovaStream, event: wire.NovaClientEvent
    ) -> None:
        payload = wire.encode_nova_event(event)
        await stream.input_stream.send(
            InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=payload)
            )
        )

    def _content_end(self, content_name: str) -> wire.NovaContentEnd:
        return wire.NovaContentEnd(
            prompt_name=self._prompt_name, content_name=content_name
        )

    def _format_tools(self) -> tuple[wire.NovaToolDefinition, ...]:
        declarations = extract_openai_function_declarations(self._config.tools)
        return tuple(
            wire.NovaToolDefinition(
                tool_spec=wire.NovaToolSpec(
                    name=declaration["name"],
                    description=declaration.get("description", ""),
                    input_schema=wire.NovaToolInputSchema(
                        json=json.dumps(
                            declaration.get("parameters", {}), allow_nan=False
                        )
                    ),
                )
            )
            for declaration in declarations
        )

    def _translate(self, event: wire.NovaServerEvent | None) -> list[RealtimeEvent]:
        if event is None:
            return []
        if event.prompt_name != self._prompt_name or (
            self._session_id is not None and event.session_id != self._session_id
        ):
            raise wire.NovaProtocolError(wire.NovaProtocolFailure.IDENTITY_MISMATCH)
        if isinstance(event, (wire.NovaCompletionStart, wire.NovaUsageEvent)):
            self._session_id = event.session_id
            if self._session_started_emitted:
                return []
            self._session_started_emitted = True
            return [SessionStartedEvent(session_id=event.session_id)]
        if isinstance(
            event,
            (
                wire.NovaTextOutputStart,
                wire.NovaAudioOutputStart,
                wire.NovaToolOutputStart,
            ),
        ):
            if event.content_id in self._content_state:
                raise wire.NovaProtocolError(wire.NovaProtocolFailure.CONTENT_MISMATCH)
            if isinstance(event, wire.NovaAudioOutputStart) and (
                event.audio_output_configuration.sample_rate_hertz
                != VENDOR_OUTPUT_SAMPLE_RATE
            ):
                raise wire.NovaProtocolError(wire.NovaProtocolFailure.INVALID_AUDIO)
            self._content_state[event.content_id] = NovaContentState(start=event)
            return []
        if isinstance(event, wire.NovaTextOutput):
            state = self._content_for(event, wire.NovaContentType.TEXT)
            state.fragments.append(event.content)
            return []
        if isinstance(event, wire.NovaAudioOutput):
            self._content_for(event, wire.NovaContentType.AUDIO)
            try:
                audio = base64.b64decode(event.content, validate=True)
            except ValueError:
                return [
                    ErrorEvent(
                        message="Amazon Nova 2 Sonic returned invalid audio",
                        code=wire.NovaProtocolFailure.INVALID_AUDIO.value,
                        is_recoverable=True,
                    )
                ]
            return (
                [AudioDataEvent(audio=audio, sample_rate=VENDOR_OUTPUT_SAMPLE_RATE)]
                if audio
                else []
            )
        if isinstance(event, wire.NovaToolUse):
            self._content_for(event, wire.NovaContentType.TOOL)
            arguments = wire.parse_nova_tool_arguments(event.content)
            if event.tool_use_id in self._pending_tools:
                raise wire.NovaProtocolError(wire.NovaProtocolFailure.IDENTITY_MISMATCH)
            self._pending_tools[event.tool_use_id] = event
            return [
                ToolCallEvent(
                    tool_call_id=event.tool_use_id,
                    tool_name=event.tool_name,
                    arguments=arguments,
                )
            ]
        if isinstance(event, wire.NovaOutputContentEnd):
            return self._translate_content_end(event)
        if isinstance(event, wire.NovaCompletionEnd):
            self._content_state = {
                key: state
                for key, state in self._content_state.items()
                if state.start.completion_id != event.completion_id
            }
            if event.stop_reason not in {
                wire.NovaStopReason.END_TURN,
                wire.NovaStopReason.INTERRUPTED,
            }:
                return []
            events: list[RealtimeEvent] = [TurnCompleteEvent()]
            if (
                not self._rotation_requested
                and time.monotonic() - self._connected_at
                >= _TURN_BOUNDARY_ROTATION_SECONDS
            ):
                self._rotation_requested = True
                events.append(GoAwayEvent(time_left_ms=self._rotation_time_left_ms()))
            return events
        return []

    def _content_for(
        self, event: wire.NovaOutputContent, kind: wire.NovaContentType
    ) -> NovaContentState:
        state = self._content_state.get(event.content_id)
        if state is None or state.start.type is not kind:
            raise wire.NovaProtocolError(wire.NovaProtocolFailure.CONTENT_MISMATCH)
        if (
            state.start.session_id != event.session_id
            or state.start.prompt_name != event.prompt_name
            or state.start.completion_id != event.completion_id
        ):
            raise wire.NovaProtocolError(wire.NovaProtocolFailure.IDENTITY_MISMATCH)
        return state

    def _translate_content_end(
        self, event: wire.NovaOutputContentEnd
    ) -> list[RealtimeEvent]:
        state = self._content_for(event, event.type)
        del self._content_state[event.content_id]
        events: list[RealtimeEvent] = []
        text = "".join(state.fragments).strip()
        start = state.start
        if (
            text
            and isinstance(start, wire.NovaTextOutputStart)
            and start.additional_model_fields.generation_stage
            is wire.NovaGenerationStage.FINAL
        ):
            if start.role is wire.NovaRole.USER:
                normalized = _normalize_text(text)
                matching_policy = next(
                    (
                        candidates
                        for candidates in self._pending_policy_inputs
                        if normalized in candidates
                    ),
                    None,
                )
                if matching_policy is not None:
                    self._pending_policy_inputs.remove(matching_policy)
                else:
                    self._conversation_history.append(
                        NovaHistoryEntry(role=wire.NovaRole.USER, text=text)
                    )
                    events.append(InputTranscriptEvent(text=text, is_final=True))
            else:
                self._conversation_history.append(
                    NovaHistoryEntry(role=wire.NovaRole.ASSISTANT, text=text)
                )
                events.append(OutputTranscriptEvent(text=text, is_final=True))
        if event.stop_reason is wire.NovaStopReason.INTERRUPTED:
            events.append(InterruptionEvent())
        return events

    @staticmethod
    def _translate_stream_error(
        result: InvokeModelWithBidirectionalStreamOutput,
    ) -> ErrorEvent:
        if isinstance(
            result, InvokeModelWithBidirectionalStreamOutputInternalServerException
        ):
            code, recoverable = NovaStreamError.INTERNAL_SERVER, True
        elif isinstance(
            result, InvokeModelWithBidirectionalStreamOutputModelTimeoutException
        ):
            code, recoverable = NovaStreamError.MODEL_TIMEOUT, True
        elif isinstance(
            result, InvokeModelWithBidirectionalStreamOutputServiceUnavailableException
        ):
            code, recoverable = NovaStreamError.SERVICE_UNAVAILABLE, True
        elif isinstance(
            result, InvokeModelWithBidirectionalStreamOutputThrottlingException
        ):
            code, recoverable = NovaStreamError.THROTTLING, True
        elif isinstance(
            result, InvokeModelWithBidirectionalStreamOutputValidationException
        ):
            code, recoverable = NovaStreamError.VALIDATION, False
        elif isinstance(
            result, InvokeModelWithBidirectionalStreamOutputModelStreamErrorException
        ):
            code, recoverable = NovaStreamError.MODEL_STREAM, False
        else:
            code, recoverable = NovaStreamError.UNKNOWN, False
        return ErrorEvent(
            message="Amazon Nova 2 Sonic stream error",
            code=code.value,
            is_recoverable=recoverable,
        )

    def _replayable_history(self) -> list[NovaHistoryEntry]:
        for index, entry in enumerate(self._conversation_history):
            if entry.role is wire.NovaRole.USER:
                return self._conversation_history[index:]
        return []

    def _rotation_time_left_ms(self) -> int:
        elapsed = time.monotonic() - self._connected_at
        return max(0, int((_SESSION_LIMIT_SECONDS - elapsed) * 1000))


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()
