"""Ordinary periodic action catalog plus the retired Absurd tick handler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal

from absurd_sdk import AsyncTaskContext
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from pydantic.json_schema import SkipJsonSchema
from redis.exceptions import LockNotOwnedError

from eylo.common.redis import get_redis_client
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
ORDINARY_TASK_MAX_RUNTIME_SECONDS = 8 * 60
ORDINARY_TASK_LOCK_TIMEOUT_SECONDS = 10 * 60

PeriodicCallable = Callable[[], Awaitable[object]]


class PeriodicActionName(StrEnum):
    """Stable task payload names; changing a value would strand queued work."""

    DISPATCH_DUE_SCHEDULES = "dispatch-due-schedules"
    RECOVER_STRANDED_SCHEDULES = "recover-stranded-schedules"
    RECONCILE_TERMINAL_AGENT_RUNS = "reconcile-terminal-agent-runs"
    RECOVER_CONVERSATION_RUNS = "recover-conversation-runs"
    RECOVER_PARALLEL_RUNS = "recover-parallel-runs"
    RECOVER_OBJECTIVE_RUNS = "recover-objective-runs"
    NUDGE_EVENT_DELIVERIES = "nudge-event-deliveries"
    NUDGE_KNOWLEDGE_WORK = "nudge-knowledge-work"
    NUDGE_RECORDING_UPLOADS = "nudge-recording-uploads"
    PROCESS_CAMPAIGN_CALLS = "process-campaign-calls"
    NUDGE_MEMORY_REINDEXES = "nudge-memory-reindexes"
    NUDGE_MEMORY_RECONCILIATIONS = "nudge-memory-reconciliations"
    NUDGE_MEMORY_FORMATIONS = "nudge-memory-formations"
    NUDGE_DELETIONS = "nudge-deletions"
    DISPATCH_DUE_SOR_SYNCS = "dispatch-due-sor-syncs"
    NUDGE_SOR_WORK = "nudge-sor-work"
    REAP_SANDBOX_RESOURCES = "reap-sandbox-resources"
    REFRESH_EXPIRING_CURATED_TOKENS = "refresh-expiring-curated-tokens"
    EXPIRE_OLD_CONVERSATIONS = "expire-old-conversations"
    CLEANUP_OAUTH_STATES = "cleanup-oauth-states"
    CLEANUP_INVALIDATED_CONNECTIONS = "cleanup-invalidated-connections"


class PeriodicCadence(StrEnum):
    EVERY_MINUTE = "* * * * *"
    EVERY_FIVE_MINUTES = "*/5 * * * *"
    HOURLY = "0 * * * *"
    DAILY = "0 0 * * *"


class PeriodicAction(BaseModel):
    """One independently scheduled task; never serialize its live callable."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    name: PeriodicActionName
    cron: PeriodicCadence
    run: SkipJsonSchema[PeriodicCallable] = Field(repr=False, exclude=True)


