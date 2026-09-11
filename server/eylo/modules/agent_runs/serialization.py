"""Generic finite-JSON boundary for product-owned run context and results."""

import json

from pydantic import ConfigDict, JsonValue, TypeAdapter

_JSON_OBJECT_ADAPTER = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, hide_input_in_errors=True)
)


def validate_agent_run_json_object(value: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Copy finite JSON without interpreting another product's manifest fields.

    Producers serialize their owning models before filing. Do not silently
    coerce runtime resources, non-string keys, or non-finite numbers into state
    that a different worker would interpret differently after restart.
    """
    payload = _JSON_OBJECT_ADAPTER.validate_python(value)
    json.dumps(payload, allow_nan=False)
    return payload
