"""Fence SOR sources and stop durable work after connection revocation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.sor.runtime.action_events import (
    SorConnectionEventType,
    file_sor_connection_event,
)
from eylo.sor.runtime.commands import cancel_sor_command
from eylo.sor.runtime.sync import cancel_sor_sync_run
from eylo.sor.runtime.webhooks import cancel_sor_webhook_receipt
from eylo.sor.shared.contracts import (
    SorCommandState,
    SorSourceState,
    SorSourceTransition,
    SorWebhookReceiptState,
    SorWorkState,
)
from eylo.sor.shared.models import (
    SorCommandModel,
    SorConnectorModel,
    SorSourceModel,
    SorSyncRunModel,
    SorWebhookReceiptModel,
)
from eylo.sor.shared.services import SorSourceService

logger = logging.getLogger(__name__)
SOR_REVOCATION_RECOVERY_LIMIT = 100
SOR_REVOCATION_RECOVERY_MAX = 1000
SOR_CONNECTION_REVOKED_CODE = "CONNECTION_REVOKED"


class _RevokedWorkKind(StrEnum):
    SYNC_RUN = "sync run"
    WEBHOOK_RECEIPT = "webhook receipt"
    COMMAND = "command"


class _RevocationWork(BaseModel):
    """Only validated work/tenant identities leave the read transaction."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    work_id: UUID


class SorConnectionRevocationPlan(BaseModel):
    """Exact durable SOR work fenced by one committed connection revocation."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    source_ids: tuple[UUID, ...]
    sync_run_ids: tuple[UUID, ...]
    webhook_receipt_ids: tuple[UUID, ...]
    command_ids: tuple[UUID, ...]


class SorConnectionStopResult(BaseModel):
    """Best-effort cancellation counts after the revocation transaction commits."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    sync_runs: int = Field(default=0, ge=0)
    webhook_receipts: int = Field(default=0, ge=0)
    commands: int = Field(default=0, ge=0)


async def recover_fenced_sor_work(
    *, limit: int = SOR_REVOCATION_RECOVERY_LIMIT
) -> SorConnectionStopResult:
    """Stop active work left behind after a committed source authority fence."""
    if not 1 <= limit <= SOR_REVOCATION_RECOVERY_MAX:
        raise ValueError("SOR revocation recovery limit must be between 1 and 1000.")
    fenced_states = (SorSourceState.REAUTH_REQUIRED, SorSourceState.DISABLED)
    async with start_transaction(ro=True) as session:
        sync_runs = tuple(
            _RevocationWork(organization_id=organization_id, work_id=work_id)
            for organization_id, work_id in (
                await session.execute(
                    select(SorSyncRunModel.organization_id, SorSyncRunModel.id)
                    .join(
                        SorSourceModel,
                        (SorSourceModel.id == SorSyncRunModel.source_id)
                        & (
                            SorSourceModel.organization_id
                            == SorSyncRunModel.organization_id
                        ),
                    )
                    .where(
                        SorSourceModel.state.in_(fenced_states),
                        SorSourceModel.deleted.is_(False),
                        SorSyncRunModel.state.in_(
                            (
                                SorWorkState.PENDING,
                                SorWorkState.RUNNING,
                                SorWorkState.WAITING,
                            )
                        ),
                        SorSyncRunModel.deleted.is_(False),
                    )
                    .order_by(
                        SorSyncRunModel.created_at.asc(), SorSyncRunModel.id.asc()
                    )
                    .limit(limit)
                )
            ).all()
        )
        webhook_receipts = tuple(
            _RevocationWork(organization_id=organization_id, work_id=work_id)
            for organization_id, work_id in (
                await session.execute(
                    select(
                        SorWebhookReceiptModel.organization_id,
                        SorWebhookReceiptModel.id,
                    )
                    .join(
                        SorSourceModel,
                        (SorSourceModel.id == SorWebhookReceiptModel.source_id)
                        & (
                            SorSourceModel.organization_id
                            == SorWebhookReceiptModel.organization_id
                        ),
                    )
                    .where(
                        SorSourceModel.state.in_(fenced_states),
                        SorSourceModel.deleted.is_(False),
                        SorWebhookReceiptModel.state.in_(
                            (
                                SorWebhookReceiptState.PENDING,
                                SorWebhookReceiptState.PROCESSING,
                            )
                        ),
                        SorWebhookReceiptModel.deleted.is_(False),
                    )
                    .order_by(
                        SorWebhookReceiptModel.created_at.asc(),
                        SorWebhookReceiptModel.id.asc(),
                    )
                    .limit(limit)
                )
            ).all()
        )
        commands = tuple(
            _RevocationWork(organization_id=organization_id, work_id=work_id)
            for organization_id, work_id in (
                await session.execute(
                    select(SorCommandModel.organization_id, SorCommandModel.id)
                    .join(
                        SorSourceModel,
                        (SorSourceModel.id == SorCommandModel.source_id)
                        & (
                            SorSourceModel.organization_id
                            == SorCommandModel.organization_id
                        ),
                    )
                    .where(
                        SorSourceModel.state.in_(fenced_states),
                        SorSourceModel.deleted.is_(False),
                        SorCommandModel.state.in_(
                            (SorCommandState.PENDING, SorCommandState.RUNNING)
                        ),
                        SorCommandModel.deleted.is_(False),
                    )
                    .order_by(
                        SorCommandModel.created_at.asc(), SorCommandModel.id.asc()
                    )
                    .limit(limit)
                )
            ).all()
        )
    return SorConnectionStopResult(
        sync_runs=await _stop_owned_each(
            sync_runs,
            kind=_RevokedWorkKind.SYNC_RUN,
            stop=lambda organization_id, work_id: cancel_sor_sync_run(
                organization_id=organization_id,
                run_id=work_id,
            ),
        ),
        webhook_receipts=await _stop_owned_each(
            webhook_receipts,
            kind=_RevokedWorkKind.WEBHOOK_RECEIPT,
            stop=lambda organization_id, work_id: cancel_sor_webhook_receipt(
                organization_id=organization_id,
                receipt_id=work_id,
            ),
        ),
        commands=await _stop_owned_each(
            commands,
            kind=_RevokedWorkKind.COMMAND,
            stop=lambda organization_id, work_id: cancel_sor_command(
                organization_id=organization_id,
                command_id=work_id,
            ),
        ),
    )


