"""Periodic tasks for connection management."""

import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.maintenance import MaintenanceFailure, MaintenanceStatus
from eylo.common.database import start_transaction
from eylo.modules.connections.repositories.oauth_state import OAuthStateRepository
from eylo.modules.connections.services.external import ExternalConnectionService

logger = logging.getLogger(__name__)

REVOKED_CONTACT_CONNECTION_RETENTION_DAYS = 30
CONNECTION_CLEANUP_FAILURE = "Connection cleanup failed."
OAUTH_STATE_CLEANUP_FAILURE = "OAuth state cleanup failed."


class ConnectionCleanupCompleted(BaseModel):
    """Count returned only after all cleanup transactions have completed."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    status: Literal[MaintenanceStatus.SUCCESS] = MaintenanceStatus.SUCCESS
    deleted_count: int = Field(ge=0)


async def cleanup_invalidated_connections() -> (
    ConnectionCleanupCompleted | MaintenanceFailure
):
    """Delete old revoked contact-owned external connections after retention."""
    logger.info("[CleanupConnectionsTask] Starting cleanup")
    try:
        async with start_transaction() as db:
            connection_ids = await ExternalConnectionService(
                db
            ).cleanup_old_revoked_contact_connections(
                retention_days=REVOKED_CONTACT_CONNECTION_RETENTION_DAYS
            )
            deleted_count = len(connection_ids)
        logger.info(f"[CleanupConnectionsTask] Deleted {deleted_count} connections")
        return ConnectionCleanupCompleted(deleted_count=deleted_count)
    except Exception as error:
        logger.error(
            "[CleanupConnectionsTask] Failed error_type=%s",
            type(error).__name__,
        )
        return MaintenanceFailure(error=CONNECTION_CLEANUP_FAILURE)


async def cleanup_expired_oauth_states() -> (
    ConnectionCleanupCompleted | MaintenanceFailure
):
    """Delete expired OAuth state records."""
    logger.info("[CleanupOAuthStatesTask] Starting cleanup")
    try:
        async with start_transaction() as db:
            expired_states = await OAuthStateRepository(db).delete_expired_states(
                datetime.now(timezone.utc)
            )
        for state in expired_states:
            async with start_transaction() as db:
                await ExternalConnectionService(
                    db
                ).revoke_pending_authorization_attempt(
                    organization_id=state.organization_id,
                    connection_id=state.external_connection_id,
                    expected_revision=state.expected_connection_revision,
                )
        deleted_count = len(expired_states)
        logger.info(f"[CleanupOAuthStatesTask] Deleted {deleted_count} states")
        return ConnectionCleanupCompleted(deleted_count=deleted_count)
    except Exception as error:
        logger.error(
            "[CleanupOAuthStatesTask] Failed error_type=%s",
            type(error).__name__,
        )
        return MaintenanceFailure(error=OAUTH_STATE_CLEANUP_FAILURE)
