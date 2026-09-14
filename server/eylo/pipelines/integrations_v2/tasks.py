"""Periodic work for curated vendor connections."""

from __future__ import annotations

import logging

from .refresh import refresh_expiring_curated_connections
from .refresh_contracts import RefreshTaskResult, RefreshTaskStatus

logger = logging.getLogger(__name__)
_REFRESH_FAILURE_MESSAGE = "Curated token refresh failed."


async def refresh_expiring_curated_tokens() -> RefreshTaskResult:
    """Renew curated OAuth credentials expiring inside the refresh window."""
    logger.info("[CuratedRefreshTask] Starting curated token refresh cycle")
    try:
        outcome = await refresh_expiring_curated_connections()
    except Exception as error:  # noqa: BLE001 - the next tick retries the cycle
        logger.error("[CuratedRefreshTask] Failed error_type=%s", type(error).__name__)
        return {"status": RefreshTaskStatus.ERROR, "error": _REFRESH_FAILURE_MESSAGE}
    logger.info(
        "[CuratedRefreshTask] considered=%d refreshed=%d failed=%d skipped=%d",
        outcome.considered,
        len(outcome.refreshed),
        len(outcome.failed),
        len(outcome.skipped),
    )
    return {
        "status": RefreshTaskStatus.SUCCESS,
        "refreshed_count": len(outcome.refreshed),
        "failed_count": len(outcome.failed),
        "skipped_count": len(outcome.skipped),
    }


__all__ = ["refresh_expiring_curated_tokens"]
