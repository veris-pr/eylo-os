"""Run a published background Agent within its parent durable Agent run."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final
from uuid import UUID

from eylo.common.contracts.background_task import BackgroundTaskOutcome
from eylo.common.database import start_transaction
from eylo.framework.agents.common import FrameworkMetadata
from eylo.framework.agents.config import RunConfig
from eylo.framework.agents.context import RunInput
from eylo.framework.agents.result import RunResult
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.llm_configs.wiring import resolve_pinned_llm
from eylo.modules.parallel_agents.schemas import TaskContent, WorkerResult
from eylo.pipelines.outbound.durable_execution import DurableStepContext
from eylo.pipelines.parallel_agents.context import build_task_conversation_context

if TYPE_CHECKING:
    from eylo.framework.agents.agent import AgentSpec
    from eylo.modules.agents.domain import ResolvedExecutableAgent
    from eylo.pipelines.agent_execution_context import PlatformRunState
    from eylo.pipelines.conversation.conversation_runner import (
        ExistingConversationModel,
    )

logger = logging.getLogger(__name__)

BACKGROUND_MAX_HANDOFFS: Final = 0


class BackgroundTaskMessageMetadata(FrameworkMetadata):
    """The dispatched task correlation attached to its transient user message."""

    request_id: str


class BackgroundTaskInputMetadata(FrameworkMetadata):
    """Conversation and task identity carried through the framework boundary."""

    conversation_id: str
    request_id: str


def background_run_config(stored_config: RunConfig | None = None) -> RunConfig:
    """Copy settings with the background-run handoff convention.

    Agent provider overrides do not contain run budgets. Only an explicitly
    supplied RunConfig can change the other runner limits here. The framework's
    max_handoffs field is reserved; background handoff refusal belongs to the
    published-agent/tool policies, not this configuration value.
    """
    base = (
        RunConfig.model_validate(stored_config)
        if stored_config is not None
        else RunConfig()
    )
    return base.model_copy(update={"max_handoffs": BACKGROUND_MAX_HANDOFFS})


class BackgroundAgentWorker:
    """Executes one dispatched background agent task."""

    def __init__(
        self,
        task_content: TaskContent,
        organization_id: UUID,
        conversation_id: UUID,
        task_message_id: UUID,
        agent_run_id: UUID,
        durable_context: DurableStepContext,
    ) -> None:
        self.task_content = task_content
        self.organization_id = organization_id
        self.conversation_id = conversation_id
        self.task_message_id = task_message_id
        self.agent_run_id = agent_run_id
        self.durable_context = durable_context

    async def run(self) -> WorkerResult:
        from eylo.modules.agents.implementations import BACKGROUND_IMPLEMENTATIONS
        from eylo.modules.templates.domain import TemplateConsumerKind
        from eylo.pipelines.agents import build_executable_agent_resolver

        agent_id = self.task_content.background_agent_id
        agent_revision = self.task_content.background_agent_revision
        if agent_id is None or agent_revision is None:
            raise ValueError("Background task lacks an exact agent revision.")
        async with start_transaction(ro=True):
            resolved = await build_executable_agent_resolver().resolve_exact(
                organization_id=self.organization_id,
                agent_id=agent_id,
                revision=agent_revision,
                consumer_kind=TemplateConsumerKind.BACKGROUND_AGENT,
            )
        agent = resolved.agent

        if agent.implementation:
            # First-party code, which owns its own side effect and decides for
            # itself whether the work is still needed.
            implementation = BACKGROUND_IMPLEMENTATIONS.get(agent.implementation)
            if implementation is None:
                # Registered at write time, gone by dispatch time — a removed
                # or renamed built-in. Recorded, not silently skipped.
                raise ValueError(
                    f"Background agent {agent_id} names implementation "
                    f"{agent.implementation!r}, which is not registered."
                )
            return await self._run_implementation(agent)

        return await self._run_prompt_agent(resolved)

    async def _run_implementation(self, agent: AgentInDb) -> WorkerResult:
        """Keep execution authority distinct from the conversation being processed."""
        from eylo.pipelines.conversation.background_implementations import (
            run_implementation,
        )

        implementation = agent.implementation
        if implementation is None:
            raise ValueError("Background agent does not name an implementation.")
        context = await self._conversation_context()
        outcome = await run_implementation(agent=agent, context=context)

        return WorkerResult(
            text=""
            if outcome is BackgroundTaskOutcome.COMPLETED
            else "No work required.",
            model_used=implementation,
            iterations_used=1,
            outcome=outcome,
        )

    async def _run_prompt_agent(
        self, resolved: ResolvedExecutableAgent
    ) -> WorkerResult:
        """Run the exact background agent and its explicit tools without handoffs.

        Model/tool exchange uses the durable transcript. The current shared
        tool and transcript implementations still require the enclosing DB
        session. Model config resolution reuses it without retaining the session.
        """
        from eylo.framework.agents.hooks import RunCallbacks
        from eylo.framework.agents.runner import FrameworkRunner
        from eylo.pipelines.agent_execution_context import PlatformRunState

        context = await build_task_conversation_context(
            organization_id=self.organization_id,
            conversation_id=self.conversation_id,
            executable=resolved,
        )
        run_config = background_run_config()
        spec = self._agent_spec(resolved)

        from eylo.pipelines.agent_run_transcript import (
            AgentRunTranscript,
            AgentRunTranscriptBridge,
            PendingToolCallsModel,
            with_replay_messages,
        )
        from eylo.pipelines.conversation.tool_executor import (
            PlatformToolExecutor,
        )

        async with start_transaction():
            transcript = AgentRunTranscript(
                organization_id=self.organization_id,
                agent_run_id=self.agent_run_id,
            )
            replay = await transcript.replay()
            local_context: PlatformRunState[ConversationContext] = PlatformRunState(
                conversation_context=context,
                agent_run_id=self.agent_run_id,
                durable_context=self.durable_context,
            )
            bridge = AgentRunTranscriptBridge(
                transcript=transcript,
                local_context=local_context,
                command_ids=replay.command_ids,
            )
            model = PendingToolCallsModel(
                self._build_model(local_context),
                agent_run_id=self.agent_run_id,
                pending_calls=replay.pending_calls,
            )
            runner = FrameworkRunner(
                model,
                tool_executor=PlatformToolExecutor(),
                callbacks=RunCallbacks(
                    after_model_response=bridge.after_model_response,
                    before_tool_call=bridge.before_tool_call,
                    after_tool_result=bridge.after_tool_result,
                ),
            )
            result = await runner.run(
                spec,
                with_replay_messages(
                    self._build_run_input(resolved, context, spec),
                    replay,
                ),
                config=run_config,
                local_context=local_context,
            )
        from eylo.framework.agents.result import RunStatus

        if result.status is not RunStatus.COMPLETED:
            summary = (
                result.error_message or "Background framework run did not complete."
            )
            raise RuntimeError(f"{result.status.value}: {summary}")

        return WorkerResult(
            text=_result_text(result),
            model_used=_model_of(result, spec),
            iterations_used=len(result.model_responses or ()),
            outcome=BackgroundTaskOutcome.COMPLETED,
        )

    async def _conversation_context(self) -> ConversationContext:
        """Load the conversation snapshot in an owned read transaction."""
        from eylo.modules.conversations.services.conversations import (
            ConversationService,
        )
        from eylo.pipelines.conversation.context import (
            ConversationContextService,
        )

        async with start_transaction(ro=True):
            conversation = await ConversationService().get_(self.conversation_id)
            return await ConversationContextService().build(conversation)

    @staticmethod
    def _agent_spec(resolved: ResolvedExecutableAgent) -> AgentSpec:
        """Expose the exact revision's tools; background runs never hand off."""
        from eylo.pipelines.conversation.domain import (
            agent_spec_from_indb,
            tool_spec_from_indb,
        )

        tools = tuple(tool_spec_from_indb(tool) for tool in resolved.tools)
        return agent_spec_from_indb(resolved.agent, tools=tools, handoffs=())

    def _build_run_input(
        self,
        resolved: ResolvedExecutableAgent,
        context: ConversationContext,
        spec: AgentSpec,
    ) -> RunInput:
        """LLM-visible input for a prompt-only background run."""
        from eylo.framework.agents.context import RunInput, RunMessage
        from eylo.pipelines.conversation.domain import run_message_from_indb

        history = tuple(
            run_message_from_indb(message) for message in context.get_messages()
        )

        return RunInput(
            instructions=resolved.system_prompt or spec.instructions,
            messages=history
            + (
                RunMessage(
                    role="user",
                    content=self.task_content.instruction,
                    metadata=BackgroundTaskMessageMetadata(
                        request_id=str(self.task_message_id)
                    ),
                ),
            ),
            tools=spec.tools,
            metadata=BackgroundTaskInputMetadata(
                conversation_id=str(self.conversation_id),
                request_id=str(self.task_message_id),
            ),
        )

    def _build_model(
        self,
        context: PlatformRunState[ConversationContext],
    ) -> ExistingConversationModel[ConversationContext]:
        """The vendor adapter. Raises NotConfiguredError if none resolves."""
        from eylo.pipelines.conversation.conversation_runner import (
            ExistingConversationModel,
        )

        return ExistingConversationModel(
            context,
            llm_resolver=resolve_pinned_llm,
        )


def _result_text(result: RunResult) -> str:
    """Return the first text block from the latest response that contains text."""
    from eylo.framework.agents.model import ModelBlockKind

    for response in reversed(result.model_responses or ()):
        for block in response.blocks or ():
            if block.kind is ModelBlockKind.TEXT:
                return block.content
    return ""


def _model_of(result: RunResult, spec: AgentSpec) -> str:
    if result.model_responses:
        return result.model_responses[-1].model
    return spec.model_settings.model or "unknown"
