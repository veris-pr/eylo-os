"""Delete one SOR source after fencing and stopping its durable work."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.modules.connections.repositories.oauth_state import OAuthStateRepository
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.sor.runtime.commands import cancel_sor_command
from eylo.sor.runtime.sync import cancel_sor_sync_run
from eylo.sor.runtime.webhook_subscriptions import remove_sor_webhook_subscription
from eylo.sor.runtime.webhooks import cancel_sor_webhook_receipt
from eylo.sor.shared.connector_services import SorConnectorService
from eylo.sor.shared.deletion import (
    SorSourceDeletionPlan,
    SorSourceDeletionService,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorConflictError

logger = logging.getLogger(__name__)


async def delete_sor_source(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> None:
    """Fence, stop delivery/work, then purge one source-owned local aggregate."""
    async with start_transaction() as session:
        plan = await SorSourceDeletionService(session).fence(
            organization_id=organization_id,
            source_id=source_id,
        )

    await _stop_source_work(plan)
    await _remove_vendor_webhook(plan)

    async with start_transaction() as session:
        await SorSourceDeletionService(session).purge(
            organization_id=organization_id,
            source_id=source_id,
        )
        await _purge_connection_authority(
            session,
            organization_id=organization_id,
            connection_id=plan.external_connection_id,
            connector_id=plan.connector_id,
        )


async def delete_sor_connector(
    *,
    organization_id: UUID,
    connector_id: UUID,
) -> None:
    """Discard one unclaimed onboarding connector and all local auth state."""
    async with start_transaction() as session:
        view = await SorConnectorService(session).get(
            organization_id=organization_id,
            connector_id=connector_id,
            for_update=True,
        )
        connection_id = view.connector.external_connection_id
        if connection_id is not None:
            await SorRepository(session).get_connection(
                organization_id=organization_id,
                connection_id=connection_id,
                vendor_key=view.connector.vendor_key,
                for_update=True,
                include_deleted=True,
            )
            claims = await SorRepository(session).list_sources_for_connection(
                organization_id=organization_id,
                connection_id=connection_id,
            )
            if claims:
                raise SorConflictError(
                    "This OAuth configuration belongs to a source. "
                    "Delete the source instead."
                )
        await _purge_connection_authority(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            connector_id=view.connector.id,
        )


async def _purge_connection_authority(
    session: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID | None,
    connector_id: UUID | None,
) -> None:
    """Erase one source-owned local OAuth config and revoke its credentials."""
    if connector_id is not None:
        connector = await SorRepository(session).get_connector(
            organization_id=organization_id,
            connector_id=connector_id,
            for_update=True,
        )
        if connector is not None:
            await session.delete(connector)
            await session.flush()
    if connection_id is None:
        return
    await OAuthStateRepository(session).delete_for_connection(
        organization_id=organization_id,
        external_connection_id=connection_id,
    )
    await ExternalConnectionService(session).revoke(
        organization_id=organization_id,
        connection_id=connection_id,
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


async def _remove_vendor_webhook(plan: SorSourceDeletionPlan) -> None:
    """Best-effort stop vendor delivery; local deletion never depends on it."""
    try:
        await remove_sor_webhook_subscription(
            organization_id=plan.organization_id,
            source_id=plan.source_id,
        )
    except Exception as error:  # noqa: BLE001 - the committed fence is authority
        logger.error(
            "Could not remove vendor webhook before SOR source purge "
            "source_id=%s error_type=%s",
            plan.source_id,
            type(error).__name__,
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


__all__ = ["delete_sor_connector", "delete_sor_source"]
