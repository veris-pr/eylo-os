"""Convert typed SOR values only at JSON persistence and transport boundaries."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class SorJsonValueError(ValueError):
    """A typed SOR value cannot be represented by canonical JSON."""


def to_json_value(value: object) -> object:
    """Recursively detach a typed value into deterministic JSON-native data."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SorJsonValueError("SOR JSON numbers must be finite.")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SorJsonValueError("SOR datetimes must include a timezone.")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, BaseModel):
        return to_json_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [to_json_value(item) for item in value]
    raise SorJsonValueError("SOR value is not JSON-compatible.")


__all__ = ["SorJsonValueError", "to_json_value"]
