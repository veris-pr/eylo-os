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
    reconcile_terminal_sor_sync_runs,
    reconcile_unadvanced_sor_sync_generations,
    spawn_sor_sync_run,
    spawn_unbound_sor_sync_runs,
)
from eylo.sor.runtime.webhook_subscriptions import maintain_sor_webhook_subscriptions
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
    SorSyncGenerationModel,
    SorSyncRunModel,
)
from eylo.sor.shared.relationships import SorRelationshipService
from eylo.sor.shared.sync_services import SorSyncRunService
from eylo.sor.shared.webhook_services import SorWebhookService

logger = logging.getLogger(__name__)

_RECONCILIATION_INTERVAL = timedelta(hours=24)
_DUE_LIMIT = 100
_RELATIONSHIP_RETRY_LIMIT = 100


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
                        ~select(SorSyncGenerationModel.id)
                        .where(
                            SorSyncGenerationModel.organization_id
                            == SorSourceStreamModel.organization_id,
                            SorSyncGenerationModel.source_id
                            == SorSourceStreamModel.source_id,
                            SorSyncGenerationModel.state.in_(
                                (
                                    SorWorkState.PENDING,
                                    SorWorkState.RUNNING,
                                    SorWorkState.WAITING,
                                )
                            ),
                            SorSyncGenerationModel.deleted.is_(False),
                        )
                        .exists(),
                    )
                    .order_by(
                        SorSourceStreamModel.next_due_at.asc(),
                        SorSourceStreamModel.id.asc(),
                    )
                    .limit(_DUE_LIMIT)
                )
            ).all()
        )

    last_reconciliations: dict[UUID, datetime] = {}
    if rows:
        due_stream_ids = tuple(row[2] for row in rows)
        async with start_transaction(ro=True) as session:
            reconciliation_rows = (
                await session.execute(
                    select(
                        SorSyncRunModel.stream_id,
                        func.max(SorSyncRunModel.finished_at),
                    )
                    .where(
                        SorSyncRunModel.stream_id.in_(due_stream_ids),
                        SorSyncRunModel.kind == SorSyncRunKind.RECONCILIATION,
                        SorSyncRunModel.state == SorWorkState.SUCCEEDED,
                        SorSyncRunModel.deleted.is_(False),
                    )
                    .group_by(SorSyncRunModel.stream_id)
                )
            ).all()
        last_reconciliations = {
            stream_id: finished_at
            for stream_id, finished_at in reconciliation_rows
            if stream_id is not None and finished_at is not None
        }

    planned: dict[tuple[UUID, UUID], list[tuple[UUID, bool]]] = {}
    for organization_id, source_id, stream_id, strategy in rows:
        last_reconciliation = last_reconciliations.get(stream_id)
        requires_reconciliation = (
            strategy is SorChangeStrategy.FULL_RECONCILE
            or last_reconciliation is None
            or last_reconciliation <= now - _RECONCILIATION_INTERVAL
        )
        planned.setdefault((organization_id, source_id), []).append(
            (stream_id, requires_reconciliation)
        )

    filed: list[tuple[UUID, UUID]] = []
    filed_runs = 0
    for (organization_id, source_id), source_streams in planned.items():
        kind = (
            SorSyncRunKind.RECONCILIATION
            if any(requires for _, requires in source_streams)
            else SorSyncRunKind.INCREMENTAL
        )
        stream_ids = [stream_id for stream_id, _ in source_streams]
        try:
            async with start_transaction() as session:
                plan = await SorSyncRunService(session).create_generation(
                    organization_id=organization_id,
                    source_id=source_id,
                    stream_ids=stream_ids,
                    kind=kind,
                )
                run_count = len(plan.runs)
                ready_run_ids = plan.ready_run_ids
            filed_runs += run_count
            filed.extend(
                (organization_id, run_id) for run_id in ready_run_ids
            )
        except Exception as error:  # noqa: BLE001 - source generations remain independent
            logger.error(
                "Could not file due SOR generation source_id=%s kind=%s "
                "error_type=%s",
                source_id,
                kind.value,
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
    return {"due": len(rows), "filed": filed_runs, "spawned": spawned}


async def nudge_sor_work() -> dict[str, int]:
    """Recover every currently implemented SOR durable outbox."""
    subscriptions = await maintain_sor_webhook_subscriptions()
    stopped = await recover_fenced_sor_work(limit=100)
    terminal_syncs = await reconcile_terminal_sor_sync_runs(limit=100)
    generations = await reconcile_unadvanced_sor_sync_generations(limit=100)
    syncs = await spawn_unbound_sor_sync_runs(limit=100)
    webhooks = await spawn_unbound_sor_webhook_receipts(limit=100)
    commands = await spawn_unbound_sor_commands(limit=100)
    async with start_transaction() as session:
        relationship_stats = await SorRelationshipService(session).resolve_pending(
            limit=_RELATIONSHIP_RETRY_LIMIT
        )
    async with start_transaction() as session:
        pruned = await SorWebhookService(session).prune_expired_raw_bodies()
    return {
        "webhook_subscriptions_eligible": subscriptions.eligible,
        "webhook_subscriptions_activated": subscriptions.activated,
        "webhook_subscriptions_failed": subscriptions.failed,
        "webhook_configuration_unavailable": (
            subscriptions.configuration_unavailable
        ),
        "cancelled_syncs": stopped.sync_runs,
        "cancelled_webhooks": stopped.webhook_receipts,
        "cancelled_commands": stopped.commands,
        "terminal_syncs_checked": terminal_syncs["checked"],
        "terminal_syncs_failed": terminal_syncs["failed"],
        "terminal_syncs_cancelled": terminal_syncs["cancelled"],
        "terminal_syncs_raced": terminal_syncs["raced"],
        "terminal_sync_errors": terminal_syncs["errors"],
        "generations_checked": generations["checked"],
        "generations_reconciled": generations["reconciled"],
        "generation_errors": generations["errors"],
        "syncs": syncs,
        "webhooks": webhooks,
        "commands": commands,
        "relationships_checked": relationship_stats.checked,
        "relationships_resolved": relationship_stats.resolved,
        "relationships_pending": relationship_stats.pending,
        "pruned": pruned,
    }


__all__ = ["dispatch_due_sor_syncs", "nudge_sor_work"]
