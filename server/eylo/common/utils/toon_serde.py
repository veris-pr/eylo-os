"""Project explicit platform context values before TOON encoding."""

from datetime import date, datetime
from enum import Enum
from math import isfinite
from uuid import UUID

from pydantic import BaseModel
from toon import encode

type ToonValue = (
    bool | int | float | str | None | date | datetime | UUID | Enum | BaseModel
    | list[ToonValue] | dict[str, ToonValue]
)


class ToonEncodingError(ValueError):
    """Context cannot be encoded faithfully; submitted values are not retained."""


def toon_encode(data: ToonValue) -> str:
    """Encode supported values without silently replacing unknown types with null."""
    try:
        return encode(_project_context(data, set()))
    except RecursionError:
        raise ToonEncodingError("Context nesting exceeds the encoder limit") from None


def _project_context(value: object, ancestors: set[int]) -> ToonValue:
    if isinstance(value, Enum):
        return _project_context(value.value, ancestors)
    if value is None or isinstance(value, (bool, int, str, date, datetime)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ToonEncodingError("Context numbers must be finite")
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (BaseModel, dict, list)):
        identity = id(value)
        if identity in ancestors:
            raise ToonEncodingError("Context cannot contain cycles")
        ancestors.add(identity)
        try:
            if isinstance(value, BaseModel):
                return _project_context(value.model_dump(), ancestors)
            if isinstance(value, dict):
                result: dict[str, ToonValue] = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ToonEncodingError("Context object keys must be strings")
                    result[key] = _project_context(item, ancestors)
                return result
            return [_project_context(item, ancestors) for item in value]
        finally:
            ancestors.remove(identity)
    raise ToonEncodingError("Unsupported context value")
