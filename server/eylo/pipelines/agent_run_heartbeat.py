"""Own active-time checks and child cleanup during one durable agent operation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from eylo.modules.agent_runs.workflow import AgentRunWorkflowContext

_CLAIM_EXTENSION_SECONDS = 120
_CHECK_INTERVAL_SECONDS = 30.0
_MINIMUM_WAIT_SECONDS = 0.001
_MILLISECONDS_PER_SECOND = 1_000


async def run_with_agent_heartbeat(
    context: AgentRunWorkflowContext,
    operation: Callable[[], Awaitable[None]],
) -> None:
    """Renew the claim and enforce active-time limits until the operation settles.

    Own the returned awaitable, including cancellation and exception retrieval.
    The runtime's outer claim heartbeat does not replace the agent budget check.
    A heartbeat failure remains authoritative even if child cleanup also fails.
    """
    operation_task = asyncio.ensure_future(operation())
    try:
        while not operation_task.done():
            remaining_milliseconds = await context.heartbeat(
                seconds=_CLAIM_EXTENSION_SECONDS
            )
            await asyncio.wait(
                (operation_task,),
                timeout=min(
                    _CHECK_INTERVAL_SECONDS,
                    max(
                        _MINIMUM_WAIT_SECONDS,
                        remaining_milliseconds / _MILLISECONDS_PER_SECOND,
                    ),
                ),
            )
        await operation_task
    finally:
        if not operation_task.done():
            operation_task.cancel()
        await asyncio.gather(operation_task, return_exceptions=True)