PERIODIC_ACTIONS = (
    PeriodicAction(
        name=PeriodicActionName.DISPATCH_DUE_SCHEDULES,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=dispatch_due_schedules,
    ),
    PeriodicAction(
        name=PeriodicActionName.RECOVER_STRANDED_SCHEDULES,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=recover_stranded_schedules,
    ),
    PeriodicAction(
        name=PeriodicActionName.RECONCILE_TERMINAL_AGENT_RUNS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=reconcile_terminal_agent_runs,
    ),
    PeriodicAction(
        name=PeriodicActionName.RECOVER_CONVERSATION_RUNS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=recover_unbound_conversation_agent_runs,
    ),
    PeriodicAction(
        name=PeriodicActionName.RECOVER_PARALLEL_RUNS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=recover_unbound_parallel_agent_runs,
    ),
    PeriodicAction(
        name=PeriodicActionName.RECOVER_OBJECTIVE_RUNS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=recover_unbound_objective_agent_runs,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_EVENT_DELIVERIES,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=spawn_unbound_event_deliveries,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_KNOWLEDGE_WORK,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_unbound_knowledge_work,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_RECORDING_UPLOADS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_unbound_recording_uploads,
    ),
    PeriodicAction(
        name=PeriodicActionName.PROCESS_CAMPAIGN_CALLS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=process_campaign_calls,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_MEMORY_REINDEXES,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_unbound_memory_reindexes,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_MEMORY_RECONCILIATIONS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_unbound_memory_reconciliations,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_MEMORY_FORMATIONS,
        cron=PeriodicCadence.EVERY_FIVE_MINUTES,
        run=nudge_unbound_memory_formations,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_DELETIONS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_unbound_deletions,
    ),
    PeriodicAction(
        name=PeriodicActionName.DISPATCH_DUE_SOR_SYNCS,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=dispatch_due_sor_syncs,
    ),
    PeriodicAction(
        name=PeriodicActionName.NUDGE_SOR_WORK,
        cron=PeriodicCadence.EVERY_MINUTE,
        run=nudge_sor_work,
    ),
    PeriodicAction(
        name=PeriodicActionName.REAP_SANDBOX_RESOURCES,
        cron=PeriodicCadence.EVERY_FIVE_MINUTES,
        run=reap_sandbox_resources,
    ),
    PeriodicAction(
        name=PeriodicActionName.REFRESH_EXPIRING_CURATED_TOKENS,
        cron=PeriodicCadence.EVERY_FIVE_MINUTES,
        run=refresh_expiring_curated_tokens,
    ),
    PeriodicAction(
        name=PeriodicActionName.EXPIRE_OLD_CONVERSATIONS,
        cron=PeriodicCadence.EVERY_FIVE_MINUTES,
        run=expire_old_conversations,
    ),
    PeriodicAction(
        name=PeriodicActionName.CLEANUP_OAUTH_STATES,
        cron=PeriodicCadence.HOURLY,
        run=cleanup_expired_oauth_states,
    ),
    PeriodicAction(
        name=PeriodicActionName.CLEANUP_INVALIDATED_CONNECTIONS,
        cron=PeriodicCadence.DAILY,
        run=cleanup_invalidated_connections,
    ),
)

_ACTIONS_BY_NAME = {action.name: action for action in PERIODIC_ACTIONS}


async def run_periodic_action(action_name: str) -> None:
    """Run one bounded catalog action without overlapping the same action."""
    try:
        action = _ACTIONS_BY_NAME[PeriodicActionName(action_name)]
    except (KeyError, ValueError) as error:
        raise ValueError(f"Unknown periodic action: {action_name}") from error

    async with get_redis_client() as redis_client:
        lock = redis_client.lock(
            f"eylo:ordinary-task-lock:{action.name}",
            timeout=ORDINARY_TASK_LOCK_TIMEOUT_SECONDS,
        )
        if not await lock.acquire(blocking=False):
            logger.info("Periodic action already running action=%s", action.name)
            return
        try:
            async with asyncio.timeout(ORDINARY_TASK_MAX_RUNTIME_SECONDS):
                await action.run()
        except Exception as error:
            logger.exception(
                "Periodic action failed action=%s error_type=%s; later schedules retry",
                action.name,
                type(error).__name__,
            )
            raise
        finally:
            try:
                await lock.release()
            except LockNotOwnedError:
                logger.error(
                    "Periodic action lock expired before release action=%s",
                    action.name,
                )


def register_legacy_periodic_workflow(runtime: PlatformDurableRuntime) -> None:
    """Drain already-persisted Absurd ticks without spawning another tick."""
    runtime.register_task(
        name=LEGACY_PERIODIC_WORKFLOW,
        handler=_retire_legacy_periodic_tick,
    )


class LegacyPeriodicRetirement(BaseModel):
    """Existing compatibility response; finite JSON without rearming a tick."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )

    retired: Literal[True] = True
    scheduled_for: JsonValue = Field(repr=False)
    replacement: Literal["taskiq"] = "taskiq"


async def _retire_legacy_periodic_tick(
    params: dict[str, JsonValue],
    _context: AsyncTaskContext,
) -> dict[str, JsonValue]:
    scheduled_for = params.get("scheduled_for")
    logger.info(
        "Retired persisted Absurd periodic tick scheduled_for=%s; Taskiq owns cron",
        scheduled_for,
    )
    return LegacyPeriodicRetirement(scheduled_for=scheduled_for).model_dump(mode="json")


__all__ = [
    "LEGACY_PERIODIC_WORKFLOW",
    "ORDINARY_TASK_LOCK_TIMEOUT_SECONDS",
    "ORDINARY_TASK_MAX_RUNTIME_SECONDS",
    "PERIODIC_ACTIONS",
    "PeriodicAction",
    "register_legacy_periodic_workflow",
    "run_periodic_action",
]
