"""Revoke shared connection authority and stop dependent product work."""

from __future__ import annotations

from uuid import UUID

from eylo.common.database import start_transaction
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.sor.runtime.revocation import (
    prepare_sor_connection_revocation,
    stop_revoked_sor_connection_work,
)


async def revoke_external_connection(
    *,
    organization_id: UUID,
    connection_id: UUID,
) -> bool:
    """Revoke one connection atomically, then interrupt captured SOR work."""
    async with start_transaction() as session:
        connection = await ExternalConnectionService(session).revoke_with_snapshot(
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if connection is None:
            return False
        plan = await prepare_sor_connection_revocation(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            connection_revision=connection.revision,
            occurred_at=connection.updated_at,
        )
    await stop_revoked_sor_connection_work(plan)
    return True


__all__ = ["revoke_external_connection"]
