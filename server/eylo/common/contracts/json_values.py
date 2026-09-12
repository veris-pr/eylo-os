"""Finite, extensible JSON objects at platform data-contract boundaries."""

from typing import Annotated

from pydantic import BeforeValidator, ConfigDict, JsonValue, TypeAdapter

_JSON_OBJECT = TypeAdapter(
    dict[str, JsonValue],
    config=ConfigDict(strict=True, allow_inf_nan=False, hide_input_in_errors=True),
)


def _finite_json_object(value: object) -> dict[str, JsonValue]:
    # JsonValue's JSON-mode schema bypasses numeric constraints. Python-mode
    # validation here also rejects NaN/infinity after model_validate_json().
    return _JSON_OBJECT.validate_python(value)


type JsonObject = Annotated[dict[str, JsonValue], BeforeValidator(_finite_json_object)]
