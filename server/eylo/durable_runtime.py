"""One explicit Absurd runtime shared by every durable platform workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast
from uuid import UUID

from absurd_sdk import (
    AbsurdHooks,
    AsyncAbsurd,
    AsyncTaskContext,
    CancellationPolicy,
    RetryStrategy,
)
from sqlalchemy.engine import make_url

from eylo.common.config import settings

DURABLE_QUEUE = "eylo-agent-runs-v1"
DURABLE_MAX_ATTEMPTS = 3
DURABLE_RETRY_STRATEGY: RetryStrategy = {
    "kind": "exponential",
    "base_seconds": 1.0,
    "factor": 2.0,
    "max_seconds": 30.0,
}
# Explicit JSON nulls disable both automatic limits. Product state owns waits
# and cancellation policy; the engine must not invent a wall-clock deadline.
DURABLE_CANCELLATION_POLICY = cast(
    CancellationPolicy,
    {"max_duration": None, "max_delay": None},
)
DURABLE_CLAIM_TIMEOUT_SECONDS = 120
DURABLE_HEARTBEAT_INTERVAL_SECONDS = 30
DURABLE_WORKER_CONCURRENCY = 4
DURABLE_POLL_INTERVAL_SECONDS = 0.25

DurableTaskHandler = Callable[
    [dict[str, Any], AsyncTaskContext],
    Awaitable[dict[str, Any]],
]
T = TypeVar("T")
_HANDLER_HEARTBEAT_ACTIVE: ContextVar[bool] = ContextVar(
    "eylo_durable_handler_heartbeat_active",
    default=False,
)


class DurableRuntimeConfigurationError(Exception):
    """Required PostgreSQL/Absurd wiring is absent or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class AbsurdRuntimeConfig:
    """Every engine and worker option; concurrency means independent pollers."""

    database_url: str = field(repr=False)
    queue_name: str = DURABLE_QUEUE
    max_attempts: int = DURABLE_MAX_ATTEMPTS
    claim_timeout_seconds: int = DURABLE_CLAIM_TIMEOUT_SECONDS
    worker_concurrency: int = DURABLE_WORKER_CONCURRENCY
    poll_interval_seconds: float = DURABLE_POLL_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        try:
            url = make_url(self.database_url)
        except Exception as error:
            raise DurableRuntimeConfigurationError(
                "Durable execution database URL is invalid."
            ) from error
        if url.get_backend_name() != "postgresql":
            raise DurableRuntimeConfigurationError(
                "Durable execution requires PostgreSQL."
            )
        if self.queue_name != DURABLE_QUEUE:
            raise DurableRuntimeConfigurationError(
                f"Durable execution queue must be {DURABLE_QUEUE}."
            )
        numeric_options = (
            self.max_attempts,
            self.claim_timeout_seconds,
            self.worker_concurrency,
            self.poll_interval_seconds,
        )
        if any(value <= 0 for value in numeric_options):
            raise DurableRuntimeConfigurationError(
                "Durable worker options must be positive."
            )

    @classmethod
    def from_platform_settings(cls) -> AbsurdRuntimeConfig:
        """Use Eylo's required PostgreSQL DB with Absurd's sync driver URL."""
        try:
            platform_url = make_url(settings.DATABASE_URL)
            absurd_url = platform_url.set(drivername="postgresql").render_as_string(
                hide_password=False
            )
        except Exception as error:
            raise DurableRuntimeConfigurationError(
                "Durable execution database wiring is unavailable."
            ) from error
        return cls(database_url=absurd_url)

    def retry_strategy(self) -> RetryStrategy:
        return dict(DURABLE_RETRY_STRATEGY)  # type: ignore[return-value]

    def cancellation_policy(self) -> CancellationPolicy:
        return dict(DURABLE_CANCELLATION_POLICY)  # type: ignore[return-value]


