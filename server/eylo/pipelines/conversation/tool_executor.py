"""Framework adapter for current platform tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError

from eylo.common.contracts.conversation import WIDGET_TOOL_PREFIX
from eylo.framework.agents.context import RunContext
from eylo.framework.agents.tool import (
    ToolCall,
    ToolCompletionMetadata,
    ToolCompletionMode,
    ToolResult,
)
from eylo.modules.agents.services.tool_execution_utils import (
    AmbiguousModelToolNameError,
    ModelToolNotFoundError,
    ToolApprovalRequiredError,
    ToolExecutionBlockedError,
    require_tool_execution_allowed,
    resolve_model_tool,
)
from eylo.modules.conversations.constants import HANDOFF_TOOL_PREFIX
from eylo.modules.interfaces.schemas.tools import WidgetDeliveryReceipt
from eylo.modules.tools.models import ToolKind
from eylo.pipelines.agent_execution_context import (
    PlatformExecutionContext,
    PlatformRunState,
    execution_context_from,
)
from eylo.pipelines.conversation.completion import ConversationMessageArtifact
from eylo.pipelines.conversation.handoff import HandoffOutcome, HandoffToolMetadata
from eylo.pipelines.conversation.tool_dispatch import (
    execute_handoff,
    execute_registered_tool,
)
from eylo.pipelines.email.tool_execution import (
    SEND_EMAIL_TOOL_NAME,
    execute_agent_email_tool,
)
from eylo.pipelines.integrations_v2.execution import execute_curated_tool
from eylo.pipelines.mcp.tool_execution import execute_mcp_tool
from eylo.pipelines.sandbox.tool_execution import (
    SANDBOX_TOOL_SLUGS,
    execute_agent_sandbox_tool,
)
from eylo.pipelines.sor.tool_execution import (
    execute_sor_mutation_tool,
    execute_sor_read_tool,
)
from eylo.pipelines.telephony.tool_execution import (
    PLACE_CALL_TOOL_NAME,
    execute_agent_place_call_tool,
)
from eylo.pipelines.voice.end_call import (
    END_CALL_TOOL_NAME,
    execute_agent_end_call_tool,
    is_live_voice_session_active,
)
from eylo.pipelines.voice.live_buffer import LiveVoiceBufferIdentity
from eylo.sockets.llm import LLMToolUseBlock
from eylo.sor.runtime.tools import resolve_sor_tool
from eylo.sor.shared.contracts import SorToolEffect

if TYPE_CHECKING:
    from eylo.pipelines.outbound.durable_execution import (
        CommandStepContext,
        DurableStepContext,
    )
    from eylo.sockets.email.sendgrid import SendGridHttpTransport
    from eylo.sockets.mcp.client import MCPHttpTransport


class PlatformToolExecutor:
    """Execute framework tool calls through platform-owned dispatch."""

    def __init__(
        self,
        *,
        mcp_transport: MCPHttpTransport | None = None,
        email_transport: SendGridHttpTransport | None = None,
    ) -> None:
        self._mcp_transport = mcp_transport
        self._email_transport = email_transport

    async def execute(
        self,
        context: RunContext,
        call: ToolCall,
    ) -> ToolResult:
        """Execute one tool call using current platform dispatch."""
        conversation_context = execution_context_from(context.local_context)
        await _refresh_tool_availability(conversation_context, context.local_context)
        block = LLMToolUseBlock(
            id=call.id,
            name=call.name,
            input=call.arguments,
        )

        if call.name.startswith(HANDOFF_TOOL_PREFIX):
            source_participant = conversation_context.get_primary_agent()
            outcome = HandoffOutcome.model_validate(
                await execute_handoff(conversation_context, block)
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=not outcome.succeeded,
                metadata=HandoffToolMetadata.from_outcome(
                    outcome,
                    swarm_id=conversation_context.conversation.swarm_id,
                    swarm_revision=conversation_context.conversation.swarm_revision,
                    source_agent_revision=source_participant.agent_revision
                    if source_participant
                    else None,
                    source_participant_id=source_participant.id
                    if source_participant
                    else None,
                ),
            )

        try:
            requested_tool = resolve_model_tool(
                conversation_context.get_tools(),
                call.name,
            )
        except (ModelToolNotFoundError, AmbiguousModelToolNameError):
            return ToolResult(
                tool_call_id=call.id,
                content={
                    "kind": "integration_error",
                    "error": "tool_not_available",
                },
                is_error=True,
            )
        sor_tool = (
            resolve_sor_tool(requested_tool.slug)
            if requested_tool.kind is ToolKind.SYSTEM
            else None
        )
        if sor_tool is not None:
            try:
                require_tool_execution_allowed(requested_tool)
            except (ToolExecutionBlockedError, ToolApprovalRequiredError) as error:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "sor_error",
                        "error": "tool_execution_blocked",
                    },
                    is_error=True,
                    metadata={
                        "sor_execution": True,
                        "tool_policy_error": type(error).__name__,
                    },
                )
            if sor_tool[1].effect is SorToolEffect.READ:
                outcome = await execute_sor_read_tool(
                    tool_name=requested_tool.slug,
                    tool_input=call.arguments,
                    conversation_context=conversation_context,
                )
            else:
                state = _durable_run_execution_state(context.local_context, call.id)
                agent_run_id = _agent_run_id_from(context.local_context)
                if state is None or agent_run_id is None:
                    return ToolResult(
                        tool_call_id=call.id,
                        content={
                            "kind": "sor_error",
                            "error": "durable_agent_run_required",
                        },
                        is_error=True,
                        metadata={"sor_execution": True},
                    )
                _tool_use_message_id, durable_context = state
                outcome = await execute_sor_mutation_tool(
                    tool_name=requested_tool.slug,
                    tool_call_id=call.id,
                    tool_input=call.arguments,
                    conversation_context=conversation_context,
                    agent_run_id=agent_run_id,
                    durable_context=durable_context,
                )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=dict(outcome.metadata),
            )
        if (
            requested_tool.kind is ToolKind.SYSTEM
            and requested_tool.slug == END_CALL_TOOL_NAME
        ):
            live_voice_identity = _live_voice_identity_from(
                context.local_context,
                conversation_context,
            )
            if live_voice_identity is not None:
                outcome = await execute_agent_end_call_tool(
                    conversation_context=conversation_context,
                    identity=live_voice_identity,
                )
                return ToolResult(
                    tool_call_id=call.id,
                    content=outcome.content,
                    is_error=outcome.is_error,
                    metadata=outcome.metadata,
                )
        if (
            requested_tool.kind is ToolKind.SYSTEM
            and requested_tool.slug in SANDBOX_TOOL_SLUGS
        ):
            state = _durable_run_execution_state(context.local_context, call.id)
            agent_run_id = _agent_run_id_from(context.local_context)
            if state is None or agent_run_id is None:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "success": False,
                        "error": "durable_agent_run_required",
                        "message": (
                            "Sandbox work requires a durable agent run and is "
                            "unavailable in live voice."
                        ),
                    },
                    is_error=True,
                    metadata={
                        "sandbox_execution": True,
                        "sandbox_failure_code": "durable_agent_run_required",
                    },
                )
            tool_use_message_id, durable_context = state
            agent = conversation_context.primary_agent
            if agent is None:
                raise ValueError("Sandbox execution requires a published agent.")
            outcome = await execute_agent_sandbox_tool(
                tool_slug=requested_tool.slug,
                tool_input=call.arguments,
                organization_id=conversation_context.conversation.organization_id,
                agent_id=agent.id,
                agent_run_id=agent_run_id,
                tool_command_id=tool_use_message_id,
                durable_context=durable_context,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=outcome.metadata,
            )
        if (
            requested_tool.kind is ToolKind.SYSTEM
            and requested_tool.slug == SEND_EMAIL_TOOL_NAME
        ):
            state = _durable_execution_state(context.local_context, call.id)
            if state is None:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "email_error",
                        "error": "durable_execution_required",
                    },
                    is_error=True,
                    metadata={"email_delivery": True},
                )
            tool_use_message_id, durable_context = state
            outcome = await execute_agent_email_tool(
                tool_input=call.arguments,
                conversation_context=conversation_context,
                tool_use_message_id=tool_use_message_id,
                durable_context=durable_context,
                sendgrid_transport=self._email_transport,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=dict(outcome.metadata),
            )
        if (
            requested_tool.kind is ToolKind.SYSTEM
            and requested_tool.slug == PLACE_CALL_TOOL_NAME
        ):
            state = _durable_execution_state(context.local_context, call.id)
            if state is None:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "telephony_error",
                        "error": "durable_execution_required",
                    },
                    is_error=True,
                    metadata={"telephony_delivery": True},
                )
            tool_use_message_id, durable_context = state
            outcome = await execute_agent_place_call_tool(
                tool_input=call.arguments,
                conversation_context=conversation_context,
                tool_use_message_id=tool_use_message_id,
                durable_context=durable_context,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=dict(outcome.metadata),
            )
        if requested_tool.kind is ToolKind.CURATED:
            # Policy is not enforced here. A curated tool's definition is code
            # and cannot change under a running deployment, so the only mutable
            # fact is operator policy — and the module service reads it live
            # while resolving the grant, before any client exists.
            state = _durable_execution_state(context.local_context, call.id)
            if state is None:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "curated_error",
                        "error": "durable_execution_required",
                    },
                    is_error=True,
                    metadata={"curated_execution": True},
                )
            tool_use_message_id, durable_context = state
            outcome = await execute_curated_tool(
                tool_id=UUID(str(requested_tool.id)),
                tool_input=call.arguments,
                conversation_context=conversation_context,
                tool_use_message_id=tool_use_message_id,
                durable_context=durable_context,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=dict(outcome.metadata),
            )
        if requested_tool.kind is ToolKind.MCP:
            try:
                require_tool_execution_allowed(requested_tool)
            except (ToolExecutionBlockedError, ToolApprovalRequiredError) as error:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "integration_error",
                        "error": "tool_execution_blocked",
                    },
                    is_error=True,
                    metadata={"tool_policy_error": type(error).__name__},
                )
            state = _durable_execution_state(context.local_context, call.id)
            if state is None:
                return ToolResult(
                    tool_call_id=call.id,
                    content={
                        "kind": "integration_error",
                        "error": "durable_execution_required",
                    },
                    is_error=True,
                    metadata={"mcp_execution": True},
                )
            tool_use_message_id, durable_context = state
            outcome = await execute_mcp_tool(
                tool=requested_tool,
                tool_input=call.arguments,
                conversation_context=conversation_context,
                tool_use_message_id=tool_use_message_id,
                durable_context=durable_context,
                transport=self._mcp_transport,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=outcome.content,
                is_error=outcome.is_error,
                metadata=dict(outcome.metadata),
            )

        content = await execute_registered_tool(conversation_context, block)
        if requested_tool.slug == WIDGET_TOOL_PREFIX and isinstance(content, dict):
            try:
                receipt = WidgetDeliveryReceipt.model_validate(content)
            except ValidationError:
                return ToolResult(
                    tool_call_id=call.id,
                    content="Widget delivery returned an invalid receipt.",
                    is_error=True,
                )
            return ToolResult(
                tool_call_id=call.id,
                content=content,
                metadata=ToolCompletionMetadata(
                    terminal_response=ToolCompletionMode.COMPLETE,
                    terminal_output="Interactive content delivered.",
                    terminal_artifact=ConversationMessageArtifact(
                        id=receipt.widget_message_id
                    ).to_framework(),
                ),
            )
        return ToolResult(tool_call_id=call.id, content=content)


def _durable_execution_state(
    local_context: object,
    tool_call_id: str,
) -> tuple[UUID, CommandStepContext] | None:
    if not isinstance(local_context, PlatformRunState):
        return None
    command_context = local_context.step_context
    command_id = local_context.command_ids.get(tool_call_id)
    if command_context is None or command_id is None:
        return None
    return command_id, command_context


def _durable_run_execution_state(
    local_context: object,
    tool_call_id: str,
) -> tuple[UUID, DurableStepContext] | None:
    if not isinstance(local_context, PlatformRunState):
        return None
    command_id = local_context.command_ids.get(tool_call_id)
    if (
        local_context.agent_run_id is None
        or local_context.durable_context is None
        or command_id is None
    ):
        return None
    return command_id, local_context.durable_context


def _agent_run_id_from(local_context: object) -> UUID | None:
    if isinstance(local_context, PlatformRunState):
        return local_context.agent_run_id
    return None


def _live_voice_identity_from(
    local_context: object | None,
    conversation_context: PlatformExecutionContext,
) -> LiveVoiceBufferIdentity | None:
    if not isinstance(local_context, PlatformRunState):
        return None
    identity = local_context.live_voice_identity
    if not isinstance(identity, LiveVoiceBufferIdentity):
        return None
    conversation = conversation_context.conversation
    if (
        identity.organization_id != conversation.organization_id
        or identity.conversation_id != conversation.id
    ):
        return None
    return identity


async def _refresh_tool_availability(
    conversation_context: PlatformExecutionContext,
    local_context: object | None,
) -> None:
    """Re-check mutable tool requirements immediately before dispatch."""
    from eylo.common.contracts.tool_availability import ToolRuntimeFact
    from eylo.pipelines.system_tools.availability import (
        refresh_context_tool_availability,
    )

    runtime_facts: set[ToolRuntimeFact] = set()
    if isinstance(local_context, PlatformRunState):
        if local_context.step_context is not None:
            runtime_facts.add(ToolRuntimeFact.DURABLE_EXECUTION)
        if _agent_run_id_from(local_context) is not None:
            runtime_facts.add(ToolRuntimeFact.AGENT_RUN)
        live_voice_identity = _live_voice_identity_from(
            local_context,
            conversation_context,
        )
        if live_voice_identity is not None and await is_live_voice_session_active(
            live_voice_identity
        ):
            runtime_facts.add(ToolRuntimeFact.ACTIVE_VOICE_SESSION)
    await refresh_context_tool_availability(
        conversation_context,
        runtime_facts=runtime_facts,
    )
