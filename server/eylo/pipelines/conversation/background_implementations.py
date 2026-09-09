"""Execute first-party background implementations with explicit agent authority."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Final, TypeAlias

from eylo.common.contracts.background_task import BackgroundTaskOutcome
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.conversations import ConversationContext

logger = logging.getLogger(__name__)

BackgroundImplementation: TypeAlias = Callable[
    [ConversationContext, AgentInDb], Awaitable[BackgroundTaskOutcome]
]
_TITLE_LOCK_NAME: Final = "title_gen"
_SUMMARY_LOCK_NAME: Final = "ctx_mgmt"


async def _locked(
    context: ConversationContext,
    lock_name: str,
    worker: BackgroundImplementation,
    agent: AgentInDb,
) -> BackgroundTaskOutcome:
    """A concurrent owner means skipped work; other failures propagate."""
    from eylo.pipelines.llm.background_agents.redis_lock.conversation_lock import (
        LockNotAcquired,
        lock_conversation,
    )

    try:
        async with lock_conversation(context.conversation.id, lock_name):
            return await worker(context, agent)
    except LockNotAcquired:
        logger.debug(
            "%s already running for conversation %s",
            lock_name,
            context.conversation.id,
        )
        return BackgroundTaskOutcome.SKIPPED


async def _run_title_generator(
    context: ConversationContext,
    agent: AgentInDb,
) -> BackgroundTaskOutcome:
    from eylo.pipelines.llm.background_agents.title_generator.agent import (
        process_title_generation_request,
    )

    return await _locked(
        context, _TITLE_LOCK_NAME, process_title_generation_request, agent
    )


async def _run_summary_generator(
    context: ConversationContext,
    agent: AgentInDb,
) -> BackgroundTaskOutcome:
    from eylo.pipelines.llm.background_agents.summary_generator.agent import (
        process_context_management_request,
    )

    return await _locked(
        context, _SUMMARY_LOCK_NAME, process_context_management_request, agent
    )


IMPLEMENTATION_RUNNERS: Final[dict[str, BackgroundImplementation]] = {
    "title_generator": _run_title_generator,
    "summary_generator": _run_summary_generator,
}


async def run_implementation(
    *,
    agent: AgentInDb,
    context: ConversationContext,
) -> BackgroundTaskOutcome:
    """Use the dispatched agent's implementation and config, not the conversation's."""
    slug = agent.implementation
    runner = None if slug is None else IMPLEMENTATION_RUNNERS.get(slug)
    if runner is None:
        raise ValueError(f"No runtime registered for implementation {slug!r}.")
    return await runner(context, agent)
