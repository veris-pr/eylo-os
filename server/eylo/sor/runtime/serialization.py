"""Serialize adapter-owned values at SOR durable execution boundaries."""

from __future__ import annotations

from eylo.sor.shared.contracts import SorSourcePayload
from eylo.sor.shared.json_values import SorJsonValueError, to_json_value
from eylo.sor.shared.services import SorProjectionError


def json_safe_payload(payload: SorSourcePayload) -> dict[str, object]:
    """Return a recursively JSON-native payload or reject an unsafe value."""
    try:
        result = to_json_value(payload.to_wire())
    except SorJsonValueError as error:
        raise SorProjectionError("Source payload contains a non-JSON value.") from error
    if not isinstance(result, dict):
        raise SorProjectionError("Source payload is not a JSON object.")
    return result


__all__ = ["json_safe_payload"]
