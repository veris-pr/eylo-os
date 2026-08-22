"""Periodic tasks for connection management."""

import logging
from datetime import datetime, timezone

from eylo.common.database import start_transaction
from eylo.modules.connections.repositories.oauth_state import OAuthStateRepository
from eylo.modules.connections.services.external import ExternalConnectionService

logger = logging.getLogger(__name__)


async def cleanup_invalidated_connections() -> dict:
    """Delete old revoked contact-owned external connections after retention."""
    logger.info("[CleanupConnectionsTask] Starting cleanup")
    try:
        async with start_transaction() as db:
            connection_ids = await ExternalConnectionService(
                db
            ).cleanup_old_revoked_contact_connections(retention_days=30)
            deleted_count = len(connection_ids)
        logger.info(f"[CleanupConnectionsTask] Deleted {deleted_count} connections")
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as error:
        logger.error(
            "[CleanupConnectionsTask] Failed error_type=%s",
            type(error).__name__,
        )
        return {"status": "error", "error": "Connection cleanup failed."}


async def cleanup_expired_oauth_states() -> dict:
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
                ).revoke_expired_authorization_attempt(
                    organization_id=state.organization_id,
                    connection_id=state.external_connection_id,
                    expected_revision=state.expected_connection_revision,
                )
        deleted_count = len(expired_states)
        logger.info(f"[CleanupOAuthStatesTask] Deleted {deleted_count} states")
        return {"status": "success", "deleted_count": deleted_count}
    except Exception as error:
        logger.error(
            "[CleanupOAuthStatesTask] Failed error_type=%s",
            type(error).__name__,
        )
        return {"status": "error", "error": "OAuth state cleanup failed."}
