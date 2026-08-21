"""Periodic filing and outbox recovery for SOR durable work."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select

from eylo.common.database import start_transaction
from eylo.sor.runtime.commands import spawn_unbound_sor_commands
from eylo.sor.runtime.revocation import recover_fenced_sor_work
from eylo.sor.runtime.sync import (
    spawn_sor_sync_run,
    spawn_unbound_sor_sync_runs,
)
from eylo.sor.runtime.webhooks import spawn_unbound_sor_webhook_receipts
from eylo.sor.shared.contracts import (
    SorChangeStrategy,
    SorSourceState,
    SorStreamState,
    SorSyncRunKind,
    SorWorkState,
)
from eylo.sor.shared.models import (
    SorSourceModel,
    SorSourceStreamModel,
    SorSyncRunModel,
)
from eylo.sor.shared.sync_services import SorSyncRunService
from eylo.sor.shared.webhook_services import SorWebhookService

logger = logging.getLogger(__name__)

_RECONCILIATION_INTERVAL = timedelta(hours=24)
_DUE_LIMIT = 100


async def dispatch_due_sor_syncs() -> dict[str, int]:
    """File due stream work; scheduling never decides Agent intent."""
    now = datetime.now(timezone.utc)
    async with start_transaction(ro=True) as session:
        rows = list(
            (
                await session.execute(
                    select(
                        SorSourceStreamModel.organization_id,
                        SorSourceStreamModel.source_id,
                        SorSourceStreamModel.id,
                        SorSourceStreamModel.strategy,
                    )
                    .join(
                        SorSourceModel,
                        (SorSourceModel.id == SorSourceStreamModel.source_id)
                        & (
                            SorSourceModel.organization_id
                            == SorSourceStreamModel.organization_id
                        ),
                    )
                    .where(
                        SorSourceStreamModel.next_due_at.is_not(None),
                        SorSourceStreamModel.next_due_at <= now,
                        SorSourceStreamModel.state.in_(
                            (SorStreamState.ACTIVE, SorStreamState.DEGRADED)
                        ),
                        SorSourceStreamModel.deleted.is_(False),
                        SorSourceModel.state.in_(
                            (SorSourceState.ACTIVE, SorSourceState.DEGRADED)
                        ),
                        SorSourceModel.deleted.is_(False),
                    )
                    .order_by(
                        SorSourceStreamModel.next_due_at.asc(),
                        SorSourceStreamModel.id.asc(),
                    )
                    .limit(_DUE_LIMIT)
                )
            ).all()
        )

    filed: list[tuple[UUID, UUID]] = []
    for organization_id, source_id, stream_id, strategy in rows:
        try:
            async with start_transaction() as session:
                last_reconciliation = await session.scalar(
                    select(func.max(SorSyncRunModel.finished_at)).where(
                        SorSyncRunModel.organization_id == organization_id,
                        SorSyncRunModel.stream_id == stream_id,
                        SorSyncRunModel.kind == SorSyncRunKind.RECONCILIATION,
                        SorSyncRunModel.state == SorWorkState.SUCCEEDED,
                        SorSyncRunModel.deleted.is_(False),
                    )
                )
                kind = (
                    SorSyncRunKind.RECONCILIATION
                    if strategy is SorChangeStrategy.FULL_RECONCILE
                    or last_reconciliation is None
                    or last_reconciliation <= now - _RECONCILIATION_INTERVAL
                    else SorSyncRunKind.INCREMENTAL
                )
                run, created = await SorSyncRunService(session).create_stream_run(
                    organization_id=organization_id,
                    source_id=source_id,
                    stream_id=stream_id,
                    kind=kind,
                )
                if created:
                    filed.append((organization_id, run.id))
        except Exception as error:  # noqa: BLE001 - streams remain independent
            logger.error(
                "Could not file due SOR stream id=%s error_type=%s",
                stream_id,
                type(error).__name__,
            )

    spawned = 0
    for organization_id, run_id in filed:
        try:
            await spawn_sor_sync_run(
                organization_id=organization_id,
                run_id=run_id,
            )
            spawned += 1
        except Exception as error:  # noqa: BLE001 - outbox recovery retries spawn
            logger.error(
                "SOR due run committed; spawn recovery remains pending "
                "run_id=%s error_type=%s",
                run_id,
                type(error).__name__,
            )
    return {"due": len(rows), "filed": len(filed), "spawned": spawned}


async def nudge_sor_work() -> dict[str, int]:
    """Recover every currently implemented SOR durable outbox."""
    stopped = await recover_fenced_sor_work(limit=100)
    syncs = await spawn_unbound_sor_sync_runs(limit=100)
    webhooks = await spawn_unbound_sor_webhook_receipts(limit=100)
    commands = await spawn_unbound_sor_commands(limit=100)
    async with start_transaction() as session:
        pruned = await SorWebhookService(session).prune_expired_raw_bodies()
    return {
        "cancelled_syncs": stopped.sync_runs,
        "cancelled_webhooks": stopped.webhook_receipts,
        "cancelled_commands": stopped.commands,
        "syncs": syncs,
        "webhooks": webhooks,
        "commands": commands,
        "pruned": pruned,
    }


__all__ = ["dispatch_due_sor_syncs", "nudge_sor_work"]