class PlatformDurableRuntime:
    """Own one producer client plus isolated polling lanes for durable work."""

    def __init__(self, config: AbsurdRuntimeConfig | None = None) -> None:
        self.config = config or AbsurdRuntimeConfig.from_platform_settings()
        self._app = self._new_app()
        self._worker_apps: tuple[AsyncAbsurd, ...] = ()
        self._registrations: dict[str, DurableTaskRegistration] = {}
        self._registered_names: set[str] = set()

    def _new_app(self) -> AsyncAbsurd:
        return AsyncAbsurd(
            self.config.database_url,
            queue_name=self.config.queue_name,
            default_max_attempts=self.config.max_attempts,
            hooks=cast(
                AbsurdHooks,
                {"wrap_task_execution": self._execute_with_claim_heartbeat},
            ),
        )

    async def _execute_with_claim_heartbeat(
        self,
        context: AsyncTaskContext,
        execute: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Renew the claim for the full handler, including code between steps."""
        interval_seconds = max(
            1,
            min(
                DURABLE_HEARTBEAT_INTERVAL_SECONDS,
                self.config.claim_timeout_seconds // 3,
            ),
        )
        token = _HANDLER_HEARTBEAT_ACTIVE.set(True)
        try:
            return await _run_with_durable_heartbeat(
                context,
                execute,
                heartbeat_seconds=self.config.claim_timeout_seconds,
                interval_seconds=interval_seconds,
            )
        finally:
            _HANDLER_HEARTBEAT_ACTIVE.reset(token)

    def register_task(
        self,
        *,
        name: str,
        handler: DurableTaskHandler,
        max_attempts: int | None = None,
        cancellation: CancellationPolicy | None = None,
    ) -> None:
        """Register one named workflow once on this shared runtime."""
        name = name.strip()
        if not name:
            raise DurableRuntimeConfigurationError(
                "Durable workflow name must be explicit."
            )
        if name in self._registered_names:
            raise DurableRuntimeConfigurationError(
                f"Durable workflow {name} is already registered."
            )
        attempts = max_attempts or self.config.max_attempts
        if attempts < 1:
            raise DurableRuntimeConfigurationError(
                "Durable workflow attempts must be positive."
            )
        registration = DurableTaskRegistration(
            name=name,
            handler=handler,
            max_attempts=attempts,
            cancellation=cast(
                CancellationPolicy,
                dict(cancellation or self.config.cancellation_policy()),
            ),
        )
        self._register_on(self._app, registration)
        self._registrations[name] = registration
        self._registered_names.add(name)

    def _register_on(
        self,
        app: AsyncAbsurd,
        registration: DurableTaskRegistration,
    ) -> None:
        decorator = app.register_task(
            registration.name,
            queue=self.config.queue_name,
            default_max_attempts=registration.max_attempts,
            default_cancellation=cast(
                CancellationPolicy,
                dict(registration.cancellation),
            ),
        )
        decorator(registration.handler)

    def is_registered(self, name: str) -> bool:
        return name in self._registered_names

    async def spawn_task(
        self,
        *,
        name: str,
        params: dict[str, Any],
        idempotency_key: str,
        max_attempts: int | None = None,
    ) -> UUID:
        """Spawn one IDs-only product workflow under explicit retry policy."""
        if not name.strip() or not idempotency_key.strip():
            raise DurableRuntimeConfigurationError(
                "Durable workflow name and idempotency key must be explicit."
            )
        spawn = await self._app.spawn(
            name,
            params,
            max_attempts=max_attempts or self.config.max_attempts,
            retry_strategy=self.config.retry_strategy(),
            headers={},
            queue=self.config.queue_name,
            cancellation=self.config.cancellation_policy(),
            idempotency_key=idempotency_key,
        )
        try:
            return UUID(str(spawn["task_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise DurableRuntimeConfigurationError(
                "Absurd returned an invalid task identifier."
            ) from error

    async def cancel_task(self, task_id: UUID) -> None:
        await self._app.cancel_task(
            str(task_id),
            queue_name=self.config.queue_name,
        )

    async def task_state(self, task_id: UUID) -> str | None:
        snapshot = await self._app.fetch_task_result(
            str(task_id),
            queue_name=self.config.queue_name,
        )
        return None if snapshot is None else snapshot.state

    async def emit_event(self, *, event_name: str, payload: dict) -> None:
        await self._app.emit_event(
            event_name,
            payload,
            queue_name=self.config.queue_name,
        )

    async def start_worker(self, *, worker_id: str) -> None:
        if not worker_id.strip():
            raise DurableRuntimeConfigurationError(
                "Durable worker ID must be explicit."
            )
        if not self._registered_names:
            raise DurableRuntimeConfigurationError(
                "At least one durable workflow must be registered before worker start."
            )
        if self._worker_apps:
            raise DurableRuntimeConfigurationError("Durable worker is already running.")

        # The Python SDK waits for its entire claimed batch before polling again,
        # so one late-arriving task cannot fill an advertised free slot. Give each
        # configured lane its own public client and connection until upstream
        # refills capacity continuously.
        # Source: https://github.com/earendil-works/absurd/blob/0.5.0/sdks/python/src/absurd_sdk/__init__.py
        lanes = tuple(self._new_app() for _ in range(self.config.worker_concurrency))
        self._worker_apps = lanes
        try:
            for app in lanes:
                for registration in self._registrations.values():
                    self._register_on(app, registration)
            async with asyncio.TaskGroup() as tasks:
                for index, app in enumerate(lanes, start=1):
                    tasks.create_task(
                        app.start_worker(
                            worker_id=f"{worker_id}:lane-{index}",
                            claim_timeout=self.config.claim_timeout_seconds,
                            concurrency=1,
                            batch_size=1,
                            poll_interval=self.config.poll_interval_seconds,
                        )
                    )
        finally:
            for app in lanes:
                await app.close()
            self._worker_apps = ()

    def stop_worker(self) -> None:
        for app in self._worker_apps:
            app.stop_worker()
        self._app.stop_worker()

    async def close(self) -> None:
        for app in self._worker_apps:
            await app.close()
        self._worker_apps = ()
        await self._app.close()


@dataclass(frozen=True, slots=True)
class DurableTaskRegistration:
    """Replayable public-SDK task registration for each worker lane."""

    name: str
    handler: DurableTaskHandler
    max_attempts: int
    cancellation: CancellationPolicy


async def run_with_durable_heartbeat(
    context: AsyncTaskContext,
    operation: Callable[[], Awaitable[T]],
    *,
    heartbeat_seconds: int = DURABLE_CLAIM_TIMEOUT_SECONDS,
    interval_seconds: int = 30,
) -> T:
    """Renew standalone work or validate the outer claim at operation boundaries."""
    if _HANDLER_HEARTBEAT_ACTIVE.get():
        await context.heartbeat(seconds=heartbeat_seconds)
        result = await operation()
        await context.heartbeat(seconds=heartbeat_seconds)
        return result
    return await _run_with_durable_heartbeat(
        context,
        operation,
        heartbeat_seconds=heartbeat_seconds,
        interval_seconds=interval_seconds,
    )


async def _run_with_durable_heartbeat(
    context: AsyncTaskContext,
    operation: Callable[[], Awaitable[T]],
    *,
    heartbeat_seconds: int,
    interval_seconds: int,
) -> T:
    """Own one heartbeat loop and cancel work immediately after claim loss."""
    if heartbeat_seconds < 1 or interval_seconds < 1:
        raise ValueError("Durable heartbeat values must be positive.")
    task = asyncio.ensure_future(operation())
    try:
        while not task.done():
            await context.heartbeat(seconds=heartbeat_seconds)
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=interval_seconds,
                )
            except TimeoutError:
                continue
        result = await task
        # A blocked event loop can let the claim expire at the same moment the
        # handler finishes. Validate ownership once more before Absurd records
        # completion; otherwise a stale worker can complete a reclaimed run.
        await context.heartbeat(seconds=heartbeat_seconds)
        return result
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


__all__ = [
    "AbsurdRuntimeConfig",
    "DURABLE_CANCELLATION_POLICY",
    "DURABLE_HEARTBEAT_INTERVAL_SECONDS",
    "DURABLE_MAX_ATTEMPTS",
    "DURABLE_QUEUE",
    "DURABLE_RETRY_STRATEGY",
    "DurableRuntimeConfigurationError",
    "DurableTaskHandler",
    "PlatformDurableRuntime",
    "run_with_durable_heartbeat",
]
