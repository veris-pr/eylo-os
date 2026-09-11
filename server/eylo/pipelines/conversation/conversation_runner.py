"""Production-facing conversation wrapper for the framework runner.

This adapter keeps the primitive ``FrameworkRunner`` free of Eylo persistence
concerns while giving the message listener a concrete execution seam.
"""

from __future__ import annotations

import datetime
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Callable, Generic
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import arrow
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from eylo.common.context_compaction import (
    latest_context_compaction,
    uncompacted_messages,
)
from eylo.common.contracts.llm_catalog import LLMModels
from eylo.common.contracts.llm_response import (
    LLMContentBlock,
    LLMContentType,
    LLMDeltaKind,
    LLMResponse,
    LLMResponsePhase,
)
from eylo.common.contracts.llm_runtime import LLMInferenceConfig, LLMPromptCaching
from eylo.common.contracts.tool_platform import PlatformTool, PlatformToolInputSchema
from eylo.common.contracts.tool_record import ToolRecord
from eylo.common.database import get_transaction
from eylo.events.py_events.agent_lifecycle import AgentLifecycleEmitter
from eylo.events.schema.py_events.base import (
    AgentLifecycleOutcome,
    AgentProcessingEvent,
    AgentResponseCompleteEvent,
    AgentRunInferenceEvent,
    AgentRunToolEvent,
    AgentToolResponseEvent,
)
from eylo.framework.agents.agent import AgentSpec
from eylo.framework.agents.common import FrameworkMetadata, JsonObject
from eylo.framework.agents.config import RunConfig, RunStreaming
from eylo.framework.agents.context import RunContext, RunInput, RunMessage
from eylo.framework.agents.history import ModelResponseProvenance, ToolResultProvenance
from eylo.framework.agents.hooks import RunCallbacks, RunHooks
from eylo.framework.agents.interruptions import (
    RunApprovalInterruption,
    RunInputInterruption,
)
from eylo.framework.agents.model import (
    ModelBlockKind,
    ModelOutputBlock,
    ModelReasoningBlock,
    ModelResponse,
    ModelSettings,
    ModelStopReason,
    ModelTextBlock,
    ModelToolCallBlock,
    ModelUsage,
)
from eylo.framework.agents.result import (
    RunFailureCode,
    RunFailureMetadata,
    RunResult,
    RunStatus,
    RunTerminalMetadata,
)
from eylo.framework.agents.runner import FrameworkRunner
from eylo.framework.agents.tool import ToolCall, ToolExecutor, ToolResult, ToolSpec
from eylo.modules.agent_runs.budgets import (
    has_current_agent_run_budget_scope,
    meter_current_agent_run_usage,
)
from eylo.modules.agent_runs.domain import (
    AgentApprovalDecision,
    AgentInputRequestKind,
    AgentRunLifecycle,
    AgentRunOutcome,
)
from eylo.modules.agent_runs.service import (
    finish_agent_run_in_transaction,
    pause_agent_run_in_transaction,
)
from eylo.modules.agent_runs.waits import AgentApprovalWaitState, AgentRunWaitState
from eylo.modules.agents.services.runner.message_store import ErrorMessages
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.message_content import (
    AssistantMessageContent,
    SystemMessageContent,
    TextContent,
    TextMessageContentBlocks,
    ToolResultContent,
    ToolResultMessageContent,
    ToolUseContent,
    ToolUseMessageContent,
    UserMessageContent,
    WidgetResponseMessageContent,
)
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageContentType,
    MessageCreate,
    MessageInDb,
    MessageKind,
    RequestStatus,
)
from eylo.modules.conversations.services.conversations import ConversationService
from eylo.modules.conversations.services.messages import MessageService
from eylo.modules.llm_configs.domain import (
    InvalidLLMConfig,
    LLMOverrides,
    ResolvePinnedLLM,
)
from eylo.modules.llm_configs.wiring import resolve_pinned_llm
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.agent_execution_context import (
    ContextT,
    PlatformExecutionContext,
    PlatformRunState,
)
from eylo.pipelines.agent_run_continuations import (
    RunContinuation,
    parse_run_continuation,
)
from eylo.pipelines.conversation.background_dispatch import (
    dispatch_background_agents,
)
from eylo.pipelines.conversation.context import ConversationContextService
from eylo.pipelines.llm.runtime import (
    LLMInferenceMode,
    to_llm_inference_mode,
    to_llm_prompt_caching,
)
from eylo.pipelines.llm.voice_text import VoiceTextPhase, VoiceTurnRef
from eylo.pipelines.session_timeline import try_file_runtime_fact
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.factory import LLMFactory
from eylo.sockets.tts.text_stream import SpeakableTextBuffer

from .completion import (
    ConversationMessageArtifact,
    ConversationRunSummary,
    FrameworkTerminalMessageMeta,
)
from .domain import (
    ExistingRunInputMetadata,
    ExistingToolCallMetadata,
    ExistingToolResultMetadata,
    agent_spec_from_context,
    run_input_from_context,
    tool_results_from_run_message,
)
from .handoff import completed_handoffs, handoff_metadata_from
from .run_state import ConversationRunState, require_conversation_run_state
from .tool_executor import PlatformToolExecutor

if TYPE_CHECKING:
    from eylo.pipelines.outbound.durable_execution import DurableStepContext

logger = logging.getLogger(__name__)

_PAUSE_STATUSES = {
    RunStatus.WAITING_FOR_APPROVAL,
    RunStatus.WAITING_FOR_INPUT,
}

_FRAMEWORK_TOOL_ID = TypeAdapter(UUID, config=ConfigDict(hide_input_in_errors=True))
_REQUEST_ID = TypeAdapter(UUID, config=ConfigDict(hide_input_in_errors=True))
_TRANSIENT_MESSAGE_COUNT = TypeAdapter(
    Annotated[int, Field(strict=True, ge=0)],
    config=ConfigDict(hide_input_in_errors=True),
)


