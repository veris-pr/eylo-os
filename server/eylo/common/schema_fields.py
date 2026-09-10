"""Shared API field metadata without domain-owned configuration policy."""

from pydantic import Field
from pydantic.fields import FieldInfo


def experimental(*, ge: float | None = None, le: float | None = None) -> FieldInfo:
    """Expose stored-but-inert configuration in human and machine API docs."""
    return Field(
        description=(
            "EXPERIMENTAL — stored but not yet enforced. Setting this has no "
            "effect on behaviour."
        ),
        json_schema_extra={"experimental": True},
        ge=ge,
        le=le,
    )
