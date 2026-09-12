"""Run a swarm agent mini ReAct loop through pipeline composition.

Loads the target agent from DB, fetches its tools, and runs an iterative
tool-calling loop using the agent's system prompt and model. The task
instruction becomes the user message.
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.common.contracts.llm_response import LLMStopReason
from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.database import start_transaction
from eylo.framework.agents.errors import ModelOutputLimitError
from eylo.modules.agent_runs.budgets import meter_current_agent_run_usage
from eylo.modules.agents.domain import ResolvedExecutableAgent
from eylo.modules.agents.services.tool_execution_utils import (
    ToolDispatchError,
    ToolExecutionResult,
    ToolInputValidationError,
    execute_exact_tool,
    resolve_model_tool,
)
from eylo.modules.conversations.schemas.messages import MessageKind
from eylo.modules.llm_configs.domain import ResolvedLLM
from eylo.modules.parallel_agents.schemas import TaskContent, WorkerResult
from eylo.pipelines.llm.runtime import (
    build_llm_adapter,
    resolve_background_agent,
    response_messages,
    text_message,
    text_parts,
    tool_result_messages,
    tool_uses,
)
from eylo.pipelines.parallel_agents.context import (
    AgentTaskConversationContext,
    build_task_conversation_context,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS: Final = 5
MODEL_SAFE_TOOL_ERROR: Final = "Error: Tool execution failed."

# Tools that workers must never call
BLOCKED_TOOL_PREFIXES: Final = ("handoff__", "spawn_task_fnf")

class SwarmWorkerRuntime(BaseModel):
    """One exact topology member and its resolved model authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    executable: ResolvedExecutableAgent
    llm: ResolvedLLM


