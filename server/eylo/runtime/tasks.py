"""Typed supervision and bounded draining of caller-owned runtime resources."""

import asyncio
import logging
from collections.abc import Callable, Collection, Coroutine, Mapping, Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

type LongRunningTaskFactory = Callable[[], Coroutine[object, object, None]]

QUEUE_DRAIN_TIMEOUT_SECONDS = 1.0


class DrainableQueue(Protocol):
    """Queue teardown waits for acknowledgements without consuming its payload."""

    async def join(self) -> None: ...

    def qsize(self) -> int: ...


def _eval_restart_conditions(
    restart_conditions: Collection[Callable[[], bool]],
) -> bool:
    """Every current owner predicate must permit restart; errors veto it."""
    for condition in restart_conditions:
        try:
            if not condition():
                return False
        except Exception as error:
            logger.error(
                "Restart condition failed error_type=%s",
                type(error).__name__,
            )
            return False
    return True


async def monitor_long_running_tasks(
    task_definitions: Mapping[str, LongRunningTaskFactory],
    active_tasks: dict[str, asyncio.Task[None]],
    *,
    exceptions_to_ignore: Collection[type[BaseException]] = (),
    exceptions_to_restart: Collection[type[BaseException]] = (),
    restart_conditions: Collection[Callable[[], bool]] = (),
) -> None:
    """Replace failed children only under the owner's explicit restart policy.

    Pending, cancelled, successful and ignored tasks retain their identities.
    Ignored errors take precedence over restartable errors. Factories bind their
    own arguments; a replacement is stored in the owner's original registry.
    The caller owns polling frequency and final teardown, not this inspection.
    """
    for name, task in list(active_tasks.items()):
        if not task.done():
            continue
        if task.cancelled():
            logger.debug("Task '%s' was cancelled", name)
            continue

        error = task.exception()
        if error is None:
            logger.warning("Task '%s' ended unexpectedly by returning normally", name)
            continue
        if isinstance(error, tuple(exceptions_to_ignore)):
            logger.debug(
                "Task '%s' stopped with ignored error_type=%s",
                name,
                type(error).__name__,
            )
            continue
        if not isinstance(error, tuple(exceptions_to_restart)):
            continue

        factory = task_definitions.get(name)
        if factory is None or not _eval_restart_conditions(restart_conditions):
            continue
        logger.info(
            "Restarting task '%s' after error_type=%s", name, type(error).__name__
        )
        active_tasks[name] = asyncio.create_task(factory())


async def teardown_long_running_tasks[K: str, T](
    active_tasks: Mapping[K, asyncio.Task[T]],
) -> None:
    """Cancel owned children together and collect failures, including done tasks.

    Never cancel/await the calling task or mutate the caller's registry. Caller
    cancellation still propagates; each child remains responsible for closing
    its resources in its own cancellation handler.
    """
    current_task = asyncio.current_task()
    owned_tasks = {
        name: task for name, task in active_tasks.items() if task is not current_task
    }
    for task in owned_tasks.values():
        if not task.done():
            task.cancel()
    try:
        await asyncio.gather(*owned_tasks.values(), return_exceptions=True)
    finally:
        for name, task in owned_tasks.items():
            if not task.done() or task.cancelled():
                continue
            error = task.exception()
            if error is not None:
                logger.error(
                    "Task stopped during teardown task=%s error_type=%s",
                    name,
                    type(error).__name__,
                )


async def teardown_queues(
    queues: Sequence[DrainableQueue],
    join_timeout: float = QUEUE_DRAIN_TIMEOUT_SECONDS,
) -> None:
    """Bound each queue's acknowledgement wait; never dequeue unhandled work."""
    for queue in queues:
        await _teardown_queue(queue, join_timeout)


async def _teardown_queue(
    queue: DrainableQueue,
    join_timeout: float = QUEUE_DRAIN_TIMEOUT_SECONDS,
) -> None:
    try:
        await asyncio.wait_for(queue.join(), timeout=join_timeout)
    except asyncio.TimeoutError:
        logger.warning(
            "Timeout waiting for request queue to drain. "
            f"{queue.qsize()} items might be unprocessed."
        )
    except Exception as error:
        logger.error(
            "Queue drain failed error_type=%s",
            type(error).__name__,
        )
