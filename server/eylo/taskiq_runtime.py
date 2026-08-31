"""Taskiq broker, task registry, and scheduler for ordinary platform work."""

from __future__ import annotations

import logging

from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisStreamBroker

from eylo.common.config import settings
from eylo.common.database import cleanup_database
from eylo.common.models import register_models
from eylo.listeners.py_events import ListenerProcessRole, setup_listeners
from eylo.periodic_work import (
    ORDINARY_TASK_LOCK_TIMEOUT_SECONDS,
    PERIODIC_ACTIONS,
    run_periodic_action,
)
from eylo.pipelines.composition import register_pipeline_extensions

logger = logging.getLogger(__name__)

ORDINARY_TASK_QUEUE = "eylo-ordinary-tasks-v1"
ORDINARY_TASK_CONSUMER_GROUP = "eylo-ordinary-workers-v1"
ORDINARY_PERIODIC_TASK = "eylo.periodic.action.v1"
ORDINARY_TASK_STREAM_MAX_LENGTH = 250_000
ORDINARY_TASK_REDELIVERY_TIMEOUT_MS = (
    ORDINARY_TASK_LOCK_TIMEOUT_SECONDS + 2 * 60
) * 1000

broker = RedisStreamBroker(
    url=settings.REDIS_URL,
    queue_name=ORDINARY_TASK_QUEUE,
    consumer_group_name=ORDINARY_TASK_CONSUMER_GROUP,
    consumer_id="0",
    max_connection_pool_size=20,
    maxlen=ORDINARY_TASK_STREAM_MAX_LENGTH,
    idle_timeout=ORDINARY_TASK_REDELIVERY_TIMEOUT_MS,
    xread_count=4,
    unacknowledged_batch_size=4,
    unacknowledged_lock_timeout=30,
    protocol=2,
)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def initialize_worker(_state: TaskiqState) -> None:
    """Initialize the same model, pipeline, and listener graph as other workers."""
    register_models()
    register_pipeline_extensions()
    setup_listeners(process_role=ListenerProcessRole.WORKER)
    logger.info(
        "Taskiq worker registered ordinary_tasks=%s queue=%s",
        len(PERIODIC_ACTIONS),
        ORDINARY_TASK_QUEUE,
    )


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def close_worker(_state: TaskiqState) -> None:
    """Release process-owned DB pools after Taskiq stops accepting work."""
    await cleanup_database()


@broker.task(
    task_name=ORDINARY_PERIODIC_TASK,
    schedule=[
        {"cron": action.cron, "args": [action.name]}
        for action in PERIODIC_ACTIONS
    ],
)
async def execute_periodic_action(action_name: str) -> None:
    """Execute one independently queued periodic action by catalog name."""
    await run_periodic_action(action_name)


__all__ = [
    "ORDINARY_PERIODIC_TASK",
    "ORDINARY_TASK_CONSUMER_GROUP",
    "ORDINARY_TASK_QUEUE",
    "broker",
    "execute_periodic_action",
    "scheduler",
]