class SwarmAgentWorker:
    """Runs a swarm agent's ReAct loop on a task instruction.

    Loads the agent config, builds a tool list (excluding handoff and
    spawn_task_fnf), and iterates: LLM call -> tool execution -> repeat
    until a text response is produced or MAX_ITERATIONS is reached.
    """

    def __init__(
        self,
        task_content: TaskContent,
        organization_id: UUID,
        conversation_id: UUID,
    ) -> None:
        self.task_content = task_content
        self.organization_id = organization_id
        self.conversation_id = conversation_id
        self._cached_ctx: AgentTaskConversationContext | None = None

    async def run(self) -> WorkerResult:
        """Execute the swarm agent's ReAct loop and return result."""
        runtime = await self._load_agent_and_tools()
        agent = runtime.executable.agent
        tools = list(runtime.executable.tools)
        resolved = runtime.llm
        self._cached_ctx = None

        adapter = build_llm_adapter(resolved)
        request_id = uuid4()
        messages = [
            text_message(
                agent.id,
                self.conversation_id,
                MessageKind.USER,
                self.task_content.instruction,
                request_id=request_id,
            )
        ]
        last_text_parts: list[str] = []

        for iteration in range(MAX_ITERATIONS):
            response = await adapter.run_inference(
                messages=messages,
                system_prompt=runtime.executable.system_prompt or "",
                tools=tools,
                llm_config=LLMInferenceConfig(generation=resolved.generation),
            )
            usage = response.usage
            await meter_current_agent_run_usage(
                input_tokens=None if usage is None else usage.input_tokens,
                output_tokens=None if usage is None else usage.output_tokens,
            )
            if response.stop_reason is LLMStopReason.MAX_TOKENS:
                raise ModelOutputLimitError
            last_text_parts = text_parts(response.content)
            requested_tools = tool_uses(response.content)

            if not requested_tools:
                text = "\n".join(last_text_parts).strip() or "Task completed."
                return WorkerResult(
                    text=text,
                    model_used=response.model,
                    iterations_used=iteration + 1,
                )

            messages.extend(
                response_messages(
                    sender_id=agent.id,
                    conversation_id=self.conversation_id,
                    request_id=request_id,
                    response=response,
                )
            )
            results: list[ToolExecutionResult] = []
            for tool_use in requested_tools:
                results.append(
                    await self._execute_tool(tool_use.name, tool_use.input, runtime)
                )
            messages.extend(
                tool_result_messages(
                    sender_id=agent.id,
                    conversation_id=self.conversation_id,
                    request_id=request_id,
                    calls=requested_tools,
                    results=results,
                )
            )

            logger.debug(
                "Swarm worker iteration %d: %d tool calls",
                iteration + 1,
                len(requested_tools),
            )

        logger.warning(
            "Swarm worker hit max iterations (%d) for agent=%s",
            MAX_ITERATIONS,
            self.task_content.swarm_id,
        )
        text = (
            "\n".join(last_text_parts).strip()
            if last_text_parts
            else "Task processing reached iteration limit without a final answer."
        )
        return WorkerResult(
            text=text,
            model_used=resolved.generation.model.value,
            iterations_used=MAX_ITERATIONS,
        )

    async def _load_agent_and_tools(self) -> SwarmWorkerRuntime:
        """Load the exact filed swarm agent revision and its exact tools."""
        async with start_transaction(ro=True):
            from eylo.modules.templates.domain import TemplateConsumerKind
            from eylo.pipelines.agents import build_executable_swarm_resolver

            if (
                self.task_content.swarm_agent_id is None
                or self.task_content.swarm_agent_revision is None
                or self.task_content.swarm_topology_id is None
                or self.task_content.swarm_topology_revision is None
            ):
                raise ValueError("Swarm task lacks exact topology/agent revisions.")
            topology = await build_executable_swarm_resolver().resolve_exact(
                organization_id=self.organization_id,
                swarm_id=self.task_content.swarm_topology_id,
                revision=self.task_content.swarm_topology_revision,
                consumer_kind=TemplateConsumerKind.SWARM_AGENT,
            )
            member = topology.member_by_agent_id(self.task_content.swarm_agent_id)
            if (
                member is None
                or member.executable_agent.ref.revision
                != self.task_content.swarm_agent_revision
            ):
                raise ValueError(
                    "Swarm task agent is not authorized by its pinned topology."
                )
            executable = member.executable_agent
            agent = executable.agent
            tools = list(executable.tools)

            # Filter out blocked tools
            tools = [
                t
                for t in tools
                if t.llm_config
                and not any(
                    t.llm_config.name.startswith(prefix)
                    for prefix in BLOCKED_TOOL_PREFIXES
                )
            ]
            resolved = await resolve_background_agent(agent)

        if not executable.system_prompt:
            raise ValueError("Swarm agent revision has no authored instructions.")
        return SwarmWorkerRuntime(
            executable=executable.with_tools(tuple(tools)), llm=resolved
        )

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, JsonValue],
        runtime: SwarmWorkerRuntime,
    ) -> ToolExecutionResult:
        """Resolve the advertised name, then dispatch by the exact stored kind."""
        # Enforce blocklist at execution time — the LLM may hallucinate
        # tool names that were filtered from its tool list
        if any(tool_name.startswith(prefix) for prefix in BLOCKED_TOOL_PREFIXES):
            logger.warning("Worker tool request rejected code=blocked_tool_prefix")
            return MODEL_SAFE_TOOL_ERROR

        try:
            tool = resolve_model_tool(runtime.executable.tools, tool_name)
        except ToolDispatchError as error:
            logger.warning(
                "Worker tool resolution rejected error_type=%s",
                type(error).__name__,
            )
            return MODEL_SAFE_TOOL_ERROR

        try:
            ctx = await self._get_conversation_context(runtime.executable)
            return await execute_exact_tool(tool, tool_input, ctx)
        except ToolInputValidationError:
            logger.warning(
                "Tool input rejected tool=%s@%s code=input_invalid",
                tool.id,
                tool.published_revision,
            )
            return "Error: Invalid input provided to the tool."
        except ToolDispatchError as error:
            logger.warning(
                "Worker tool dispatch rejected tool=%s@%s error_type=%s",
                tool.id,
                tool.published_revision,
                type(error).__name__,
            )
            return MODEL_SAFE_TOOL_ERROR
        except Exception as error:
            logger.warning(
                "Worker tool execution failed tool=%s@%s error_type=%s",
                tool.id,
                tool.published_revision,
                type(error).__name__,
            )
            return MODEL_SAFE_TOOL_ERROR

    async def _get_conversation_context(
        self, executable: ResolvedExecutableAgent
    ) -> AgentTaskConversationContext:
        """Cache the worker's exact actor, never the parent's tool authority."""
        if self._cached_ctx is not None:
            actor = self._cached_ctx.execution_participant
            if (
                actor.agent_id != executable.ref.definition_id
                or actor.agent_revision != executable.ref.revision
            ):
                raise ValueError("Swarm tool context changed its execution authority.")
            return self._cached_ctx
        self._cached_ctx = await build_task_conversation_context(
            organization_id=self.organization_id,
            conversation_id=self.conversation_id,
            executable=executable,
        )
        return self._cached_ctx