async def prepare_sor_connection_revocation(
    session: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    connection_revision: int,
    occurred_at: datetime,
) -> SorConnectionRevocationPlan:
    """Fence dependent sources and capture their active work in one transaction."""
    connector = await session.scalar(
        select(SorConnectorModel).where(
            SorConnectorModel.organization_id == organization_id,
            SorConnectorModel.external_connection_id == connection_id,
            SorConnectorModel.deleted.is_(False),
        )
    )
    sources = tuple(
        (
            await session.scalars(
                select(SorSourceModel)
                .where(
                    SorSourceModel.organization_id == organization_id,
                    SorSourceModel.external_connection_id == connection_id,
                    SorSourceModel.deleted.is_(False),
                )
                .order_by(SorSourceModel.id.asc())
                .with_for_update()
            )
        ).all()
    )
    for source in sources:
        if source.state not in {
            SorSourceState.REAUTH_REQUIRED,
            SorSourceState.DISABLED,
        }:
            await SorSourceService(session).transition(
                organization_id=organization_id,
                source_id=source.id,
                transition=SorSourceTransition.REAUTHORIZATION_REQUIRED,
                error_code=SOR_CONNECTION_REVOKED_CODE,
                error_summary="The source connection was revoked.",
            )
        await file_sor_connection_event(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            connection_revision=connection_revision,
            event_sequence=f"revoked:{connection_revision}:source:{source.id}",
            event_type=SorConnectionEventType.REVOKED,
            occurred_at=occurred_at,
            profile=source.profile,
            vendor_key=source.vendor_key,
            connector_id=connector.id if connector is not None else None,
            source_id=source.id,
        )
    if not sources and connector is not None:
        await file_sor_connection_event(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            connection_revision=connection_revision,
            event_sequence=f"revoked:{connection_revision}:connector:{connector.id}",
            event_type=SorConnectionEventType.REVOKED,
            occurred_at=occurred_at,
            profile=connector.profile,
            vendor_key=connector.vendor_key,
            connector_id=connector.id,
        )

    source_ids = tuple(source.id for source in sources)
    if not source_ids:
        return SorConnectionRevocationPlan(
            organization_id=organization_id,
            source_ids=(),
            sync_run_ids=(),
            webhook_receipt_ids=(),
            command_ids=(),
        )
    sync_run_ids = tuple(
        (
            await session.scalars(
                select(SorSyncRunModel.id)
                .where(
                    SorSyncRunModel.organization_id == organization_id,
                    SorSyncRunModel.source_id.in_(source_ids),
                    SorSyncRunModel.state.in_(
                        (
                            SorWorkState.PENDING,
                            SorWorkState.RUNNING,
                            SorWorkState.WAITING,
                        )
                    ),
                    SorSyncRunModel.deleted.is_(False),
                )
                .order_by(SorSyncRunModel.created_at.asc(), SorSyncRunModel.id.asc())
            )
        ).all()
    )
    webhook_receipt_ids = tuple(
        (
            await session.scalars(
                select(SorWebhookReceiptModel.id)
                .where(
                    SorWebhookReceiptModel.organization_id == organization_id,
                    SorWebhookReceiptModel.source_id.in_(source_ids),
                    SorWebhookReceiptModel.state.in_(
                        (
                            SorWebhookReceiptState.PENDING,
                            SorWebhookReceiptState.PROCESSING,
                        )
                    ),
                    SorWebhookReceiptModel.deleted.is_(False),
                )
                .order_by(
                    SorWebhookReceiptModel.created_at.asc(),
                    SorWebhookReceiptModel.id.asc(),
                )
            )
        ).all()
    )
    command_ids = tuple(
        (
            await session.scalars(
                select(SorCommandModel.id)
                .where(
                    SorCommandModel.organization_id == organization_id,
                    SorCommandModel.source_id.in_(source_ids),
                    SorCommandModel.state.in_(
                        (SorCommandState.PENDING, SorCommandState.RUNNING)
                    ),
                    SorCommandModel.deleted.is_(False),
                )
                .order_by(SorCommandModel.created_at.asc(), SorCommandModel.id.asc())
            )
        ).all()
    )
    return SorConnectionRevocationPlan(
        organization_id=organization_id,
        source_ids=source_ids,
        sync_run_ids=sync_run_ids,
        webhook_receipt_ids=webhook_receipt_ids,
        command_ids=command_ids,
    )


