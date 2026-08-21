"""Serialize adapter-owned values at SOR durable execution boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from eylo.sor.shared.services import SorProjectionError


def json_safe_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a recursively JSON-native payload or reject an unsafe value."""
    return {str(key): _json_safe(value) for key, value in payload.items()}


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SorProjectionError("Source datetimes must include a timezone.")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_json_safe(item) for item in value]
    raise SorProjectionError("Source payload contains a non-JSON value.")


__all__ = ["json_safe_payload"]
