"""Ordinary periodic action catalog plus the retired Absurd tick handler."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from absurd_sdk import AsyncTaskContext

from eylo.durable_runtime import PlatformDurableRuntime
from eylo.events.durable.binding import spawn_unbound_event_deliveries
from eylo.jobs.agent_runs import reconcile_terminal_agent_runs
from eylo.jobs.campaign_executor import process_campaign_calls
from eylo.jobs.deletion import nudge_unbound_deletions
from eylo.jobs.knowledge_ingestion import nudge_unbound_knowledge_work
from eylo.jobs.memory_formation import (
    nudge_unbound_memory_formations,
    nudge_unbound_memory_reconciliations,
    nudge_unbound_memory_reindexes,
)
from eylo.jobs.objectives import (
    reap_sandbox_resources,
    recover_unbound_objective_agent_runs,
)
from eylo.jobs.recording_upload import nudge_unbound_recording_uploads
from eylo.jobs.scheduler import dispatch_due_schedules, recover_stranded_schedules
from eylo.jobs.sor import dispatch_due_sor_syncs, nudge_sor_work
from eylo.modules.connections.tasks import (
    cleanup_expired_oauth_states,
    cleanup_invalidated_connections,
)
from eylo.modules.conversations.tasks.agent_runs import (
    recover_unbound_conversation_agent_runs,
)
from eylo.modules.conversations.tasks.conversations import expire_old_conversations
from eylo.modules.parallel_agents.tasks import recover_unbound_parallel_agent_runs
from eylo.pipelines.integrations_v2.tasks import refresh_expiring_curated_tokens

logger = logging.getLogger(__name__)

LEGACY_PERIODIC_WORKFLOW = "eylo.periodic.tick.v1"

PeriodicCallable = Callable[[], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class PeriodicAction:
    """One independently scheduled ordinary task."""

    name: str
    cron: str
    run: PeriodicCallable


PERIODIC_ACTIONS = (
    PeriodicAction("dispatch-due-schedules", "* * * * *", dispatch_due_schedules),
    PeriodicAction(
        "recover-stranded-schedules",
        "* * * * *",
        recover_stranded_schedules,
    ),
    PeriodicAction(
        "reconcile-terminal-agent-runs",
        "* * * * *",
        reconcile_terminal_agent_runs,
    ),
    PeriodicAction(
        "recover-conversation-runs",
        "* * * * *",
        recover_unbound_conversation_agent_runs,
    ),
    PeriodicAction(
        "recover-parallel-runs",
        "* * * * *",
        recover_unbound_parallel_agent_runs,
    ),
    PeriodicAction(
        "recover-objective-runs",
        "* * * * *",
        recover_unbound_objective_agent_runs,
    ),
    PeriodicAction(
        "nudge-event-deliveries",
        "* * * * *",
        spawn_unbound_event_deliveries,
    ),
    PeriodicAction(
        "nudge-knowledge-work",
        "* * * * *",
        nudge_unbound_knowledge_work,
    ),
    PeriodicAction(
        "nudge-recording-uploads",
        "* * * * *",
        nudge_unbound_recording_uploads,
    ),
    PeriodicAction("process-campaign-calls", "* * * * *", process_campaign_calls),
    PeriodicAction(
        "nudge-memory-reindexes",
        "* * * * *",
        nudge_unbound_memory_reindexes,
    ),
    PeriodicAction(
        "nudge-memory-reconciliations",
        "* * * * *",
        nudge_unbound_memory_reconciliations,
    ),
    PeriodicAction(
        "nudge-memory-formations",
        "*/5 * * * *",
        nudge_unbound_memory_formations,
    ),
    PeriodicAction("nudge-deletions", "* * * * *", nudge_unbound_deletions),
    PeriodicAction("dispatch-due-sor-syncs", "* * * * *", dispatch_due_sor_syncs),
    PeriodicAction("nudge-sor-work", "* * * * *", nudge_sor_work),
    PeriodicAction("reap-sandbox-resources", "*/5 * * * *", reap_sandbox_resources),
    PeriodicAction(
        "refresh-expiring-curated-tokens",
        "*/5 * * * *",
        refresh_expiring_curated_tokens,
    ),
    PeriodicAction(
        "expire-old-conversations",
        "*/5 * * * *",
        expire_old_conversations,
    ),
    PeriodicAction("cleanup-oauth-states", "0 * * * *", cleanup_expired_oauth_states),
    PeriodicAction(
        "cleanup-invalidated-connections",
        "0 0 * * *",
        cleanup_invalidated_connections,
    ),
)

_ACTIONS_BY_NAME = {action.name: action for action in PERIODIC_ACTIONS}


async def run_periodic_action(action_name: str) -> None:
    """Run one catalogued action; the next cron dispatch remains independent."""
    try:
        action = _ACTIONS_BY_NAME[action_name]
    except KeyError as error:
        raise ValueError(f"Unknown periodic action: {action_name}") from error
    try:
        await action.run()
    except Exception as error:
        logger.exception(
            "Periodic action failed action=%s error_type=%s; later schedules retry",
            action.name,
            type(error).__name__,
        )
        raise


def register_legacy_periodic_workflow(runtime: PlatformDurableRuntime) -> None:
    """Drain already-persisted Absurd ticks without spawning another tick."""
    runtime.register_task(
        name=LEGACY_PERIODIC_WORKFLOW,
        handler=_retire_legacy_periodic_tick,
    )


async def _retire_legacy_periodic_tick(
    params: dict[str, Any],
    _context: AsyncTaskContext,
) -> dict[str, Any]:
    scheduled_for = params.get("scheduled_for")
    logger.info(
        "Retired persisted Absurd periodic tick scheduled_for=%s; Taskiq owns cron",
        scheduled_for,
    )
    return {
        "retired": True,
        "scheduled_for": scheduled_for,
        "replacement": "taskiq",
    }


__all__ = [
    "LEGACY_PERIODIC_WORKFLOW",
    "PERIODIC_ACTIONS",
    "PeriodicAction",
    "register_legacy_periodic_workflow",
    "run_periodic_action",
]
