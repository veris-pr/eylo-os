"""Compose provider, agent-binding, and execution facts for system tools."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.tool_availability import (
    ToolAvailabilityFacts,
    ToolRuntimeFact,
    missing_tool_requirements,
)
from eylo.common.database import current_transaction, start_transaction
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.provider_configs.capabilities import ready_capabilities
from eylo.modules.tools.models import ToolKind
from eylo.modules.tools.services.tool_register import system_tools_registry
from eylo.pipelines.system_tools.agent_capabilities import (
    resolve_agent_tool_capabilities,
)
from eylo.pipelines.telephony.sessions import S_CALLS

if TYPE_CHECKING:
    from eylo.modules.tools.schemas.indb import ToolInDb


class ToolAvailabilityScope(Protocol):
    """A conversation or detached execution scope; identity is read-only here."""

    @property
    def id(self) -> UUID: ...

    @property
    def organization_id(self) -> UUID: ...


class ToolAvailabilityContext(Protocol):
    """Minimum mutable context required to resolve system-tool availability."""

    @property
    def conversation(self) -> ToolAvailabilityScope: ...

    @property
    def primary_agent(self) -> AgentInDb | None: ...

    @property
    def widget_interfaces_enabled(self) -> bool: ...

    tool_availability: ToolAvailabilityFacts


async def refresh_context_tool_availability(
    context: ToolAvailabilityContext,
    *,
    session: AsyncSession | None = None,
    runtime_facts: Iterable[ToolRuntimeFact] = (),
) -> ToolAvailabilityFacts:
    """Publish fresh facts from an explicit, active, or owned DB-only scope.

    Never commit or close a borrowed session. Without one, release the owned
    read transaction before returning to the tool/model execution path.
    """
    db = session if session is not None else current_transaction()
    if db is None:
        async with start_transaction(ro=True) as db:
            facts = await _load_tool_availability(context, db, runtime_facts)
    else:
        facts = await _load_tool_availability(context, db, runtime_facts)
    context.tool_availability = facts
    return facts


async def _load_tool_availability(
    context: ToolAvailabilityContext,
    db: AsyncSession,
    runtime_facts: Iterable[ToolRuntimeFact],
) -> ToolAvailabilityFacts:
    organization_id = context.conversation.organization_id
    agent = context.primary_agent
    agent_capabilities = (
        frozenset()
        if agent is None
        else await resolve_agent_tool_capabilities(db, agent)
    )
    resolved_runtime = set(runtime_facts)
    if context.widget_interfaces_enabled:
        resolved_runtime.add(ToolRuntimeFact.WIDGET)
    if _has_active_call(context):
        resolved_runtime.update(
            {
                ToolRuntimeFact.ACTIVE_CALL,
                ToolRuntimeFact.ACTIVE_VOICE_SESSION,
            }
        )

    return ToolAvailabilityFacts(
        organization_capabilities=await ready_capabilities(db, organization_id),
        agent_capabilities=agent_capabilities,
        runtime_facts=frozenset(resolved_runtime),
    )


def filter_available_system_tools(
    tools: Iterable[ToolInDb],
    facts: ToolAvailabilityFacts,
) -> list[ToolInDb]:
    """Filter system tools against the current execution facts."""
    visible: list[ToolInDb] = []
    for tool in tools:
        if tool.kind is not ToolKind.SYSTEM:
            visible.append(tool)
            continue
        try:
            missing = missing_tool_requirements(
                system_tools_registry.requirements_for(tool.slug),
                facts,
            )
        except ValueError:
            continue
        if missing.available:
            visible.append(tool)
    return visible


def _has_active_call(context: ToolAvailabilityContext) -> bool:
    organization_id = context.conversation.organization_id
    conversation_id = context.conversation.id
    return any(
        session.is_active
        and session.organization_id == organization_id
        and session.conversation_id == conversation_id
        for session in S_CALLS.active_sessions()
    )


__all__ = [
    "ToolAvailabilityContext",
    "filter_available_system_tools",
    "refresh_context_tool_availability",
]
