"""Delete one SOR source after fencing and stopping its durable work."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from eylo.common.database import start_transaction
from eylo.sor.runtime.commands import cancel_sor_command
from eylo.sor.runtime.sync import cancel_sor_sync_run
from eylo.sor.runtime.webhooks import cancel_sor_webhook_receipt
from eylo.sor.shared.deletion import (
    SorSourceDeletionPlan,
    SorSourceDeletionService,
)

logger = logging.getLogger(__name__)


async def delete_sor_source(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> None:
    """Fence, stop, then purge one source without touching its vendor account."""
    async with start_transaction() as session:
        plan = await SorSourceDeletionService(session).fence(
            organization_id=organization_id,
            source_id=source_id,
        )

    await _stop_source_work(plan)

    async with start_transaction() as session:
        await SorSourceDeletionService(session).purge(
            organization_id=organization_id,
            source_id=source_id,
        )


async def _stop_source_work(plan: SorSourceDeletionPlan) -> None:
    """Best-effort stop work after the committed source authority fence."""
    await _stop_each(
        plan.command_ids,
        kind="command",
        stop=lambda command_id: cancel_sor_command(
            organization_id=plan.organization_id,
            command_id=command_id,
        ),
    )
    await _stop_each(
        plan.webhook_receipt_ids,
        kind="webhook receipt",
        stop=lambda receipt_id: cancel_sor_webhook_receipt(
            organization_id=plan.organization_id,
            receipt_id=receipt_id,
            error_code="SOURCE_DELETED",
            error_summary="SOR webhook processing stopped because the source was deleted.",
        ),
    )
    await _stop_each(
        plan.sync_run_ids,
        kind="sync run",
        stop=lambda run_id: cancel_sor_sync_run(
            organization_id=plan.organization_id,
            run_id=run_id,
        ),
    )


async def _stop_each(
    work_ids: Sequence[UUID],
    *,
    kind: str,
    stop: Callable[[UUID], Awaitable[bool]],
) -> None:
    for work_id in work_ids:
        try:
            await stop(work_id)
        except Exception as error:  # noqa: BLE001 - the source fence is authority
            logger.error(
                "Could not stop SOR %s before source purge work_id=%s "
                "error_type=%s",
                kind,
                work_id,
                type(error).__name__,
            )


__all__ = ["delete_sor_source"]