async def stop_revoked_sor_connection_work(
    plan: SorConnectionRevocationPlan,
) -> SorConnectionStopResult:
    """Cancel every captured task without undoing the committed revocation."""
    sync_runs = await _stop_each(
        plan.sync_run_ids,
        kind=_RevokedWorkKind.SYNC_RUN,
        stop=lambda work_id: cancel_sor_sync_run(
            organization_id=plan.organization_id,
            run_id=work_id,
        ),
    )
    webhook_receipts = await _stop_each(
        plan.webhook_receipt_ids,
        kind=_RevokedWorkKind.WEBHOOK_RECEIPT,
        stop=lambda work_id: cancel_sor_webhook_receipt(
            organization_id=plan.organization_id,
            receipt_id=work_id,
        ),
    )
    commands = await _stop_each(
        plan.command_ids,
        kind=_RevokedWorkKind.COMMAND,
        stop=lambda work_id: cancel_sor_command(
            organization_id=plan.organization_id,
            command_id=work_id,
        ),
    )
    return SorConnectionStopResult(
        sync_runs=sync_runs,
        webhook_receipts=webhook_receipts,
        commands=commands,
    )


async def _stop_each(
    work_ids: Sequence[UUID],
    *,
    kind: _RevokedWorkKind,
    stop: Callable[[UUID], Awaitable[bool]],
) -> int:
    stopped = 0
    for work_id in work_ids:
        try:
            if await stop(work_id):
                stopped += 1
        except Exception as error:  # noqa: BLE001 - authority is already revoked
            logger.error(
                "Could not stop SOR %s after connection revocation "
                "work_id=%s error_type=%s",
                kind,
                work_id,
                type(error).__name__,
            )
    return stopped


async def _stop_owned_each(
    work: Sequence[_RevocationWork],
    *,
    kind: _RevokedWorkKind,
    stop: Callable[[UUID, UUID], Awaitable[bool]],
) -> int:
    stopped = 0
    for item in work:
        try:
            if await stop(item.organization_id, item.work_id):
                stopped += 1
        except Exception as error:  # noqa: BLE001 - persisted fence is authoritative
            logger.error(
                "Could not recover fenced SOR %s work_id=%s error_type=%s",
                kind,
                item.work_id,
                type(error).__name__,
            )
    return stopped


__all__ = [
    "SorConnectionRevocationPlan",
    "SorConnectionStopResult",
    "prepare_sor_connection_revocation",
    "recover_fenced_sor_work",
    "stop_revoked_sor_connection_work",
]
