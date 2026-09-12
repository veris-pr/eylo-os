"""Session-local decomposed voice turns with no durable raw message origin."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import ValidationError

from eylo.common.contracts.conversation import HANDOFF_TOOL_PREFIX
from eylo.common.database import start_transaction
from eylo.events.py_events.agent_lifecycle import AgentLifecycleEmitter
from eylo.events.schema.py_events.base import (
    AgentLifecycleEvent,
    AgentLifecycleOutcome,
    AgentProcessingEvent,
    AgentResponseCompleteEvent,
    AgentRunInferenceEvent,
    AgentRunToolEvent,
    AgentToolResponseEvent,
)
from eylo.framework.agents.agent import AgentSpec
from eylo.framework.agents.config import RunConfig, RunStreaming
from eylo.framework.agents.context import RunContext, RunInput, RunMessage
from eylo.framework.agents.hooks import RunCallbacks, RunHooks
from eylo.framework.agents.items import (
    RunItem,
    RunItemKind,
    RunToolCallItem,
    RunToolResultItem,
)
from eylo.framework.agents.model import Model
from eylo.framework.agents.result import RunResult, RunStatus
from eylo.framework.agents.runner import FrameworkRunner
from eylo.framework.agents.tool import ToolCall, ToolExecutor, ToolResult
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageKind,
    MessageMeta,
)
from eylo.modules.conversations.services.conversations import ConversationService
from eylo.modules.llm_configs.wiring import resolve_pinned_llm
from eylo.modules.voice_transcripts.constants import (
    VoiceRuntimeMode,
    VoiceSpeechOutcome,
)
from eylo.pipelines.agent_execution_context import PlatformRunState
from eylo.pipelines.conversation.context import ConversationContextService
from eylo.pipelines.conversation.conversation_runner import ExistingConversationModel
from eylo.pipelines.conversation.domain import (
    ExistingRunMessageMetadata,
    ExistingToolCallMetadata,
    ExistingToolResultMetadata,
    agent_spec_from_context,
    run_input_from_context,
)
from eylo.pipelines.conversation.handoff import (
    completed_handoffs,
    handoff_metadata_from,
)
from eylo.pipelines.llm.runtime import to_llm_inference_mode
from eylo.pipelines.llm.streaming_tts import (
    VoiceTextSegment,
    complete_voice_sessions_for_response,
    deliver_voice_text_segment,
    prepare_voice_sessions_for_inference,
)
from eylo.pipelines.llm.voice_text import VoiceTextPhase
from eylo.pipelines.voice.live_buffer import (
    LiveVoiceBuffer,
    LiveVoiceDraft,
    LiveVoiceItemKind,
)
from eylo.pipelines.voice.live_transcript import schedule_live_message_transcripts
from eylo.pipelines.voice.request_state import VoiceRequestStatus
from eylo.pipelines.voice.tool_executor import (
    LiveVoiceToolExecutor,
    without_live_sandbox_agent_tools,
)

if TYPE_CHECKING:
    from eylo.pipelines.websocket.schemas import WSSessionState

logger = logging.getLogger(__name__)

LiveVoiceModelFactory = Callable[
    [PlatformRunState[ConversationContext], RunConfig], Model
]


class LiveVoiceHistoryError(ValueError):
    """A capture cannot supply a truthful, paired model/tool history."""


class LiveVoiceLifecycleHooks(RunHooks):
    """Project one decomposed voice turn onto the shared agent lifecycle."""

    def __init__(
        self, *, local_context: PlatformRunState[ConversationContext], request_id: UUID
    ) -> None:
        self._local_context = local_context
        self._request_id = request_id
        self._events = AgentLifecycleEmitter()
        self._started = False
        self._terminal = False

    @property
    def current_context(self) -> ConversationContext:
        return self._local_context.conversation_context

    async def on_agent_start(self, context: RunContext, agent: AgentSpec) -> None:
        if self._started:
            return
        self._started = True
        self._emit(AgentProcessingEvent)

    async def on_llm_start(self, context: RunContext, run_input: RunInput) -> None:
        conversation = self.current_context.conversation
        await prepare_voice_sessions_for_inference(
            conversation_id=conversation.id,
            organization_id=conversation.organization_id,
            request_id=self._request_id,
        )
        self._emit(AgentRunInferenceEvent)

    async def on_tool_start(self, context: RunContext, call: ToolCall) -> None:
        self._emit(AgentRunToolEvent)

    async def on_tool_end(
        self,
        context: RunContext,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        self._emit(AgentToolResponseEvent)

    async def on_run_end(self, context: RunContext, result: RunResult) -> None:
        successful = result.status in {
            RunStatus.COMPLETED,
            RunStatus.WAITING_FOR_INPUT,
            RunStatus.WAITING_FOR_APPROVAL,
        }
        await self.finish(
            AgentLifecycleOutcome.COMPLETED
            if successful
            else AgentLifecycleOutcome.FAILED
        )

    async def on_error(self, context: RunContext, error: Exception) -> None:
        await self.finish(AgentLifecycleOutcome.FAILED)

    async def finish(self, outcome: AgentLifecycleOutcome) -> None:
        if self._terminal:
            return
        self._terminal = True
        conversation = self.current_context.conversation
        try:
            await complete_voice_sessions_for_response(
                conversation_id=conversation.id,
                organization_id=conversation.organization_id,
                request_id=self._request_id,
            )
        except Exception as error:
            logger.error(
                "Could not finish decomposed voice lifecycle error_type=%s",
                type(error).__name__,
            )
        finally:
            self._events.emit(
                AgentResponseCompleteEvent,
                context=self.current_context,
                request_id=self._request_id,
                outcome=outcome,
            )

    def _emit(self, event_type: type[AgentLifecycleEvent]) -> None:
        self._events.emit(
            event_type,
            context=self.current_context,
            request_id=self._request_id,
        )


class LiveVoiceTurnRunner:
    """Run decomposed voice turns from live memory, never from raw DB messages."""

    def __init__(
        self,
        live_buffer: LiveVoiceBuffer,
        *,
        session_state: WSSessionState | None = None,
        model_factory: LiveVoiceModelFactory | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        if live_buffer.identity.runtime_mode not in {
            VoiceRuntimeMode.BROWSER_DECOMPOSED,
            VoiceRuntimeMode.TELEPHONY,
        }:
            raise ValueError("The decomposed voice runner cannot own realtime mode.")
        self._buffer = live_buffer
        self._session_state = session_state
        self._model_factory = model_factory
        self._tool_executor = tool_executor or LiveVoiceToolExecutor(
            live_buffer.identity
        )
        self._turn_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._active_task: asyncio.Task[None] | None = None
        self._active_request_id: UUID | None = None
        self._fallback_messages: list[RunMessage] = []
        self._closed = False

    async def submit(
        self,
        request_id: UUID,
        transcript: str,
        captured_sequence: int | None,
    ) -> bool:
        """Queue one final user utterance without blocking STT or interruption."""
        if self._closed:
            return False

        if captured_sequence is None:
            self._fallback_messages.append(
                _plain_run_message(
                    role="user",
                    content=transcript,
                    kind=MessageKind.USER,
                    request_id=request_id,
                )
            )
        fallback_count = len(self._fallback_messages)
        task = asyncio.create_task(
            self._run_serialized(
                request_id=request_id,
                captured_sequence=captured_sequence,
                fallback_count=fallback_count,
            ),
            name=f"live-voice-turn-{request_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._forget_task)
        return True

    async def interrupt(self) -> None:
        """Cancel only the active inference; queued/new user input remains live."""
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()

    async def drain(self, *, timeout: float = 15.0) -> None:
        """Stop accepting input and settle submitted turns before call teardown."""
        self._closed = True
        tasks = tuple(self._tasks)
        if not tasks:
            return
        try:
            async with asyncio.timeout(timeout):
                await asyncio.gather(*tasks, return_exceptions=True)
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def record_speech_outcome(
        self,
        request_id: str | None,
        outcome: VoiceSpeechOutcome,
    ) -> None:
        """Record whether generated assistant speech drained or was interrupted."""
        if request_id is None:
            return
        try:
            normalized_request_id = UUID(str(request_id))
        except ValueError:
            return
        self._buffer.mark_speech_outcome(
            normalized_request_id,
            outcome,
        )
        status = {
            VoiceSpeechOutcome.DRAINED: VoiceRequestStatus.COMPLETED,
            VoiceSpeechOutcome.INTERRUPTED: VoiceRequestStatus.INTERRUPTED,
            VoiceSpeechOutcome.FAILED: VoiceRequestStatus.FAILED,
            VoiceSpeechOutcome.CANCELLED: VoiceRequestStatus.INTERRUPTED,
        }[outcome]
        self._mark_request(normalized_request_id, status)

    async def _run_serialized(
        self,
        *,
        request_id: UUID,
        captured_sequence: int | None,
        fallback_count: int,
    ) -> None:
        try:
            async with self._turn_lock:
                self._active_task = asyncio.current_task()
                self._active_request_id = request_id
                await self._run_turn(
                    request_id=request_id,
                    captured_sequence=captured_sequence,
                    fallback_count=fallback_count,
                )
        except asyncio.CancelledError:
            self._mark_request(request_id, VoiceRequestStatus.INTERRUPTED)
            raise
        except Exception as error:
            self._mark_request(request_id, VoiceRequestStatus.FAILED)
            logger.error(
                "Live voice agent turn failed error_type=%s",
                type(error).__name__,
            )
        finally:
            if self._active_task is asyncio.current_task():
                self._active_task = None
                self._active_request_id = None

    async def _run_turn(
        self,
        *,
        request_id: UUID,
        captured_sequence: int | None,
        fallback_count: int,
    ) -> None:
        identity = self._buffer.identity
        snapshot = await self._buffer.snapshot()
        live_messages = tuple(
            message
            for item in snapshot.items
            if captured_sequence is None or item.sequence <= captured_sequence
            if (message := _run_message_from_voice_item(item)) is not None
        )
        transient_messages = (
            *live_messages,
            *self._fallback_messages[:fallback_count],
        )

        async with start_transaction() as db:
            conversation = await ConversationService(db).get_by_organization_and_id(
                identity.organization_id,
                identity.conversation_id,
            )
            if conversation is None:
                raise ValueError("Live voice conversation is unavailable.")
            context_service = ConversationContextService(db)
            context = await context_service.build(
                conversation=conversation,
                voice_runtime=identity.runtime_mode,
            )
            from eylo.common.contracts.tool_availability import ToolRuntimeFact
            from eylo.pipelines.system_tools.availability import (
                refresh_context_tool_availability,
            )

            await refresh_context_tool_availability(
                context,
                session=db,
                runtime_facts={
                    ToolRuntimeFact.DURABLE_EXECUTION,
                    ToolRuntimeFact.ACTIVE_VOICE_SESSION,
                },
            )
            agent = without_live_sandbox_agent_tools(agent_spec_from_context(context))
            base_input = run_input_from_context(context, request_id=request_id)
            run_input = base_input.model_copy(
                update={
                    "messages": (*base_input.messages, *transient_messages),
                    "tools": agent.tools,
                }
            )
            run_config = RunConfig(stream=RunStreaming.ENABLED)
            local_context = PlatformRunState(
                conversation_context=context,
                live_voice_identity=identity,
            )

            async def refresh_after_handoff(
                run_context: RunContext,
                current_input: RunInput,
                tool_results: tuple[ToolResult, ...],
            ) -> RunInput:
                if not completed_handoffs(tool_results):
                    return current_input
                refreshed = await context_service.build(
                    conversation=local_context.conversation_context.conversation,
                    voice_runtime=identity.runtime_mode,
                )
                await refresh_context_tool_availability(
                    refreshed,
                    session=db,
                    runtime_facts={
                        ToolRuntimeFact.DURABLE_EXECUTION,
                        ToolRuntimeFact.ACTIVE_VOICE_SESSION,
                    },
                )
                local_context.conversation_context = refreshed
                next_agent = without_live_sandbox_agent_tools(
                    agent_spec_from_context(refreshed)
                )
                if run_context.current_agent.id != next_agent.id:
                    run_context.record_handoff(next_agent)
                else:
                    run_context.current_agent = next_agent
                return current_input.model_copy(
                    update={
                        "instructions": refreshed.system_prompt
                        or next_agent.instructions,
                        "tools": next_agent.tools,
                    }
                )

            model = self._build_model(local_context, run_config)
            lifecycle_hooks = LiveVoiceLifecycleHooks(
                local_context=local_context,
                request_id=request_id,
            )
            self._mark_request(request_id, VoiceRequestStatus.LLM_STARTED)
            try:
                result = await FrameworkRunner(
                    model,
                    tool_executor=self._tool_executor,
                    hooks=lifecycle_hooks,
                    callbacks=RunCallbacks(after_tool_results=refresh_after_handoff),
                ).run(
                    agent,
                    run_input,
                    config=run_config,
                    local_context=local_context,
                )
            except asyncio.CancelledError:
                await lifecycle_hooks.finish(AgentLifecycleOutcome.COMPLETED)
                raise
            except Exception:
                await lifecycle_hooks.finish(AgentLifecycleOutcome.FAILED)
                raise

        try:
            drafts, response_messages = _response_capture(
                result,
                request_id=request_id,
                context=context,
            )
        except (ValidationError, LiveVoiceHistoryError):
            await self._buffer.reject_capture()
            logger.error("Decomposed voice capture contains invalid data.")
        else:
            if drafts:
                appended = await self._buffer.append_turn(drafts)
                schedule_live_message_transcripts(identity, appended)
                if not appended:
                    self._fallback_messages.extend(response_messages)
        if result.status in {
            RunStatus.WAITING_FOR_INPUT,
            RunStatus.WAITING_FOR_APPROVAL,
        }:
            prompt = next(
                (
                    item.message
                    for item in reversed(result.items)
                    if item.kind
                    in {RunItemKind.INPUT_REQUEST, RunItemKind.APPROVAL_REQUEST}
                    and item.message
                ),
                None,
            )
            if prompt:
                await _emit_text(
                    identity.organization_id,
                    identity.conversation_id,
                    request_id,
                    prompt,
                )
        if result.status in {
            RunStatus.COMPLETED,
            RunStatus.WAITING_FOR_INPUT,
            RunStatus.WAITING_FOR_APPROVAL,
        }:
            self._mark_request(request_id, VoiceRequestStatus.LLM_COMPLETED)
        else:
            self._mark_request(request_id, VoiceRequestStatus.FAILED)

    def _build_model(
        self,
        local_context: PlatformRunState[ConversationContext],
        config: RunConfig,
    ) -> Model:
        if self._model_factory is not None:
            return self._model_factory(local_context, config)
        return ExistingConversationModel(
            local_context,
            llm_resolver=resolve_pinned_llm,
            inference_mode=to_llm_inference_mode(config.stream),
        )

    def _mark_request(
        self,
        request_id: UUID,
        status: VoiceRequestStatus,
    ) -> None:
        if self._session_state is not None:
            self._session_state.mark_voice_request(request_id, status)

    def _forget_task(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Live voice task ended unexpectedly error_type=%s",
                type(error).__name__,
            )


def _run_message_from_voice_item(item: LiveVoiceDraft) -> RunMessage | None:
    """Project agent history; platform policy speech is not a model exchange."""
    request_id = item.request_id
    if item.kind is LiveVoiceItemKind.SYSTEM_SPEECH:
        return None
    if item.kind is LiveVoiceItemKind.USER_TRANSCRIPT:
        return _plain_run_message(
            role="user",
            content=_voice_text(item),
            kind=MessageKind.USER,
            request_id=request_id,
        )
    if item.kind is LiveVoiceItemKind.ASSISTANT_TRANSCRIPT:
        return _plain_run_message(
            role="assistant",
            content=_voice_text(item),
            kind=MessageKind.ASSISTANT,
            request_id=request_id,
        )
    if item.kind is LiveVoiceItemKind.DTMF:
        return _plain_run_message(
            role="user",
            content=f"DTMF digits: {_voice_text(item)}",
            kind=MessageKind.USER,
            request_id=request_id,
        )
    if item.kind is LiveVoiceItemKind.TOOL_CALL:
        if (
            not item.tool_call_id
            or not item.tool_name
            or not isinstance(item.payload, dict)
        ):
            raise LiveVoiceHistoryError(
                "Voice tool call identity or arguments are invalid."
            )
        call = ToolCall(
            id=item.tool_call_id,
            name=item.tool_name,
            arguments=item.payload,
        )
        return RunMessage(
            role="assistant",
            content="",
            metadata=ExistingRunMessageMetadata(
                kind=MessageKind.TOOL_USE,
                content_kind=MessageContentKind.TOOL,
                request_id=request_id,
                meta=MessageMeta(),
                tool_call=ExistingToolCallMetadata(
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                ),
            ),
        )
    if not item.tool_call_id or item.is_error is None:
        raise LiveVoiceHistoryError(
            "Voice tool result identity or outcome is unavailable."
        )
    result = ToolResult(
        tool_call_id=item.tool_call_id,
        content=item.payload,
        is_error=item.is_error,
    )
    return RunMessage(
        role="tool",
        content=_content_text(item.payload),
        metadata=ExistingRunMessageMetadata(
            kind=MessageKind.TOOL_RESULT,
            content_kind=MessageContentKind.TOOL,
            request_id=request_id,
            meta=MessageMeta(),
            tool_result=ExistingToolResultMetadata(
                tool_call_id=result.tool_call_id,
                name=item.tool_name,
                is_error=result.is_error,
                content=result.content,
            ),
        ),
    )


def _voice_text(item: LiveVoiceDraft) -> str:
    if not isinstance(item.payload, str):
        raise LiveVoiceHistoryError("Voice speech history requires text.")
    return item.payload


def _plain_run_message(
    *,
    role: str,
    content: str,
    kind: MessageKind,
    request_id: UUID | None,
) -> RunMessage:
    return RunMessage(
        role=role,
        content=content,
        metadata=ExistingRunMessageMetadata(
            kind=kind,
            content_kind=MessageContentKind.TEXT,
            request_id=request_id,
            meta=MessageMeta(),
        ),
    )


def _response_capture(
    result: RunResult,
    *,
    request_id: UUID,
    context: ConversationContext,
) -> tuple[list[LiveVoiceDraft], list[RunMessage]]:
    """Capture native live results, advancing attribution after each proven switch."""
    result = RunResult.model_validate(result)
    agent_participant = context.get_primary_agent()
    participant_id = agent_participant.id if agent_participant else None
    drafts: list[LiveVoiceDraft] = []
    messages: list[RunMessage] = []
    tool_names: dict[str, str] = {}
    for item in result.items:
        draft = _draft_from_run_item(
            item,
            request_id=request_id,
            participant_id=participant_id,
            tool_names=tool_names,
        )
        if draft is None:
            continue
        drafts.append(draft)
        message = _run_message_from_voice_item(draft)
        if message is not None:
            messages.append(message)
        if isinstance(item, RunToolResultItem):
            try:
                handoff = handoff_metadata_from(item.payload)
            except (ValueError, TypeError) as error:
                raise LiveVoiceHistoryError(
                    "Voice handoff metadata is invalid."
                ) from error
            if handoff is not None and handoff.target_participant_id is not None:
                participant_id = handoff.target_participant_id
            elif (
                handoff is None
                and not item.payload.is_error
                and tool_names[item.payload.tool_call_id].startswith(
                    HANDOFF_TOOL_PREFIX
                )
            ):
                raise LiveVoiceHistoryError(
                    "Voice handoff capture lacks its switch identity."
                )
    return drafts, messages


def _draft_from_run_item(
    item: RunItem,
    *,
    request_id: UUID,
    participant_id: UUID | None,
    tool_names: dict[str, str],
) -> LiveVoiceDraft | None:
    if item.kind is RunItemKind.MESSAGE and item.message:
        return LiveVoiceDraft(
            kind=LiveVoiceItemKind.ASSISTANT_TRANSCRIPT,
            payload=item.message,
            participant_id=participant_id,
            request_id=request_id,
        )
    if isinstance(item, RunToolCallItem):
        call = item.payload
        tool_names[call.id] = call.name
        return LiveVoiceDraft(
            kind=LiveVoiceItemKind.TOOL_CALL,
            payload=call.arguments,
            participant_id=participant_id,
            request_id=request_id,
            tool_call_id=call.id,
            tool_name=call.name,
        )
    if isinstance(item, RunToolResultItem):
        result = item.payload
        name = tool_names.get(result.tool_call_id)
        if name is None:
            raise LiveVoiceHistoryError(
                "Voice tool result has no matching captured call."
            )
        content = result.content
        payload = content if isinstance(content, (str, dict)) else {"content": content}
        return LiveVoiceDraft(
            kind=LiveVoiceItemKind.TOOL_RESULT,
            payload=payload,
            participant_id=participant_id,
            request_id=request_id,
            tool_call_id=result.tool_call_id,
            tool_name=name,
            is_error=result.is_error,
        )
    if item.kind in {RunItemKind.INPUT_REQUEST, RunItemKind.APPROVAL_REQUEST}:
        if item.message:
            return LiveVoiceDraft(
                kind=LiveVoiceItemKind.ASSISTANT_TRANSCRIPT,
                payload=item.message,
                participant_id=participant_id,
                request_id=request_id,
            )
    return None


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    return str(content)


async def _emit_text(
    organization_id: UUID,
    conversation_id: UUID,
    request_id: UUID,
    content: str,
) -> None:
    turn_id = uuid4()
    await deliver_voice_text_segment(
        VoiceTextSegment(
            organization_id=organization_id,
            conversation_id=conversation_id,
            text=content,
            phase=VoiceTextPhase.PARTIAL,
            turn_id=turn_id,
            request_id=request_id,
        )
    )
    await deliver_voice_text_segment(
        VoiceTextSegment(
            organization_id=organization_id,
            conversation_id=conversation_id,
            text="",
            phase=VoiceTextPhase.COMPLETE,
            turn_id=turn_id,
            request_id=request_id,
        )
    )


__all__ = ["LiveVoiceTurnRunner"]
