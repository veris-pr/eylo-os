"""Content-free observability listeners for local System of Record events."""

from __future__ import annotations

import logging
from enum import Enum

from eylo.events.schema.py_events.sor import SorPostCommitEvent

logger = logging.getLogger(__name__)


async def observe_sor_event(event: SorPostCommitEvent) -> None:
    """Log bounded SOR identities and counts, never record or credential content."""
    logger.info(
        "System of Record local event",
        extra={
            "local_event_name": type(event).__name__,
            "organization_id": str(event.organization_id),
            "source_id": _optional_id(event, "source_id"),
            "stream_id": _optional_id(event, "stream_id"),
            "sync_run_id": _optional_id(event, "sync_run_id"),
            "record_id": _optional_id(event, "record_id"),
            "profile": _optional_value(event, "profile"),
            "entity": _optional_value(event, "entity"),
            "disposition": _optional_value(event, "disposition"),
            "kind": _optional_value(event, "kind"),
            "records_added": _optional_value(event, "records_added"),
            "records_updated": _optional_value(event, "records_updated"),
            "records_tombstoned": _optional_value(
                event,
                "records_tombstoned",
            ),
            "records_rejected": _optional_value(event, "records_rejected"),
        },
    )


def _optional_id(event: SorPostCommitEvent, field: str) -> str | None:
    value = getattr(event, field, None)
    return str(value) if value is not None else None


def _optional_value(event: SorPostCommitEvent, field: str) -> str | None:
    value = getattr(event, field, None)
    if isinstance(value, Enum):
        return str(value.value)
    return str(value) if value is not None else None
