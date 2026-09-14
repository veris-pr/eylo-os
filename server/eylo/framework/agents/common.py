"""Shared types for the Eylo agent framework contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    JsonValue,
    TypeAdapter,
    model_validator,
)


def _finite_json(value: JsonValue) -> JsonValue:
    """Reject non-finite numbers anywhere in a framework JSON payload."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Framework JSON numbers must be finite.")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value


type FiniteJsonValue = Annotated[JsonValue, AfterValidator(_finite_json)]
type JsonObject = dict[str, FiniteJsonValue]
_JSON_OBJECT = TypeAdapter(JsonObject, config=ConfigDict(strict=True))


class FrameworkModel(BaseModel):
    """Base model for mutable framework state."""

    model_config = ConfigDict(
        extra="forbid", arbitrary_types_allowed=True, allow_inf_nan=False
    )


class FrozenFrameworkModel(BaseModel):
    """Base model for immutable framework value objects."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
        allow_inf_nan=False,
    )


class FrameworkMetadata(BaseModel):
    """Platform metadata envelope for framework primitives.

    Framework metadata is schema-backed. Subsystems should define focused
    subclasses for known fields; this base remains extensible so older persisted
    metadata and integration-provided annotations can round-trip safely.

    Framework metadata fields explicitly preserve those subclasses during
    serialization. Only transportable metadata belongs here; runtime dependencies
    belong in RunContext.local_context. Subclass-private fields must be excluded
    by their owner, and normal Pydantic include/exclude rules still apply.
    """

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        arbitrary_types_allowed=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="before")
    @classmethod
    def validate_extra_json(cls, value: object) -> object:
        """Validate only extensible fields; declared subclass fields own their types."""
        if isinstance(value, cls) or not isinstance(value, Mapping):
            return value
        extras = {key: item for key, item in value.items() if key not in cls.model_fields}
        _JSON_OBJECT.validate_python(extras)
        return value

    def get(self, key: str, default: object = None) -> object:
        if key in self.__class__.model_fields:
            return getattr(self, key)
        if self.model_extra and key in self.model_extra:
            return self.model_extra[key]
        return default

    def __contains__(self, key: str) -> bool:
        return key in self.__class__.model_fields or bool(
            self.model_extra and key in self.model_extra
        )

    def __getitem__(self, key: str) -> object:
        if key not in self:
            raise KeyError(key)
        return self.get(key)