class _FrameworkToolRecord(BaseModel):
    """Vendor-facing record for a framework-only model tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    llm_config: PlatformTool


def _vendor_tools_from_run_input(
    run_input: RunInput,
    conversation_context: PlatformExecutionContext,
) -> list[ToolRecord]:
    """Project the framework-authoritative tool list into vendor records."""
    persisted_by_name: dict[str, ToolRecord] = {}
    for tool in conversation_context.get_tools():
        name = tool.llm_config.name
        if name in persisted_by_name:
            raise ValueError(
                "Conversation tools contain a duplicate model-visible name."
            )
        persisted_by_name[name] = tool

    organization_id = conversation_context.conversation.organization_id
    vendor_tools: list[ToolRecord] = []
    seen_names: set[str] = set()
    for spec in run_input.tools:
        if spec.name in seen_names:
            raise ValueError("Run input tools contain a duplicate model-visible name.")
        seen_names.add(spec.name)

        persisted = persisted_by_name.get(spec.name)
        if persisted is not None:
            vendor_tools.append(persisted)
            continue

        vendor_tools.append(
            _FrameworkToolRecord(
                id=_framework_tool_id(spec, organization_id=organization_id),
                llm_config=PlatformTool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=PlatformToolInputSchema.model_validate(
                        spec.input_schema
                    ),
                ),
            )
        )
    return vendor_tools


def _framework_tool_id(spec: ToolSpec, *, organization_id: UUID) -> UUID:
    """Preserve a supplied UUID; derive identity only when none was supplied."""
    metadata_id = spec.metadata.get("id")
    if metadata_id is not None:
        return _FRAMEWORK_TOOL_ID.validate_python(metadata_id)
    return uuid5(
        NAMESPACE_URL,
        f"eylo:framework-tool:{organization_id}:{spec.name}",
    )


class ExistingConversationModel(Generic[ContextT]):
    """Framework model adapter over today's LLM vendor adapters."""

    def __init__(
        self,
        conversation_context: ContextT | PlatformRunState[ContextT],
        *,
        llm_resolver: ResolvePinnedLLM,
        prompt_caching: LLMPromptCaching | None = None,
        inference_mode: LLMInferenceMode = LLMInferenceMode.SINGLE_RESPONSE,
    ) -> None:
        self._conversation_context = conversation_context
        self._llm_resolver = llm_resolver
        self._prompt_caching = prompt_caching
        self._inference_mode = inference_mode

    async def generate(
        self,
        run_input: RunInput,
        settings: ModelSettings,
    ) -> ModelResponse:
        """Resolve org credentials, then call the matching LLM adapter."""
        settings = ModelSettings.model_validate(settings)
        if (
            settings.provider_config_id is None
            or settings.provider_config_revision is None
        ):
            raise NotConfiguredError(
                capability=Capability.LLM,
                missing=["provider_config", "provider_config_revision"],
                configure_via="/api/agents",
            )
        resolved = await self._llm_resolver(
            self.current_context.conversation.organization_id,
            provider_config_id=settings.provider_config_id,
            revision=settings.provider_config_revision,
            overrides=_llm_overrides_from_settings(settings),
        )
        adapter = LLMFactory.from_resolved(resolved).adapter
        messages = _prepare_messages_for_existing_vendor(
            _messages_from_run_input(run_input, self.current_context)
        )
        tools = _vendor_tools_from_run_input(run_input, self.current_context)
        prompt_caching = self._prompt_caching
        if prompt_caching is None:
            prompt_caching = to_llm_prompt_caching(settings.prompt_caching)
        llm_config = LLMInferenceConfig(
            generation=resolved.generation,
            prompt_caching=prompt_caching,
        )

        if self._inference_mode is LLMInferenceMode.STREAMING:
            llm_response = await self._run_streaming_inference(
                adapter=adapter,
                run_input=run_input,
                messages=messages,
                tools=tools,
                llm_config=llm_config,
                emit_tokens=not has_current_agent_run_budget_scope(),
            )
        else:
            llm_response = await adapter.run_inference(
                messages=messages,
                system_prompt=run_input.instructions,
                tools=tools,
                llm_config=llm_config,
            )
        await _meter_llm_response(llm_response)
        return _model_response_from_llm_response(llm_response)

    async def _run_streaming_inference(
        self,
        *,
        adapter: LLMVendorAdapter,
        run_input: RunInput,
        messages: list[MessageInDb],
        tools: list[ToolRecord],
        llm_config: LLMInferenceConfig,
        emit_tokens: bool,
    ) -> LLMResponse:
        """Stream through the adapter and deliver ordered voice text segments."""
        turn_id = uuid4()
        metadata = _token_metadata(run_input, turn_id)
        text_stream = PlatformTokenStream(run_input=run_input, metadata=metadata)
        emitted_complete = False

        streaming_iter: AsyncGenerator[LLMResponse, None] | None = None
        try:
            try:
                streaming_iter = adapter.run_streaming_inference(
                    messages=messages,
                    system_prompt=run_input.instructions,
                    tools=tools,
                    llm_config=llm_config,
                )
                first_chunk = await streaming_iter.__anext__()
            except (AttributeError, NotImplementedError, StopAsyncIteration, TypeError):
                response = await adapter.run_inference(
                    messages=messages,
                    system_prompt=run_input.instructions,
                    tools=tools,
                    llm_config=llm_config,
                )
                if emit_tokens:
                    await text_stream.add_response(response)
                    await text_stream.flush()
                    await _emit_token_complete(run_input, metadata)
                return response

            if not emit_tokens:
                return await _consume_buffered_stream(first_chunk, streaming_iter)

            final_response, emitted_complete = await _consume_stream_chunk(
                first_chunk,
                text_stream,
                emitted_complete=emitted_complete,
            )

            async for partial_response in streaming_iter:
                candidate, emitted_complete = await _consume_stream_chunk(
                    partial_response,
                    text_stream,
                    emitted_complete=emitted_complete,
                )
                final_response = candidate or final_response

            if final_response is None:
                raise ValueError("Streaming inference returned no responses")

            if not text_stream.has_received_text:
                await text_stream.add_response(final_response)
            else:
                await text_stream.reconcile_response(final_response)
            await text_stream.flush()
            if not emitted_complete:
                await _emit_token_complete(run_input, metadata)
            return final_response
        finally:
            if streaming_iter is not None:
                await streaming_iter.aclose()

    @property
    def current_context(self) -> ContextT:
        """Return the latest conversation context for this model call."""
        if isinstance(self._conversation_context, PlatformRunState):
            return self._conversation_context.conversation_context
        return self._conversation_context


