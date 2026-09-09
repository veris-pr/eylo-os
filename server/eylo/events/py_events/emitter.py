"""Ephemeral event emission for the `events` platform."""

import logging
import os
from types import EllipsisType
from typing import override

from pydantic import BaseModel
from pyventus.events import AsyncIOEventEmitter, EventEmitter
from pyventus.events import EventLinker as _EventLinker

type SubscribableEventType = str | type[object] | EllipsisType

logger = logging.getLogger(__name__)

EPHEMERAL_EVENT_MAX_BYTES = 64 * 1024


class EyloLinker(_EventLinker):
    @classmethod
    @override
    def get_valid_event_name(cls, event: SubscribableEventType) -> str:
        if isinstance(event, type) and issubclass(event, BaseModel):
            return event.__name__
        return super().get_valid_event_name(event)


_ee: EventEmitter | None = None
_ee_pid: int | None = None


def _get_event_emitter() -> EventEmitter:
    """Reuse within a process; initialize afresh after a PID change."""
    global _ee, _ee_pid

    current_pid = os.getpid()

    if _ee is None or _ee_pid != current_pid:
        logger.info("Initializing event emitter for PID %s", current_pid)
        _ee = AsyncIOEventEmitter(event_linker=EyloLinker)
        _ee_pid = current_pid

    return _ee


def emit_ephemeral(event: BaseModel) -> bool:
    """Emit one bounded, best-effort in-process hook or UI delta.

    Local event loss is allowed. Serialization or handler-scheduling failures
    are logged without interrupting the canonical product flow.
    """
    event_name = type(event).__name__
    try:
        payload_size = len(event.model_dump_json().encode())
    except Exception as error:  # noqa: BLE001 - presentation cannot block authority
        logger.error(
            "Could not serialize ephemeral event name=%s error_type=%s",
            event_name,
            type(error).__name__,
        )
        return False
    if payload_size > EPHEMERAL_EVENT_MAX_BYTES:
        logger.warning(
            "Dropped oversized ephemeral event %s (%s > %s bytes).",
            event_name,
            payload_size,
            EPHEMERAL_EVENT_MAX_BYTES,
        )
        return False
    try:
        _get_event_emitter().emit(event)
    except Exception as error:  # noqa: BLE001 - presentation cannot block authority
        logger.error(
            "Could not schedule ephemeral event name=%s error_type=%s",
            event_name,
            type(error).__name__,
        )
        return False
    return True
