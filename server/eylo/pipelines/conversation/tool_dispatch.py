"""Current conversation tool and handoff dispatch.

This module owns the in-process product behavior shared by text, voice,
background, scheduled, and durable agent runs. External provider execution
stays in the capability-specific pipeline modules that call it.
"""

from __future__ import annotations

import logging
from typing import Final

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.llm_response import LLMToolUseBlock
from eylo.common.database import current_transaction, start_transaction
from eylo.common.revisions import DefinitionRef
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.agents.services.tool_execution_utils import (
    AmbiguousModelToolNameError,
    ModelToolNotFoundError,
    ToolApprovalRequiredError,
    ToolExecutionBlockedError,
    ToolExecutionResult,
    ToolExecutorNotFoundError,
    ToolInputValidationError,
    execute_exact_tool,
    resolve_model_tool,
)
from eylo.modules.conversations.constants import HANDOFF_TOOL_PREFIX
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.messages import MessageKind
from eylo.modules.conversations.services.participants import (
    ConversationParticipantService,
)
from eylo.pipelines.agent_execution_context import PlatformExecutionContext
from eylo.pipelines.conversation.handoff import HandoffOutcome, HandoffState
from eylo.pipelines.system_tools.compound_render_widget import (
    compound_widget_text_fallback,
)

logger = logging.getLogger(__name__)

_HANDOFF_HISTORY_MESSAGE_LIMIT: Final = 10
_HANDOFF_TURN_LIMIT: Final = 3


class HandoffInput(BaseModel):
    """Model-supplied continuation text; topology, agents and revisions are trusted context."""

    message: str | None = Field(default=None, strict=True)


async def execute_registered_tool(
    context: PlatformExecutionContext,
    tool_call: LLMToolUseBlock,
) -> ToolExecutionResult:
    """Resolve and execute one exact in-process tool revision."""
    error_map = {
        "tool_not_found": "Error: The requested tool was not found.",
        "tool_execution_failed": "Error: Invalid input provided to the tool.",
    }

    try:
        requested_tool = resolve_model_tool(context.get_tools(), tool_call.name)
    except (ModelToolNotFoundError, AmbiguousModelToolNameError) as error:
        logger.info(
            "Tool resolution rejected conversation=%s agent=%s error_type=%s",
            context.conversation.id,
            context.primary_agent.id if context.primary_agent else None,
            type(error).__name__,
        )
        raise RuntimeError(error_map["tool_not_found"]) from None

    try:
        return await execute_exact_tool(requested_tool, tool_call.input, context)
    except ToolInputValidationError as error:
        logger.warning(
            "Tool input rejected tool=%s@%s code=input_invalid",
            requested_tool.id,
            requested_tool.published_revision,
        )
        if requested_tool.slug == "compound_render_widget":
            return compound_widget_text_fallback("Widget input was invalid.")
        raise RuntimeError(error_map["tool_execution_failed"]) from error
    except ToolExecutorNotFoundError:
        logger.error(
            "Tool dispatch rejected tool=%s@%s code=executor_not_found",
            requested_tool.id,
            requested_tool.published_revision,
        )
        raise RuntimeError(error_map["tool_not_found"]) from None
    except (ToolExecutionBlockedError, ToolApprovalRequiredError) as error:
        logger.info(
            "Tool policy rejected tool=%s@%s error_type=%s",
            requested_tool.id,
            requested_tool.published_revision,
            type(error).__name__,
        )
        raise RuntimeError("Error: Tool execution failed.") from None
    except Exception as error:
        logger.error(
            "Tool execution failed tool=%s@%s error_type=%s",
            requested_tool.id,
            requested_tool.published_revision,
            type(error).__name__,
        )
        raise RuntimeError("Error: Tool execution failed.") from None


async def execute_handoff(
    context: PlatformExecutionContext,
    tool_call: LLMToolUseBlock,
) -> HandoffOutcome:
    """Persist an exact member switch; callers own the full runtime-context rebuild.

    Without a caller session, own a short DB-only transaction. A borrowed session
    is never committed or closed here. Return detached DTOs without partially
    mutating the caller's context, including when a commit fails.
    """
    source_agent = context.primary_agent
    if source_agent is None:
        raise ValueError("Handoff requires a published source agent.")
    if (
        not isinstance(context, ConversationContext)
        or context.conversation.swarm_id is None
        or context.conversation.swarm_revision is None
    ):
        logger.error("Handoff requested without pinned swarm authority.")
        return HandoffOutcome(
            content="Error: This conversation has no swarm topology.",
            source_agent=source_agent,
        )

    swarm_ref = DefinitionRef(
        definition_id=context.conversation.swarm_id,
        revision=context.conversation.swarm_revision,
    )
    session = current_transaction()
    if session is not None:
        return await _execute_pinned_handoff(
            session, context, tool_call, source_agent, swarm_ref
        )
    async with start_transaction() as session:
        return await _execute_pinned_handoff(
            session, context, tool_call, source_agent, swarm_ref
        )


