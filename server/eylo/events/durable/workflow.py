"""Absurd workflow for at-least-once unordered event delivery."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from absurd_sdk import AsyncTaskContext
from pydantic import JsonValue

from eylo.common.database import start_transaction
from eylo.durable_runtime import (
    DURABLE_CANCELLATION_POLICY,
    PlatformDurableRuntime,
)
from eylo.events.durable.binding import EVENT_DELIVERY_WORKFLOW
from eylo.events.durable.domain import (
    MAX_DELIVERY_ATTEMPTS,
    EventDeliveryFailureCode,
    EventDeliveryResult,
    EventDeliveryState,
    EventDeliveryTaskParams,
)
from eylo.events.durable.registry import (
    EventConsumerNotRegistered,
    EventConsumerRegistry,
    PermanentEventConsumerError,
)
from eylo.events.durable.service import EventDeliveryService


class EventDeliveryWorkflow:
    """Resolve one exact consumer and atomically commit its receipt."""

    def __init__(self, registry: EventConsumerRegistry) -> None:
        self.registry = registry

    async def execute(
        self,
        params: Mapping[str, object],
        task_context: AsyncTaskContext,
    ) -> dict[str, JsonValue]:
        identity = EventDeliveryTaskParams.from_wire(params)
        organization_id, delivery_id = identity.organization_id, identity.delivery_id
        await task_context.heartbeat(seconds=120)
        async with start_transaction() as session:
            attempt = await EventDeliveryService(session).begin_attempt(
                organization_id=organization_id,
                delivery_id=delivery_id,
            )
        if not attempt.should_consume:
            return _result(attempt.state, attempt.attempts)

        try:
            handler = self.registry.resolve(
                consumer_name=attempt.consumer_name,
                envelope=attempt.envelope,
            )
            async with start_transaction() as session:
                await EventDeliveryService(session).consume(
                    organization_id=organization_id,
                    delivery_id=delivery_id,
                    handler=handler,
                )
        except (EventConsumerNotRegistered, PermanentEventConsumerError) as error:
            state = await _record_failure(
                organization_id=organization_id,
                delivery_id=delivery_id,
                error_code=(
                    EventDeliveryFailureCode.CONSUMER_NOT_REGISTERED
                    if isinstance(error, EventConsumerNotRegistered)
                    else EventDeliveryFailureCode.CONSUMER_REJECTED
                ),
            )
            return _result(state, attempt.attempts)
        except Exception:
            await _record_failure(
                organization_id=organization_id,
                delivery_id=delivery_id,
                error_code=EventDeliveryFailureCode.DELIVERY_FAILED,
            )
            raise
        return _result(EventDeliveryState.SUCCEEDED, attempt.attempts)


def register_event_delivery_workflow(
    runtime: PlatformDurableRuntime,
    registry: EventConsumerRegistry,
) -> None:
    """Register event delivery after every consumer manifest entry is loaded."""
    workflow = EventDeliveryWorkflow(registry)
    runtime.register_task(
        name=EVENT_DELIVERY_WORKFLOW,
        handler=workflow.execute,
        max_attempts=MAX_DELIVERY_ATTEMPTS,
        cancellation=DURABLE_CANCELLATION_POLICY,
    )


async def _record_failure(
    *,
    organization_id: UUID,
    delivery_id: UUID,
    error_code: EventDeliveryFailureCode,
) -> EventDeliveryState:
    async with start_transaction() as session:
        return await EventDeliveryService(session).record_failure(
            organization_id=organization_id,
            delivery_id=delivery_id,
            error_code=error_code,
        )


def _result(state: EventDeliveryState, attempts: int) -> dict[str, JsonValue]:
    return EventDeliveryResult(state=state, attempts=attempts).model_dump(mode="json")
