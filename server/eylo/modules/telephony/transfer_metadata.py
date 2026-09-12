"""Typed transfer observations with finite, extensible JSON context."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from eylo.common.contracts.json_values import JsonObject
from eylo.common.outbound import require_failure_code

_JSON_OBJECT = TypeAdapter(JsonObject)


class CallTransferMetadata(BaseModel):
    """Preserve omitted fields and custom context in the existing flat DB shape."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="allow",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    carrier_outcome_at: str | None = None
    failure_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def finite_context(cls, value: object) -> JsonObject:
        if isinstance(value, cls):
            value = value.model_dump(mode="python", exclude_unset=True)
        return _JSON_OBJECT.validate_python(value)

    def as_payload(self) -> JsonObject:
        """Revalidate nested mutable context immediately before persistence."""
        return _JSON_OBJECT.validate_python(
            self.model_dump(mode="python", exclude_unset=True)
        )

    def merged(self, incoming: Self) -> Self:
        """Incoming observations replace matching keys; unrelated context survives."""
        return type(self).model_validate({**self.as_payload(), **incoming.as_payload()})

    def with_outcome(self, *, observed_at: datetime, failure_code: str | None) -> Self:
        """Record the carrier observation without clearing prior failure context."""
        observation = type(self)(carrier_outcome_at=observed_at.isoformat())
        if failure_code is not None:
            observation = type(self)(
                carrier_outcome_at=observed_at.isoformat(),
                failure_code=require_failure_code(failure_code),
            )
        return self.merged(observation)