class FrameworkConversationRunner:
    """Run one real conversation turn through the primitive framework."""

    def __init__(
        self,
        *,
        conversation_service: ConversationService | None = None,
        context_service: ConversationContextService | None = None,
        message_service: MessageService | None = None,
        tool_executor: ToolExecutor | None = None,
        llm_resolver: ResolvePinnedLLM | None = None,
        model_factory: Callable[
            [ConversationRunState, RunConfig],
            ExistingConversationModel[ConversationContext],
        ]
        | None = None,
    ) -> None:
        self._conversation_service = conversation_service or ConversationService()
        self._context_service = context_service or ConversationContextService()
        self._message_service = message_service or MessageService()
        self._tool_executor = tool_executor or PlatformToolExecutor()
        self._llm_resolver = llm_resolver
        self._model_factory = model_factory

    async def run(
        self,
        *,
        conversation_id: UUID,
        user_message: MessageInDb,
        config: RunConfig | None = None,
        agent_run_id: UUID | None = None,
        expected_agent_id: UUID | None = None,
        expected_agent_revision: int | None = None,
        durable_context: DurableStepContext | None = None,
    ):
        """Execute and persist one framework-backed conversation turn."""
        if agent_run_id is not None and (
            expected_agent_id is None or expected_agent_revision is None
        ):
            raise ValueError("Durable conversation execution requires an exact agent.")
        if agent_run_id is not None and durable_context is None:
            raise ValueError("Durable conversation execution requires its context.")
        run_config = (
            RunConfig.model_validate(config) if config is not None else RunConfig()
        )
        conversation = await self._conversation_service.get_(conversation_id)
        context = await self._context_service.build(
            conversation=conversation,
            through_message_id=user_message.id,
        )
        context = _context_through_user_message(context, user_message)
        if agent_run_id is not None:
            _require_exact_context_agent(
                context,
                agent_id=expected_agent_id,
                agent_revision=expected_agent_revision,
            )
        return await self._execute_context(
            context=context,
            user_message=user_message,
            run_config=run_config,
            agent_run_id=agent_run_id,
            last_message_id=user_message.id,
            durable_context=durable_context,
        )

    async def resume(
        self,
        *,
        conversation_id: UUID,
        user_message: MessageInDb,
        wait: AgentRunWaitState,
        config: RunConfig,
        agent_run_id: UUID,
        expected_agent_id: UUID,
        expected_agent_revision: int,
        durable_context: DurableStepContext,
    ):
        """Continue one answered tool interruption on the same product run."""
        config = RunConfig.model_validate(config)
        conversation = await self._conversation_service.get_(conversation_id)
        context = await self._context_service.build(conversation=conversation)
        _require_exact_context_agent(
            context,
            agent_id=expected_agent_id,
            agent_revision=expected_agent_revision,
        )
        from eylo.common.contracts.tool_availability import ToolRuntimeFact
        from eylo.pipelines.system_tools.availability import (
            refresh_context_tool_availability,
        )

        await refresh_context_tool_availability(
            context,
            runtime_facts={
                ToolRuntimeFact.DURABLE_EXECUTION,
                ToolRuntimeFact.AGENT_RUN,
            },
        )
        agent = agent_spec_from_context(context)
        tool_use_message, tool_call = _resume_tool_call(
            context,
            run_id=agent_run_id,
            wait=wait,
        )
        existing_result = _resume_result_message(
            context,
            run_id=agent_run_id,
            request_id=wait.request_id,
        )
        context.messages = _without_pause_projections(
            context.messages or [],
            run_id=agent_run_id,
        )
        local_context = ConversationRunState(
            conversation_context=context,
            last_message_id=(
                existing_result.id
                if existing_result is not None
                else tool_use_message.id
            ),
            active_user_message=user_message,
            request_id=user_message.request_id,
            agent_run_id=agent_run_id,
            tool_use_messages={tool_call.id: tool_use_message},
            command_ids={tool_call.id: tool_use_message.id},
            durable_context=durable_context,
        )
        run_context = RunContext(
            current_agent=agent,
            handoff_chain=[agent],
            local_context=local_context,
            config=config,
        )
        if existing_result is None:
            tool_result = await self._resume_tool_result(
                run_context=run_context,
                call=tool_call,
                wait=wait,
            )
            tool_result = tool_result.model_copy(
                update={
                    "metadata": tool_result.metadata.model_copy(
                        update={"resume_request_id": str(wait.request_id)}
                    )
                }
            )
            await self._persist_tool_result_message(run_context, tool_call, tool_result)

        refreshed = await self._context_service.build(conversation=conversation)
        refreshed.messages = _without_pause_projections(
            refreshed.messages or [],
            run_id=agent_run_id,
        )
        return await self._execute_context(
            context=refreshed,
            user_message=user_message,
            run_config=config,
            agent_run_id=agent_run_id,
            last_message_id=local_context.last_message_id,
            durable_context=durable_context,
        )

    async def _resume_tool_result(
        self,
        *,
        run_context: RunContext,
        call: ToolCall,
        wait: AgentRunWaitState,
    ) -> ToolResult:
        wait.require_answered()
        if isinstance(wait, AgentApprovalWaitState):
            response = wait.require_response()
            if response.decision is AgentApprovalDecision.APPROVE:
                return await self._tool_executor.execute(run_context, call)
            return ToolResult(
                tool_call_id=call.id,
                content="The user rejected this tool action.",
                is_error=True,
                metadata={"approval_rejected": True},
            )

        return ToolResult(
            tool_call_id=call.id,
            content=json.dumps(
                wait.response, ensure_ascii=False, separators=(",", ":")
            ),
            metadata={
                "human_input_received": True,
                "input_request_id": str(wait.request_id),
            },
        )

    async def _execute_context(
        self,
        *,
        context: ConversationContext,
        user_message: MessageInDb,
        run_config: RunConfig,
        agent_run_id: UUID | None,
        last_message_id: UUID,
        durable_context: DurableStepContext | None,
    ):
        from eylo.common.contracts.tool_availability import ToolRuntimeFact
        from eylo.pipelines.system_tools.availability import (
            refresh_context_tool_availability,
        )

        execution_facts = (
            {ToolRuntimeFact.DURABLE_EXECUTION, ToolRuntimeFact.AGENT_RUN}
            if agent_run_id is not None and durable_context is not None
            else set()
        )
        await refresh_context_tool_availability(
            context,
            runtime_facts=execution_facts,
        )
        agent = agent_spec_from_context(context)
        run_input = run_input_from_context(context, request_id=user_message.request_id)
        local_context = ConversationRunState(
            conversation_context=context,
            last_message_id=last_message_id,
            active_user_message=user_message,
            request_id=user_message.request_id,
            agent_run_id=agent_run_id,
            durable_context=durable_context,
        )

        if user_message.request_id is not None:
            await self._transition_request_status(
                user_message.request_id,
                RequestStatus.PROCESSING,
                conversation_id=user_message.conversation_id,
            )
            await get_transaction().commit()

        lifecycle_hooks = FrameworkConversationHooks(
            local_context=local_context,
            user_message=user_message,
        )
        local_context.lifecycle_hooks = lifecycle_hooks
        runner = FrameworkRunner(
            self._build_model(local_context, run_config),
            tool_executor=self._tool_executor,
            hooks=lifecycle_hooks,
            callbacks=RunCallbacks(
                after_model_response=self._persist_model_response_messages,
                before_tool_call=self._persist_tool_use_message,
                after_tool_result=self._persist_tool_result_message,
                after_tool_results=self._refresh_after_tool_results,
            ),
        )
        try:
            result = await runner.run(
                agent,
                run_input,
                config=run_config,
                local_context=local_context,
            )
        except Exception:
            await _complete_voice_request(
                context=local_context.conversation_context,
                user_message=user_message,
            )
            lifecycle_hooks.emit_response_complete(AgentLifecycleOutcome.FAILED)
            raise
        final_context = local_context.conversation_context
        outcome = AgentLifecycleOutcome.COMPLETED

        try:
            final_message = await self._persist_terminal_message(
                result=result,
                context=final_context,
                agent=result.final_agent or agent,
                user_message=user_message,
                parent_message_id=local_context.last_message_id,
                agent_run_id=agent_run_id,
            )
            if (
                run_config.stream is RunStreaming.ENABLED
                and _should_emit_terminal_message_tokens(result)
            ):
                await _emit_terminal_message_tokens(
                    run_input,
                    text=final_message.get_text_content() or "",
                    turn_id=result.run_id,
                )
            elif (
                run_config.stream is RunStreaming.DISABLED
                and final_message.content_kind == MessageContentKind.TEXT
            ):
                from eylo.pipelines.llm.streaming_tts import (
                    push_voice_message_to_tts,
                )

                await push_voice_message_to_tts(
                    final_message,
                    final_context.conversation,
                )
        except Exception:
            outcome = AgentLifecycleOutcome.FAILED
            await self._mark_request_failed_after_terminal_persistence_error(
                user_message
            )
            raise
        finally:
            await _complete_voice_request(
                context=final_context,
                user_message=user_message,
            )
            lifecycle_hooks.emit_response_complete(outcome)
        await self._enqueue_memory_formation(final_context)
        return result.model_copy(update={"final_message_id": final_message.id})

    async def _transition_request_status(
        self,
        request_id: UUID | None,
        requested_status: RequestStatus,
        *,
        conversation_id: UUID,
    ) -> None:
        if request_id is None:
            return
        transition = await self._message_service.update_request_status_by_request_id(
            request_id,
            requested_status,
            conversation_id=conversation_id,
        )
        if not transition.valid:
            logger.error(
                "Request status transition rejected: request_id=%s previous=%s requested=%s",
                request_id,
                transition.previous_status,
                requested_status,
            )
            return

    @staticmethod
    async def _enqueue_memory_formation(conversation_context) -> None:
        """Queue learning only after the complete exchange is durable."""
        primary_agent = getattr(conversation_context, "primary_agent", None)
        if primary_agent is None:
            return
        from eylo.pipelines.memory.formation import enqueue_from_context

        await enqueue_from_context(conversation_context, primary_agent)

    def _build_model(
        self,
        local_context: ConversationRunState,
        config: RunConfig,
    ) -> ExistingConversationModel[ConversationContext]:
        if self._model_factory is not None:
            return self._model_factory(local_context, config)
        return ExistingConversationModel(
            local_context,
            llm_resolver=(
                self._llm_resolver
                if self._llm_resolver is not None
                else resolve_pinned_llm
            ),
            prompt_caching=to_llm_prompt_caching(config.prompt_caching),
            inference_mode=to_llm_inference_mode(config.stream),
        )

    async def _mark_request_failed_after_terminal_persistence_error(
        self,
        user_message: MessageInDb,
    ) -> None:
        """Persist a final failed request status without masking the original error."""
        if user_message.request_id is None:
            return

        try:
            transaction = get_transaction()
            await transaction.rollback()
            await self._message_service.update_request_status_by_request_id(
                user_message.request_id,
                RequestStatus.FAILED,
                conversation_id=user_message.conversation_id,
            )
            await transaction.commit()
        except Exception as error:  # noqa: BLE001 - preserve the original terminal error
            logger.error(
                "Failed to mark framework request=%s after terminal persistence "
                "error_type=%s",
                user_message.request_id,
                type(error).__name__,
            )

    async def _persist_model_response_messages(
        self,
        run_context: RunContext,
        run_input: RunInput,
        response: ModelResponse,
        tool_calls: tuple[ToolCall, ...],
    ) -> None:
        """Prepare ordered model-response persistence for tool execution."""
        if not tool_calls:
            return

        local_context = require_conversation_run_state(run_context.local_context)
        local_context.pending_model_response_cursor = 0

    async def _persist_tool_use_message(
        self,
        run_context: RunContext,
        call: ToolCall,
        response: ModelResponse,
    ) -> None:
        """Persist model output blocks in order through this executed tool."""
        local_context = require_conversation_run_state(run_context.local_context)
        conversation_context = local_context.conversation_context
        parent_message_id = local_context.last_message_id
        created_at = arrow.utcnow().datetime
        cursor = local_context.pending_model_response_cursor
        stop_index = _model_block_stop_index(response, call, cursor)

        for index in range(cursor, stop_index):
            block = response.blocks[index]
            if block.kind == ModelBlockKind.TEXT:
                text = block.content
                if not text:
                    continue
                message = await self._message_service.create_(
                    _primary_agent_message_create(
                        conversation_context,
                        kind=MessageKind.ASSISTANT,
                        content_kind=MessageContentKind.TEXT,
                        content=AssistantMessageContent(
                            content=TextContent(text=text),
                        ),
                        external_id=response.id,
                        meta=_framework_message_meta(response, index),
                        created_at=created_at + datetime.timedelta(microseconds=index),
                        parent_message_id=parent_message_id,
                        request_id=local_context.request_id,
                        request_status=RequestStatus.PROCESSING,
                        agent_run_id=local_context.agent_run_id,
                    )
                )
                parent_message_id = message.id
                continue

            if block.kind != ModelBlockKind.TOOL_CALL:
                continue

            tool_call = block.content
            await self._transition_request_status(
                local_context.request_id,
                RequestStatus.AWAITING_TOOL_RESULTS,
                conversation_id=conversation_context.conversation.id,
            )
            message = await self._message_service.create_(
                _primary_agent_message_create(
                    conversation_context,
                    kind=MessageKind.TOOL_USE,
                    content_kind=MessageContentKind.TOOL,
                    content=ToolUseMessageContent(
                        content=ToolUseContent(
                            id=tool_call.id,
                            name=tool_call.name,
                            input=tool_call.arguments,
                        )
                    ),
                    external_id=tool_call.id,
                    meta=_framework_message_meta(response, index),
                    created_at=created_at + datetime.timedelta(microseconds=index),
                    parent_message_id=parent_message_id,
                    request_id=local_context.request_id,
                    request_status=RequestStatus.AWAITING_TOOL_RESULTS,
                    agent_run_id=local_context.agent_run_id,
                )
            )
            local_context.tool_use_messages[tool_call.id] = message
            local_context.command_ids[tool_call.id] = message.id
            parent_message_id = message.id

        local_context.pending_model_response_cursor = stop_index
        local_context.last_message_id = parent_message_id
        await get_transaction().commit()

    async def _persist_tool_result_message(
        self,
        run_context: RunContext,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        """Persist a tool result before the framework advances the loop."""
        local_context = require_conversation_run_state(run_context.local_context)
        tool_use_message = local_context.tool_use_messages.get(call.id)
        if tool_use_message is None:
            raise ValueError("No persisted TOOL_USE message exists for this tool call.")

        sender_participant_id = _tool_result_sender_participant_id(
            local_context,
            result,
        )
        message = await self._message_service.create_(
            MessageCreate(
                conversation_id=tool_use_message.conversation_id,
                sender_participant_id=sender_participant_id,
                kind=MessageKind.TOOL_RESULT,
                content_kind=MessageContentKind.TOOL,
                content=ToolResultMessageContent(
                    content=[
                        ToolResultContent(
                            tool_use_id=tool_use_message.external_id,
                            name=call.name,
                            content=result.content,
                            is_error=result.is_error,
                        )
                    ],
                ),
                meta=_tool_result_meta(result),
                created_at=arrow.utcnow().datetime,
                parent_message_id=tool_use_message.id,
                request_id=tool_use_message.request_id,
                request_status=RequestStatus.AWAITING_TOOL_RESULTS,
                agent_run_id=local_context.agent_run_id,
            )
        )
        local_context.last_message_id = message.id
        await get_transaction().commit()

    async def _refresh_after_tool_results(
        self,
        run_context: RunContext,
        run_input: RunInput,
        tool_results: tuple[ToolResult, ...],
    ) -> RunInput:
        """Refresh active conversation state after DB-changing handoff tools."""
        handoffs = completed_handoffs(tool_results)
        local_context = require_conversation_run_state(run_context.local_context)
        await self._transition_request_status(
            local_context.request_id,
            RequestStatus.PROCESSING,
            conversation_id=local_context.conversation_context.conversation.id,
        )
        await get_transaction().commit()

        if not handoffs:
            return run_input

        current_context = local_context.conversation_context
        active_user_message = local_context.active_user_message
        refreshed = await self._context_service.build(
            conversation=current_context.conversation,
            through_message_id=active_user_message.id,
        )
        refreshed = _context_through_user_message(refreshed, active_user_message)
        from eylo.common.contracts.tool_availability import ToolRuntimeFact
        from eylo.pipelines.system_tools.availability import (
            refresh_context_tool_availability,
        )

        runtime_facts = set()
        if local_context.durable_context is not None:
            runtime_facts.add(ToolRuntimeFact.DURABLE_EXECUTION)
        if local_context.agent_run_id is not None:
            runtime_facts.add(ToolRuntimeFact.AGENT_RUN)
        await refresh_context_tool_availability(
            refreshed,
            runtime_facts=runtime_facts,
        )
        local_context.conversation_context = refreshed

        previous_agent = run_context.current_agent
        next_agent = agent_spec_from_context(refreshed)
        if previous_agent.id != next_agent.id:
            run_context.record_handoff(next_agent)
            lifecycle_hooks = local_context.lifecycle_hooks
            if isinstance(lifecycle_hooks, FrameworkConversationHooks):
                await lifecycle_hooks.on_handoff(
                    run_context,
                    previous_agent,
                    next_agent,
                )
        else:
            run_context.current_agent = next_agent

        refreshed_input = run_input_from_context(refreshed)
        transient_tool_message_count = _TRANSIENT_MESSAGE_COUNT.validate_python(
            run_input.metadata.get("transient_tool_message_count", 0)
        )
        candidate_transient_tool_messages = (
            run_input.messages[-transient_tool_message_count:]
            if transient_tool_message_count
            else ()
        )
        should_append_transient_tools = _should_append_transient_tool_messages(
            refreshed_input,
            candidate_transient_tool_messages,
            tool_results,
        )
        transient_tool_messages = (
            candidate_transient_tool_messages if should_append_transient_tools else ()
        )

        return refreshed_input.model_copy(
            update={
                "messages": (
                    *refreshed_input.messages,
                    *transient_tool_messages,
                ),
                "metadata": ExistingRunInputMetadata.model_validate(
                    {
                        **run_input.metadata.model_dump(),
                        **refreshed_input.metadata.model_dump(exclude_none=True),
                    }
                ),
            }
        )

    async def _persist_terminal_message(
        self,
        *,
        result: RunResult,
        context: ConversationContext,
        agent: AgentSpec,
        user_message: MessageInDb,
        parent_message_id: UUID,
        agent_run_id: UUID | None,
    ) -> MessageInDb:
        result = RunResult.model_validate(result)
        request_status = _request_status_for_result(result)
        text = _terminal_text_for_result(result)
        if result.error_message:
            logger.warning(
                "Framework run %s failed with status %s: %s",
                result.run_id,
                result.status.value,
                result.error_message,
            )
        await self._transition_request_status(
            user_message.request_id,
            request_status,
            conversation_id=user_message.conversation_id,
        )
        message = await _terminal_artifact_message(
            result,
            context=context,
            user_message=user_message,
            message_service=self._message_service,
        )
        if message is None:
            message = await self._message_service.create_(
                _primary_agent_message_create(
                    context,
                    kind=MessageKind.ASSISTANT,
                    content_kind=MessageContentKind.TEXT,
                    content=AssistantMessageContent(
                        content=TextContent(text=text),
                    ),
                    external_id=str(result.run_id),
                    meta=_terminal_message_meta(result, agent),
                    created_at=arrow.utcnow().datetime,
                    parent_message_id=parent_message_id,
                    request_id=user_message.request_id,
                    request_status=request_status,
                    agent_run_id=agent_run_id,
                )
            )
        if agent_run_id is not None:
            if message.agent_run_id is None:
                message = await self._message_service.update_(
                    message.id,
                    {"agent_run_id": agent_run_id},
                )
            elif message.agent_run_id != agent_run_id:
                raise ValueError(
                    "Terminal artifact message belongs to a different AgentRun."
                )
            if result.status in _PAUSE_STATUSES:
                kind, prompt, expected_schema, continuation = _agent_run_pause_fields(
                    result
                )
                await pause_agent_run_in_transaction(
                    get_transaction(),
                    organization_id=context.conversation.organization_id,
                    run_id=agent_run_id,
                    kind=kind,
                    prompt=prompt,
                    expected_response_schema=expected_schema,
                    continuation=continuation,
                )
            else:
                lifecycle, outcome, run_result, outcome_reason, failure_summary = (
                    _agent_run_terminal_fields(
                        result,
                        conversation_id=user_message.conversation_id,
                        origin_message_id=user_message.id,
                        final_message_id=message.id,
                    )
                )
                await finish_agent_run_in_transaction(
                    get_transaction(),
                    organization_id=context.conversation.organization_id,
                    run_id=agent_run_id,
                    lifecycle=lifecycle,
                    outcome=outcome,
                    result=run_result,
                    outcome_reason=outcome_reason,
                    failure_summary=failure_summary,
                )
        await get_transaction().commit()
        return message


class FrameworkConversationHooks(RunHooks):
    """Bridge framework lifecycle callbacks to existing agent UI events."""

    def __init__(
        self, *, local_context: ConversationRunState, user_message: MessageInDb
    ) -> None:
        self._local_context = local_context
        self._user_message = user_message
        self._agent_started = False
        self._events = AgentLifecycleEmitter()

    async def on_run_end(self, context, result) -> None:
        """Enqueue the agent's attached background agents.

        Once per run, after the loop has finished, so nothing here is on the
        latency path of a reply. Enqueue only — the worker does the model work.
        """
        conversation_context = self.current_context
        # `primary_agent` is the agent record; `get_primary_agent()` returns the
        # participant. Attachments hang off the agent, so it is the former.
        primary_agent = getattr(conversation_context, "primary_agent", None)
        if primary_agent is None:
            return

        await dispatch_background_agents(
            agent_id=primary_agent.id,
            conversation_context=conversation_context,
            request_id=self._local_context.request_id,
        )

    async def on_agent_start(self, context, agent: AgentSpec) -> None:
        if self._agent_started:
            return
        self._agent_started = True
        self._events.emit(
            AgentProcessingEvent,
            context=self.current_context,
            request_id=self._user_message.request_id or self._user_message.id,
            message_id=self._user_message.id,
        )

    async def on_llm_start(self, context, run_input: RunInput) -> None:
        from eylo.pipelines.llm.streaming_tts import (
            prepare_voice_sessions_for_inference,
        )

        conversation = self.current_context.conversation
        await prepare_voice_sessions_for_inference(
            conversation_id=conversation.id,
            organization_id=conversation.organization_id,
            request_id=self._user_message.request_id,
        )
        self._events.emit(
            AgentRunInferenceEvent,
            context=self.current_context,
            request_id=self._user_message.request_id or self._user_message.id,
            message_id=self._user_message.id,
        )

    async def on_tool_start(self, context, call: ToolCall) -> None:
        self._events.emit(
            AgentRunToolEvent,
            context=self.current_context,
            request_id=self._user_message.request_id or self._user_message.id,
            message_id=self._user_message.id,
        )
        await self._file_timeline(
            event_type="agent.tool.started",
            payload={
                "tool_name": call.name,
                "tool_call_id": call.id,
            },
            subject_type="agent.tool",
        )

    async def on_tool_end(
        self,
        context,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        self._events.emit(
            AgentToolResponseEvent,
            context=self.current_context,
            request_id=self._user_message.request_id or self._user_message.id,
            message_id=self._user_message.id,
        )
        await self._file_timeline(
            event_type=(
                "agent.tool.failed" if result.is_error else "agent.tool.completed"
            ),
            payload={
                "tool_name": call.name,
                "tool_call_id": call.id,
            },
            subject_type="agent.tool",
        )

    async def on_handoff(
        self,
        context,
        from_agent: AgentSpec,
        to_agent: AgentSpec,
    ) -> None:
        await self._file_timeline(
            event_type="agent.handoff.completed",
            payload={
                "from_agent_id": str(from_agent.id),
                "to_agent_id": str(to_agent.id),
            },
            subject_type="agent.handoff",
        )

    async def _file_timeline(
        self,
        *,
        event_type: str,
        payload: dict,
        subject_type: str,
    ) -> None:
        user_session_id = self._user_message.user_session_id
        if user_session_id is None:
            return
        conversation = self.current_context.conversation
        raw_run_id = self._local_context.agent_run_id
        subject_id = (
            UUID(str(raw_run_id)) if raw_run_id is not None else self._user_message.id
        )
        await try_file_runtime_fact(
            organization_id=conversation.organization_id,
            user_session_id=user_session_id,
            subject_type=subject_type,
            subject_id=subject_id,
            event_type=event_type,
            payload={
                "agent_run_id": str(raw_run_id) if raw_run_id is not None else None,
                "conversation_id": str(conversation.id),
                **payload,
            },
        )

    def emit_response_complete(self, outcome: AgentLifecycleOutcome) -> None:
        self._events.emit(
            AgentResponseCompleteEvent,
            context=self.current_context,
            request_id=self._user_message.request_id or self._user_message.id,
            message_id=self._user_message.id,
            outcome=outcome,
        )

    @property
    def current_context(self) -> ConversationContext:
        return self._local_context.conversation_context


def _terminal_message_meta(result: RunResult, agent: AgentSpec) -> dict[str, object]:
    result = RunResult.model_validate(result)
    return FrameworkTerminalMessageMeta(
        run_id=result.run_id,
        status=result.status,
        model=(
            result.model_responses[-1].model
            if result.model_responses
            else agent.model_settings.model or "unknown"
        ),
        usage=result.usage,
        error=result.error_message is not None,
        run_metadata=result.metadata,
        llm_response=_terminal_replay_response(result),
    ).model_dump(mode="json")


def _terminal_replay_response(result: RunResult) -> ModelResponse | None:
    """Replay only the unchanged final model text, never a tool/generated outcome."""
    if (
        not result.is_success
        or not result.model_responses
        or result.final_output is None
    ):
        return None
    response = result.model_responses[-1]
    if any(block.kind == ModelBlockKind.TOOL_CALL for block in response.blocks):
        return None
    text = "".join(
        block.content for block in response.blocks if block.kind == ModelBlockKind.TEXT
    )
    return response if text == result.final_output else None


def _primary_agent_message_create(
    context: ConversationContext,
    *,
    kind: MessageKind,
    content_kind: MessageContentKind,
    content: object,
    external_id: str,
    meta: dict,
    created_at: datetime.datetime,
    parent_message_id: UUID,
    request_id: UUID | None,
    request_status: RequestStatus,
    agent_run_id: UUID | None,
) -> MessageCreate:
    participant = context.get_primary_agent()
    if participant is None:
        raise ValueError("ConversationContext has no primary agent participant.")
    return MessageCreate(
        conversation_id=context.conversation.id,
        sender_participant_id=participant.id,
        agent_run_id=agent_run_id,
        kind=kind,
        content_kind=content_kind,
        content=content,
        external_id=external_id,
        meta=meta,
        created_at=created_at,
        parent_message_id=parent_message_id,
        request_id=request_id,
        request_status=request_status,
    )


def _require_exact_context_agent(
    context: ConversationContext,
    *,
    agent_id: UUID | None,
    agent_revision: int | None,
) -> None:
    primary_agent = context.get_primary_agent()
    if (
        primary_agent is None
        or primary_agent.agent_id != agent_id
        or primary_agent.agent_revision != agent_revision
    ):
        raise ValueError(
            "Conversation agent no longer matches the durable run revision."
        )


def _resume_tool_call(
    context: ConversationContext,
    *,
    run_id: UUID,
    wait: AgentRunWaitState,
) -> tuple[MessageInDb, ToolCall]:
    continuation = parse_run_continuation(wait, RunContinuation)
    tool_call_id = continuation.framework.tool_call_id

    for message in reversed(context.messages or []):
        if (
            message.agent_run_id != run_id
            or message.kind != MessageKind.TOOL_USE
            or message.external_id != tool_call_id
        ):
            continue
        content = message.get_tool_use_content().content
        return message, ToolCall(
            id=content.id,
            name=content.name,
            arguments=content.input,
        )
    raise ValueError("AgentRun continuation tool call is unavailable.")


def _without_pause_projections(
    messages: list[MessageInDb],
    *,
    run_id: UUID,
) -> list[MessageInDb]:
    return [
        message
        for message in messages
        if not _is_pause_projection(message, run_id=run_id)
    ]


def _resume_result_message(
    context: ConversationContext,
    *,
    run_id: UUID,
    request_id: UUID,
) -> MessageInDb | None:
    for message in reversed(context.messages or []):
        if message.agent_run_id != run_id or message.kind != MessageKind.TOOL_RESULT:
            continue
        metadata = _message_meta_dict(message.meta).get("metadata")
        if isinstance(metadata, dict) and metadata.get("resume_request_id") == str(
            request_id
        ):
            return message
    return None


def _is_pause_projection(message: MessageInDb, *, run_id: UUID) -> bool:
    if message.agent_run_id != run_id:
        return False
    meta = _message_meta_dict(message.meta)
    if message.kind == MessageKind.ASSISTANT:
        return meta.get("status") in {
            RunStatus.WAITING_FOR_INPUT.value,
            RunStatus.WAITING_FOR_APPROVAL.value,
        }
    if message.kind != MessageKind.TOOL_RESULT:
        return False
    metadata = meta.get("metadata")
    return isinstance(metadata, dict) and metadata.get("tool_execution_paused") is True


def _message_meta_dict(meta: object) -> dict:
    if isinstance(meta, BaseModel):
        return meta.model_dump(mode="json")
    return dict(meta) if isinstance(meta, dict) else {}


async def _consume_stream_chunk(
    response: LLMResponse,
    text_stream: "PlatformTokenStream",
    *,
    emitted_complete: bool,
) -> tuple[LLMResponse | None, bool]:
    """Route one adapter streaming chunk into the ordered voice stream."""
    if response.metadata.phase is LLMResponsePhase.PROGRESS:
        delta = response.metadata.delta
        if delta is not None and delta.type is LLMDeltaKind.TEXT:
            await text_stream.add_delta(delta.text)
        return None, emitted_complete

    if not text_stream.has_received_text:
        await text_stream.add_response(response)
    else:
        await text_stream.reconcile_response(response)
    await text_stream.flush()
    if not emitted_complete:
        await _emit_token_complete(text_stream.run_input, text_stream.metadata)
        emitted_complete = True
    return response, emitted_complete


async def _consume_buffered_stream(
    first_response: LLMResponse,
    remaining_responses: AsyncIterator[LLMResponse],
) -> LLMResponse:
    """Buffer budgeted streaming output until final usage is accepted."""
    final_response = _final_stream_response(first_response)
    async for response in remaining_responses:
        final_response = _final_stream_response(response) or final_response
    if final_response is None:
        raise ValueError("Streaming inference returned no final response")
    return final_response


def _final_stream_response(response: LLMResponse) -> LLMResponse | None:
    if response.metadata.phase is LLMResponsePhase.PROGRESS:
        return None
    return response


async def _meter_llm_response(response: LLMResponse) -> None:
    usage = response.usage
    await meter_current_agent_run_usage(
        input_tokens=None if usage is None else usage.input_tokens,
        output_tokens=None if usage is None else usage.output_tokens,
    )


def _response_text(response: LLMResponse) -> str:
    """Return the concatenated text blocks from a vendor-normalized response."""
    return "".join(
        block.content.text
        for block in response.content
        if block.type == LLMContentType.TEXT
    )


class PlatformTokenStream:
    """Emit vendor streaming deltas as safe Eylo platform text segments."""

    def __init__(self, *, run_input: RunInput, metadata: VoiceTurnRef) -> None:
        self.run_input = run_input
        self.metadata = VoiceTurnRef.model_validate(metadata)
        self._buffer = SpeakableTextBuffer()
        self._raw_text = ""

    @property
    def has_received_text(self) -> bool:
        return bool(self._raw_text)

    async def add_delta(self, text: str) -> None:
        """Add one raw vendor text delta and emit any completed segments."""
        if not text:
            return
        self._raw_text += text
        await self._emit_segments(self._buffer.add(text))

    async def add_response(self, response: LLMResponse) -> None:
        """Add text from a non-streaming response."""
        await self.add_delta(_response_text(response))

    async def reconcile_response(self, response: LLMResponse) -> None:
        """Append final response text that was not already covered by deltas."""
        final_text = _response_text(response)
        if not final_text or final_text == self._raw_text:
            return
        if final_text.startswith(self._raw_text):
            await self.add_delta(final_text[len(self._raw_text) :])
            return
        if not self._raw_text:
            await self.add_delta(final_text)

    async def flush(self) -> None:
        """Emit any remaining speakable text before the completion signal."""
        await self._emit_segments(self._buffer.flush())

    async def _emit_segments(self, segments: list[str]) -> None:
        for segment in segments:
            await _emit_token(
                self.run_input,
                token=segment,
                phase=VoiceTextPhase.PARTIAL,
                metadata=self.metadata,
            )


async def _emit_token_complete(run_input: RunInput, metadata: VoiceTurnRef) -> None:
    await _emit_token(
        run_input, token="", phase=VoiceTextPhase.COMPLETE, metadata=metadata
    )


async def _emit_terminal_message_tokens(
    run_input: RunInput,
    *,
    text: str,
    turn_id: UUID,
) -> None:
    metadata = _token_metadata(run_input, turn_id)
    if text:
        await _emit_token(
            run_input,
            token=text,
            phase=VoiceTextPhase.PARTIAL,
            metadata=metadata,
        )
    await _emit_token_complete(run_input, metadata)


async def _emit_token(
    run_input: RunInput,
    *,
    token: str,
    phase: VoiceTextPhase,
    metadata: VoiceTurnRef,
) -> None:
    """Deliver one ordered text segment to active voice sessions."""
    from eylo.pipelines.llm.streaming_tts import (
        VoiceTextSegment,
        deliver_voice_text_segment,
    )

    organization_id = run_input.metadata.get("organization_id")
    conversation_id = run_input.metadata.get("conversation_id")
    if not organization_id or not conversation_id:
        raise ValueError(
            "Framework streaming requires organization_id and conversation_id."
        )

    await deliver_voice_text_segment(
        VoiceTextSegment(
            organization_id=organization_id,
            conversation_id=conversation_id,
            text=token,
            phase=phase,
            turn_id=metadata.turn_id,
            request_id=metadata.request_id,
        )
    )


def _token_metadata(run_input: RunInput, turn_id: UUID) -> VoiceTurnRef:
    """Validate caller correlation without stringifying opaque runtime objects."""
    request_id = run_input.metadata.get("request_id")
    return VoiceTurnRef(
        turn_id=turn_id,
        request_id=None if request_id is None or request_id == "" else request_id,
    )


def _request_id_from_input(run_input: RunInput) -> UUID | None:
    return _request_id_from_metadata(run_input.metadata)


def _request_id_from_metadata(metadata: FrameworkMetadata) -> UUID | None:
    """Accept UUID snapshots and legacy empty correlation, never opaque objects."""
    request_id = metadata.get("request_id")
    if request_id is None or request_id == "":
        return None
    return _REQUEST_ID.validate_python(request_id)


def _model_block_stop_index(
    response: ModelResponse,
    call: ToolCall,
    cursor: int,
) -> int:
    """Return the exclusive block index to persist before executing a tool.

    The framework persists model output lazily so terminal tool results do not
    create dangling future TOOL_USE rows. For the tool about to execute, persist
    all prior text, the matching tool call, and following text until the next
    tool call.
    """
    matched_tool = False
    for index in range(cursor, len(response.blocks)):
        block = response.blocks[index]
        if block.kind != ModelBlockKind.TOOL_CALL:
            continue
        tool_call = block.content
        if matched_tool:
            return index
        if tool_call.id == call.id:
            matched_tool = True

    if matched_tool:
        return len(response.blocks)
    raise ValueError("Tool call identity was not found in its model response.")


def _framework_message_meta(
    response: ModelResponse,
    response_block_index: int | None,
) -> JsonObject:
    return ModelResponseProvenance(
        model_response=response,
        response_block_index=response_block_index,
    ).model_dump(mode="json")


def _tool_result_meta(result: ToolResult) -> JsonObject:
    return ToolResultProvenance.from_result(result).model_dump(mode="json")


def _tool_result_sender_participant_id(
    local_context: ConversationRunState,
    result: ToolResult,
) -> UUID:
    handoff = handoff_metadata_from(result)
    if handoff is not None and handoff.target_participant_id is not None:
        return handoff.target_participant_id

    conversation_context = local_context.conversation_context
    agent = conversation_context.get_primary_agent()
    if agent is None:
        raise ValueError("ConversationContext has no primary agent participant.")
    return agent.id


def _should_append_transient_tool_messages(
    refreshed_input: RunInput,
    transient_tool_messages: tuple[RunMessage, ...],
    tool_results: tuple[ToolResult, ...],
) -> bool:
    """Append in-memory tool messages only when context rebuild lacks them."""
    expected_tool_call_ids = {
        result.tool_call_id for result in tool_results if result.tool_call_id
    }
    if not expected_tool_call_ids or not transient_tool_messages:
        return False

    refreshed_tool_result_ids = {
        result.tool_call_id
        for message in refreshed_input.messages
        for result in tool_results_from_run_message(message) or ()
    }
    return not expected_tool_call_ids.issubset(refreshed_tool_result_ids)


async def _complete_voice_request(
    *,
    context: ConversationContext,
    user_message: MessageInDb,
) -> None:
    """Finish voice runtime state directly before emitting a lossy UI delta."""
    from eylo.pipelines.llm.streaming_tts import (
        complete_voice_sessions_for_response,
    )

    conversation = context.conversation
    try:
        await complete_voice_sessions_for_response(
            conversation_id=conversation.id,
            organization_id=conversation.organization_id,
            request_id=user_message.request_id,
        )
    except Exception as error:
        logger.error(
            "Could not finish conversation voice lifecycle error_type=%s",
            type(error).__name__,
        )


def _context_through_user_message(
    context: ConversationContext, user_message: MessageInDb
) -> ConversationContext:
    messages = context.messages or []
    ordered_messages = sorted(
        messages,
        key=lambda message: (message.created_at, str(message.id)),
    )
    for index, message in enumerate(ordered_messages):
        if message.id == user_message.id:
            return context.model_copy(
                update={"messages": ordered_messages[: index + 1]}
            )

    logger.warning(
        "Active user message %s was not present in conversation context %s",
        user_message.id,
        user_message.conversation_id,
    )
    return context


def _llm_overrides_from_settings(settings: ModelSettings) -> LLMOverrides:
    """Translate framework settings without exposing vendor enums to the framework."""
    try:
        return LLMOverrides(
            model=LLMModels(settings.model) if settings.model is not None else None,
            max_tokens=settings.max_tokens,
            temperature=settings.temperature,
            top_k=settings.top_k,
            top_p=settings.top_p,
            stop_sequences=settings.stop_sequences,
        )
    except (InvalidLLMConfig, ValueError):
        raise NotConfiguredError(
            capability=Capability.LLM,
            missing=["valid_pinned_provider_config"],
            configure_via="/api/llm-configs",
        ) from None


def _messages_from_run_input(
    run_input: RunInput,
    conversation_context: PlatformExecutionContext,
) -> list[MessageInDb]:
    created_at = arrow.utcnow().datetime
    return [
        _message_from_run_message(
            message,
            conversation_context,
            created_at=created_at + datetime.timedelta(microseconds=index),
        )
        for index, message in enumerate(run_input.messages)
    ]


def _prepare_messages_for_existing_vendor(
    messages: list[MessageInDb],
) -> list[MessageInDb]:
    """Fold framework system context into user messages before vendor transforms.

    Vendor adapters intentionally drop ``MessageKind.SYSTEM`` history entries.
    The framework adapter therefore folds the validated persisted summary into
    the first user message before handing history to those adapters.
    """
    compaction = latest_context_compaction(messages)
    prepared = uncompacted_messages(messages)
    if not prepared:
        return prepared

    first_user_idx = _first_user_index(prepared)
    if first_user_idx is not None and compaction is not None:
        prepared = _replace_message_text(
            prepared,
            first_user_idx,
            _append_context_section(
                prepared[first_user_idx].get_text_content() or "",
                "## Untrusted summary of earlier conversation:",
                compaction.summary.get_text_content() or "",
            ),
        )
    return prepared


def _first_user_index(messages: list[MessageInDb]) -> int | None:
    for index, message in enumerate(messages):
        if message.kind == MessageKind.USER:
            return index
    return None


def _last_user_index(messages: list[MessageInDb]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].kind == MessageKind.USER:
            return index
    return None


def _append_context_section(text: str, heading: str, context: str) -> str:
    if not context:
        return text
    return f"{text}\n\n---\n\n{heading}\n {context}"


def _replace_message_text(
    messages: list[MessageInDb],
    index: int,
    text: str,
) -> list[MessageInDb]:
    updated = list(messages)
    message = updated[index]
    preserved_blocks = []
    if isinstance(message.content, UserMessageContent):
        preserved_blocks = [
            block
            for block in message.content.content
            if not isinstance(block, TextContent)
        ]
    updated[index] = MessageInDb(
        **message.model_dump(exclude={"content"}),
        content=UserMessageContent(content=[TextContent(text=text), *preserved_blocks]),
    )
    return updated


def _message_from_run_message(
    message: RunMessage,
    conversation_context: PlatformExecutionContext,
    *,
    created_at: datetime.datetime,
) -> MessageInDb:
    tool_call = message.metadata.get("tool_call")
    if isinstance(tool_call, ToolCall):
        tool_call = ExistingToolCallMetadata(
            id=tool_call.id,
            name=tool_call.name,
            arguments=tool_call.arguments,
        )
    if tool_call is not None:
        tool_call = ExistingToolCallMetadata.model_validate(tool_call)
        return _tool_use_message_from(
            message, conversation_context, tool_call, created_at
        )

    tool_results = tool_results_from_run_message(message)
    if tool_results is not None:
        return _tool_result_message_from(
            message,
            conversation_context,
            tool_results,
            created_at,
        )

    kind = _message_kind_from_metadata(message) or _message_kind_from_role(message.role)
    content_kind = _content_kind_from_metadata(message) or MessageContentKind.TEXT
    if content_kind == MessageContentKind.WIDGET_RESPONSE:
        widget_response = message.metadata.get("widget_response")
        if widget_response is None:
            raise ValueError(
                "Widget response run message is missing structured content."
            )
        content = WidgetResponseMessageContent.model_validate(widget_response)
    else:
        content = _message_content_for_kind(
            kind,
            message.content,
            content_blocks=_content_blocks_from_metadata(message),
        )
    return _message_indb(
        message,
        conversation_context,
        kind=kind,
        content_kind=content_kind,
        content=content,
        created_at=created_at,
    )


def _tool_use_message_from(
    message: RunMessage,
    conversation_context: PlatformExecutionContext,
    tool_call: ExistingToolCallMetadata,
    created_at: datetime.datetime,
) -> MessageInDb:
    return _message_indb(
        message,
        conversation_context,
        kind=MessageKind.TOOL_USE,
        content_kind=MessageContentKind.TOOL,
        content=ToolUseMessageContent(
            content=ToolUseContent(
                id=tool_call.id,
                name=tool_call.name,
                input=tool_call.arguments,
            ),
        ),
        created_at=created_at,
    )


def _tool_result_message_from(
    message: RunMessage,
    conversation_context: PlatformExecutionContext,
    tool_results: tuple[ExistingToolResultMetadata, ...],
    created_at: datetime.datetime,
) -> MessageInDb:
    return _message_indb(
        message,
        conversation_context,
        kind=MessageKind.TOOL_RESULT,
        content_kind=MessageContentKind.TOOL,
        content=ToolResultMessageContent(
            content=[
                ToolResultContent(
                    tool_use_id=tool_result.tool_call_id,
                    name=tool_result.name,
                    content=tool_result.content,
                    is_error=tool_result.is_error,
                )
                for tool_result in tool_results
            ],
        ),
        created_at=created_at,
    )


def _message_indb(
    message: RunMessage,
    conversation_context: PlatformExecutionContext,
    *,
    kind: MessageKind,
    content_kind: MessageContentKind,
    content: MessageContentType,
    created_at: datetime.datetime,
) -> MessageInDb:
    meta = message.metadata.get("meta")
    if isinstance(meta, ModelResponseProvenance):
        meta = ModelResponseProvenance.model_validate(meta).model_dump(mode="json")
    elif isinstance(meta, ToolResultProvenance):
        meta = ToolResultProvenance.model_validate(meta).model_dump(mode="json")
    return MessageInDb(
        id=message.id or uuid4(),
        conversation_id=conversation_context.conversation.id,
        sender_participant_id=_sender_participant_id(conversation_context, kind),
        kind=kind,
        content_kind=content_kind,
        content=content,
        created_at=created_at,
        updated_at=created_at,
        meta=meta or None,
        request_id=_request_id_from_metadata(message.metadata),
    )


def _sender_participant_id(
    conversation_context: PlatformExecutionContext,
    kind: MessageKind,
) -> UUID:
    if kind == MessageKind.USER:
        contact = conversation_context.get_primary_contact()
        if contact is None:
            raise ValueError("ConversationContext has no primary contact participant.")
        return contact.id

    agent = conversation_context.get_primary_agent()
    if agent is None:
        raise ValueError("ConversationContext has no primary agent participant.")
    return agent.id


def _message_kind_from_role(role: str) -> MessageKind:
    normalized = role.lower()
    if normalized == "user":
        return MessageKind.USER
    if normalized == "system":
        return MessageKind.SYSTEM
    return MessageKind.ASSISTANT


def _message_kind_from_metadata(message: RunMessage) -> MessageKind | None:
    value = message.metadata.get("kind")
    if value is None:
        return None
    if isinstance(value, MessageKind):
        return value
    try:
        return MessageKind(str(value))
    except ValueError:
        return None


def _content_kind_from_metadata(message: RunMessage) -> MessageContentKind | None:
    value = message.metadata.get("content_kind")
    if value is None:
        return None
    if isinstance(value, MessageContentKind):
        return value
    try:
        return MessageContentKind(str(value))
    except ValueError:
        return None


def _message_content_for_kind(
    kind: MessageKind,
    content: str,
    *,
    content_blocks: TextMessageContentBlocks | None = None,
) -> AssistantMessageContent | SystemMessageContent | UserMessageContent:
    content_value = content_blocks if content_blocks is not None else content
    if kind == MessageKind.USER:
        return UserMessageContent(content=content_value)
    if kind == MessageKind.SYSTEM:
        return SystemMessageContent(content=content_value)
    return AssistantMessageContent(content=content_value)


def _content_blocks_from_metadata(
    message: RunMessage,
) -> TextMessageContentBlocks | None:
    value = message.metadata.get("content_blocks")
    if value is None:
        return None
    return UserMessageContent(content=value).content


def _model_response_from_llm_response(response: LLMResponse) -> ModelResponse:
    return ModelResponse(
        id=response.id,
        model=response.model,
        blocks=tuple(_model_block_from_llm_block(block) for block in response.content),
        usage=_usage_from_llm_response(response),
        stop_reason=(
            ModelStopReason(response.stop_reason.value)
            if response.stop_reason is not None
            else None
        ),
        metadata=response.metadata.to_json(),
    )


def _model_block_from_llm_block(block: LLMContentBlock) -> ModelOutputBlock:
    if block.type == LLMContentType.TEXT:
        return ModelTextBlock(
            content=block.content.text,
        )
    if block.type == LLMContentType.TOOL_USE:
        return ModelToolCallBlock(
            content=ToolCall(
                id=block.content.id,
                name=block.content.name,
                arguments=block.content.input,
            ),
        )
    return ModelReasoningBlock(
        content=block.content.text,
    )


def _usage_from_llm_response(response: LLMResponse) -> ModelUsage:
    if response.usage is None:
        return ModelUsage()
    return ModelUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
        reasoning_tokens=response.usage.reasoning_tokens or 0,
    )


def _terminal_text_for_result(result: RunResult) -> str:
    if result.final_output:
        return result.final_output
    if result.is_success:
        return ErrorMessages.EMPTY_RESPONSE
    if result.status == RunStatus.WAITING_FOR_APPROVAL:
        return "I need approval before continuing this request."
    if result.status == RunStatus.WAITING_FOR_INPUT:
        return "I need more information before continuing this request."
    if result.status is RunStatus.TIMED_OUT:
        return ErrorMessages.REQUEST_TIMEOUT
    if result.status is RunStatus.MAX_TURNS_EXCEEDED:
        return ErrorMessages.MAX_ITERATIONS
    if (
        isinstance(result.metadata, RunFailureMetadata)
        and result.metadata.failure_code is RunFailureCode.MODEL_OUTPUT_LIMIT
    ):
        return ErrorMessages.MODEL_OUTPUT_LIMIT
    return ErrorMessages.GENERIC_ERROR


def _agent_run_terminal_fields(
    result: RunResult,
    *,
    conversation_id: UUID,
    origin_message_id: UUID,
    final_message_id: UUID,
) -> tuple[
    AgentRunLifecycle,
    AgentRunOutcome,
    dict[str, JsonValue] | None,
    str | None,
    str | None,
]:
    """Map framework conclusions onto the product's separate lifecycle/outcome."""
    if result.status is RunStatus.COMPLETED:
        return (
            AgentRunLifecycle.COMPLETED,
            AgentRunOutcome.ACHIEVED,
            _conversation_run_result(
                result,
                conversation_id=conversation_id,
                origin_message_id=origin_message_id,
                final_message_id=final_message_id,
            ),
            None,
            None,
        )
    if result.status in {RunStatus.TIMED_OUT, RunStatus.MAX_TURNS_EXCEEDED}:
        reason = f"Conversation execution ended with {result.status.value}."
        return (
            AgentRunLifecycle.COMPLETED,
            AgentRunOutcome.EXHAUSTED,
            _conversation_run_result(
                result,
                conversation_id=conversation_id,
                origin_message_id=origin_message_id,
                final_message_id=final_message_id,
            ),
            reason,
            None,
        )
    return (
        AgentRunLifecycle.FAILED,
        AgentRunOutcome.FAILED,
        None,
        None,
        f"Conversation execution ended with {result.status.value}.",
    )


def _agent_run_pause_fields(
    result: RunResult,
) -> tuple[AgentInputRequestKind, str, dict, dict]:
    """Project framework interruption metadata onto a typed product request."""
    interruption = result.metadata
    if not isinstance(interruption, (RunApprovalInterruption, RunInputInterruption)):
        raise ValueError("Framework pause is missing continuation metadata.")
    if result.status is RunStatus.WAITING_FOR_APPROVAL and isinstance(
        interruption, RunApprovalInterruption
    ):
        approval = interruption.approval_request
        request = approval
        prompt = (
            approval.action_summary
            or approval.policy_reason
            or "Approve this agent action?"
        )
        expected_schema = {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": [decision.value for decision in AgentApprovalDecision],
                },
                "comment": {"type": "string"},
            },
            "required": ["decision"],
            "additionalProperties": False,
        }
        kind = AgentInputRequestKind.APPROVAL
    elif result.status is RunStatus.WAITING_FOR_INPUT and isinstance(
        interruption, RunInputInterruption
    ):
        details = interruption.input_request
        request = details
        prompt = details.prompt or "Provide the requested information."
        expected_schema = details.expected_input_schema
        kind = AgentInputRequestKind.INPUT
    else:
        raise ValueError("Framework result is not an input or approval pause.")

    return (
        kind,
        prompt,
        expected_schema,
        RunContinuation(
            framework=interruption.continuation, request=request
        ).model_dump(mode="json"),
    )


