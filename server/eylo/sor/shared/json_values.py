"""Convert typed SOR values only at JSON persistence and transport boundaries."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, JsonValue, TypeAdapter


class SorJsonValueError(ValueError):
    """A typed SOR value cannot be represented by canonical JSON."""


def _finite_json(value: JsonValue) -> JsonValue:
    """Reject non-finite numbers anywhere in an already validated JSON tree."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise SorJsonValueError("SOR JSON numbers must be finite.")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


SorJsonValue = Annotated[JsonValue, AfterValidator(_finite_json)]
_JSON_VALUE = TypeAdapter(SorJsonValue)


def require_json_value(value: object) -> JsonValue:
    """Validate native JSON without coercing objects, keys, dates or numbers."""
    return _JSON_VALUE.validate_python(value, strict=True)


def require_json_object(value: object) -> dict[str, JsonValue]:
    """Copy a JSON mapping at an adapter boundary without coercing its values."""
    if not isinstance(value, Mapping):
        raise SorJsonValueError("SOR JSON object must be a mapping.")
    validated = require_json_value(dict(value))
    if not isinstance(validated, dict):
        raise SorJsonValueError("SOR JSON object must be a mapping.")
    return validated


def to_json_value(value: object) -> JsonValue:
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


__all__ = [
    "SorJsonValue",
    "SorJsonValueError",
    "require_json_object",
    "require_json_value",
    "to_json_value",
]
