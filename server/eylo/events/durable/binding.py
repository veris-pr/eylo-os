"""Bind committed event delivery rows to independent Absurd tasks."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from eylo.common.database import start_transaction
from eylo.durable_runtime import PlatformDurableRuntime
from eylo.events.durable.domain import EventDeliveryState
from eylo.events.durable.models import EventDeliveryModel
from eylo.events.durable.service import (
    DurableEventConflict,
    EventDeliveryService,
)

logger = logging.getLogger(__name__)

EVENT_DELIVERY_WORKFLOW = "eylo.events.deliver.v1"
EVENT_DELIVERY_IDEMPOTENCY_PREFIX = "event-delivery:v1"
EVENT_DELIVERY_RECOVERY_LIMIT = 100


class EventDeliverySpawnBatch(BaseModel):
    """Independent spawn outcomes; one failure never hides another."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    task_ids: tuple[UUID, ...]
    failures: tuple[tuple[UUID, str], ...]


class _DeliveryIdentity(BaseModel):
    """Detached delivery ownership, never an ORM row or request session."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    delivery_id: UUID


async def spawn_event_delivery(
    *,
    organization_id: UUID,
    delivery_id: UUID,
) -> UUID:
    """Idempotently spawn and bind one already-committed delivery."""
    runtime = PlatformDurableRuntime()
    try:
        return await _spawn_with_runtime(
            runtime,
            organization_id=organization_id,
            delivery_id=delivery_id,
        )
    finally:
        await runtime.close()


async def spawn_event_deliveries(
    *,
    organization_id: UUID,
    event_id: UUID,
) -> EventDeliverySpawnBatch:
    """Spawn all explicit consumers concurrently after the source commit."""
    async with start_transaction(ro=True) as session:
        delivery_ids = tuple(
            (
                await session.scalars(
                    select(EventDeliveryModel.id)
                    .where(
                        EventDeliveryModel.event_id == event_id,
                        EventDeliveryModel.organization_id == organization_id,
                    )
                    .order_by(EventDeliveryModel.consumer_name.asc())
                )
            ).all()
        )
    return await _spawn_batch(
        tuple(
            _DeliveryIdentity(organization_id=organization_id, delivery_id=delivery_id)
            for delivery_id in delivery_ids
        )
    )


async def spawn_unbound_event_deliveries(
    *,
    limit: int = EVENT_DELIVERY_RECOVERY_LIMIT,
) -> EventDeliverySpawnBatch:
    """Recover commit-before-spawn gaps without adding another claim protocol."""
    if limit < 1:
        raise ValueError("Event delivery recovery limit must be positive.")
    async with start_transaction(ro=True) as session:
        rows = tuple(
            _DeliveryIdentity(organization_id=organization_id, delivery_id=delivery_id)
            for organization_id, delivery_id in (
                await session.execute(
                    select(
                        EventDeliveryModel.organization_id,
                        EventDeliveryModel.id,
                    )
                    .where(
                        EventDeliveryModel.state == EventDeliveryState.PENDING,
                        EventDeliveryModel.absurd_task_id.is_(None),
                    )
                    .order_by(EventDeliveryModel.created_at.asc())
                    .limit(limit)
                )
            ).all()
        )
    result = await _spawn_batch(rows)
    for delivery_id, summary in result.failures:
        logger.error(
            "Could not spawn durable event delivery %s: %s",
            delivery_id,
            summary,
        )
    return result


async def _spawn_batch(
    rows: tuple[_DeliveryIdentity, ...],
) -> EventDeliverySpawnBatch:
    if not rows:
        return EventDeliverySpawnBatch(task_ids=(), failures=())
    runtime = PlatformDurableRuntime()
    try:
        results = await asyncio.gather(
            *(
                _spawn_with_runtime(
                    runtime,
                    organization_id=row.organization_id,
                    delivery_id=row.delivery_id,
                )
                for row in rows
            ),
            return_exceptions=True,
        )
    finally:
        await runtime.close()

    task_ids: list[UUID] = []
    failures: list[tuple[UUID, str]] = []
    for row, result in zip(rows, results, strict=True):
        if isinstance(result, BaseException):
            failures.append((row.delivery_id, str(result) or type(result).__name__))
        else:
            task_ids.append(result)
    return EventDeliverySpawnBatch(
        task_ids=tuple(task_ids),
        failures=tuple(failures),
    )


async def _spawn_with_runtime(
    runtime: PlatformDurableRuntime,
    *,
    organization_id: UUID,
    delivery_id: UUID,
) -> UUID:
    async with start_transaction(ro=True) as session:
        delivery, _ = await EventDeliveryService(session).get(
            organization_id=organization_id,
            delivery_id=delivery_id,
        )
        if delivery.absurd_task_id is not None:
            return delivery.absurd_task_id
        if delivery.state is not EventDeliveryState.PENDING:
            raise DurableEventConflict(
                f"A {delivery.state.value} delivery cannot be spawned."
            )
        max_attempts = delivery.max_attempts

    task_id = await runtime.spawn_task(
        name=EVENT_DELIVERY_WORKFLOW,
        params={
            "organization_id": str(organization_id),
            "delivery_id": str(delivery_id),
        },
        idempotency_key=(
            f"{EVENT_DELIVERY_IDEMPOTENCY_PREFIX}:{organization_id}:{delivery_id}"
        ),
        max_attempts=max_attempts,
    )
    async with start_transaction() as session:
        await EventDeliveryService(session).bind_task(
            organization_id=organization_id,
            delivery_id=delivery_id,
            task_id=task_id,
        )
    return task_id