def _conversation_run_result(
    result: RunResult,
    *,
    conversation_id: UUID,
    origin_message_id: UUID,
    final_message_id: UUID,
) -> dict[str, JsonValue]:
    """Store bounded product references, never a provider response payload."""
    return ConversationRunSummary(
        conversation_id=conversation_id,
        origin_message_id=origin_message_id,
        final_message_id=final_message_id,
        framework_run_id=result.run_id,
        framework_status=result.status,
        usage=result.usage,
    ).model_dump(mode="json")


def _request_status_for_result(result: RunResult) -> RequestStatus:
    if result.is_success:
        return RequestStatus.COMPLETED
    if result.status in _PAUSE_STATUSES:
        return RequestStatus.PROCESSING
    return RequestStatus.FAILED


def _should_emit_terminal_message_tokens(result: RunResult) -> bool:
    return (
        isinstance(result.metadata, RunTerminalMetadata)
        and result.metadata.terminal_artifact is None
    ) or result.status in _PAUSE_STATUSES


async def _terminal_artifact_message(
    result: RunResult,
    *,
    context: ConversationContext,
    user_message: MessageInDb,
    message_service: MessageService,
) -> MessageInDb | None:
    """Resolve committed tool output, not the history snapshot from before the tool.

    Tool-result persistence commits the artifact before terminal resolution.
    Loading its exact identity avoids rebuilding the whole conversation and
    preserves authority checks even when the tool supplied a foreign reference.
    """
    result = RunResult.model_validate(result)
    if not isinstance(result.metadata, RunTerminalMetadata):
        return None
    reference = result.metadata.terminal_artifact
    if reference is None:
        return None
    artifact = ConversationMessageArtifact.model_validate(reference.model_dump())

    message = await message_service.get_(artifact.id)
    if (
        message.id != artifact.id
        or message.conversation_id != context.conversation.id
        or message.conversation_id != user_message.conversation_id
        or message.kind != MessageKind.ASSISTANT
        or message.content_kind != MessageContentKind.WIDGET
        or message.request_id != user_message.request_id
    ):
        raise ValueError("Terminal artifact message authority is invalid.")
    return message