async def _execute_pinned_handoff(
    session: AsyncSession,
    context: ConversationContext,
    tool_call: LLMToolUseBlock,
    source_agent: AgentInDb,
    swarm_ref: DefinitionRef,
) -> HandoffOutcome:
    """Resolve topology and switch the expected primary under one DB scope."""
    from eylo.modules.templates.domain import TemplateConsumerKind
    from eylo.pipelines.agents import build_executable_swarm_resolver

    agent_slug = tool_call.name.removeprefix(HANDOFF_TOOL_PREFIX)
    topology = await build_executable_swarm_resolver(session).resolve_exact(
        organization_id=context.conversation.organization_id,
        swarm_id=swarm_ref.definition_id,
        revision=swarm_ref.revision,
        consumer_kind=TemplateConsumerKind.CONVERSATIONAL_TEXT,
    )
    current_participant = context.get_primary_agent()
    current_member = topology.member_by_agent_id(source_agent.id)
    target_member = topology.member_by_slug(agent_slug)
    if (
        current_participant is None
        or current_participant.agent_id != source_agent.id
        or current_participant.agent_revision is None
        or current_member is None
        or current_member.executable_agent.ref.revision
        != current_participant.agent_revision
        or target_member is None
    ):
        logger.error("Pinned swarm topology rejected the requested handoff.")
        return HandoffOutcome(
            content="Error: Handoff target is not authorized.",
            source_agent=source_agent,
        )

    resolved_agent = target_member.executable_agent
    target_agent = resolved_agent.agent
    if target_agent.id == source_agent.id:
        logger.warning("Handoff requested to the same agent, ignoring.")
        return HandoffOutcome(
            content="Error: Handoff requested to the same agent, ignoring.",
            source_agent=source_agent,
        )

    try:
        requested_input = HandoffInput.model_validate(tool_call.input).message
    except ValidationError:
        return HandoffOutcome(
            content="Error: Handoff message must be text.",
            source_agent=source_agent,
        )
    handoff_tools: list[str] = []
    for message in reversed((context.messages or [])[-_HANDOFF_HISTORY_MESSAGE_LIMIT:]):
        if message.kind == MessageKind.USER:
            break
        if message.kind != MessageKind.TOOL_USE or not message.content:
            continue
        try:
            parsed = message.get_tool_use_content()
        except (ValueError, AttributeError):
            continue
        if parsed.content.name.startswith(HANDOFF_TOOL_PREFIX):
            handoff_tools.append(parsed.content.name)

    circuit_breaker_triggered = len(handoff_tools) >= _HANDOFF_TURN_LIMIT
    handoff_loop_detected = (
        circuit_breaker_triggered and tool_call.name in handoff_tools
    )
    logger.debug(
        "Handoff history checked count=%d loop_detected=%s",
        len(handoff_tools),
        handoff_loop_detected,
    )
    if circuit_breaker_triggered:
        return HandoffOutcome(
            content="Error: Too many recent handoffs detected.",
            source_agent=source_agent,
            requested_input=requested_input,
            state=(
                HandoffState.LOOP_DETECTED
                if handoff_loop_detected
                else HandoffState.LIMIT_REACHED
            ),
        )

    target_participant = await ConversationParticipantService(
        session
    ).switch_primary_agent(
        context.conversation.id,
        source_agent.id,
        current_participant.agent_revision,
        target_agent.id,
        resolved_agent.ref.revision,
    )
    logger.warning(
        "Handoff switched conversation=%s from_agent=%s to_agent=%s",
        context.conversation.id,
        source_agent.id,
        target_agent.id,
    )
    return HandoffOutcome(
        content=(
            "Respond to the user's request and move forward with the appropriate "
            f"next action `{requested_input}`.\n\n"
            f"NOTE: You are now speaking as Assistant:`{target_agent.name}`."
        ),
        source_agent=source_agent,
        requested_input=requested_input,
        target_agent=target_agent,
        target_participant=target_participant,
        state=HandoffState.SUCCEEDED,
    )


__all__ = ["HandoffOutcome", "execute_handoff", "execute_registered_tool"]
