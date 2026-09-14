"""Finite WebSocket projections from explicitly supported Python wire values."""

from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from math import isfinite
from uuid import UUID

from pydantic import JsonValue

from eylo.common.contracts.json_values import JsonObject

type WsProjectionValue = (
    str | bool | int | float | None | UUID | datetime | bytes | Enum
    | list[WsProjectionValue] | tuple[WsProjectionValue, ...]
    | Mapping[str, WsProjectionValue]
)


def project_ws_value(value: object) -> JsonValue:
    """Preserve existing wire scalars; never introspect or serialize arbitrary objects."""
    try:
        return _project_value(value, set())
    except RecursionError:
        raise ValueError("WebSocket projection is too deeply nested") from None


def _project_value(value: object, ancestors: set[int]) -> JsonValue:
    if isinstance(value, Enum):
        return _project_value(value.value, ancestors)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("WebSocket numbers must be finite")
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        # Compatibility for existing text projections, not microphone transport.
        return value.decode("utf-8", "ignore")
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("WebSocket projections cannot contain cycles")
        ancestors.add(identity)
        try:
            if isinstance(value, Mapping):
                result: JsonObject = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ValueError("WebSocket object keys must be strings")
                    result[key] = _project_value(item, ancestors)
                return result
            return [_project_value(item, ancestors) for item in value]
        finally:
            ancestors.remove(identity)
    raise ValueError("Unsupported WebSocket projection value")


def project_ws_object(value: object) -> JsonObject:
    """Project a named-field envelope, refusing scalar or collection roots."""
    result = project_ws_value(value)
    if not isinstance(result, dict):
        raise ValueError("WebSocket envelope must be an object")
    return result
