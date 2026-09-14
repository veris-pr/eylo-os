"""Registered current-time system tool."""

from datetime import datetime, timezone


async def get_current_time(
    *,
    ctx: object = None,
) -> int:
    """Return the current UTC time as whole seconds since the Unix epoch."""
    return int(datetime.now(timezone.utc).timestamp())
