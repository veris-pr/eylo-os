"""Content-free command identities for non-conversation AgentRun tools."""

from __future__ import annotations

from uuid import UUID

from eylo.framework.agents.tool import ToolCall
from eylo.pipelines.agent_execution_context import ContextT, PlatformRunState


def bind_agent_run_tool_command(
    local_context: PlatformRunState[ContextT],
    *,
    call: ToolCall,
    command_id: UUID,
) -> None:
    """Bind a call to an already persisted canonical command row."""
    local_context.command_ids[call.id] = command_id


__all__ = [
    "bind_agent_run_tool_command",
]
