"""Scalar carrier metadata; routing meaning remains owned by the pipeline."""

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

_WIRE_PARAMETERS = TypeAdapter(dict[str, str | int], config=ConfigDict(strict=True))


class StreamParameters(BaseModel):
    """Reject implicit object stringification before XML, URL or JSON encoding."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    values: dict[str, str | int] = Field(repr=False, exclude=True)

    def as_wire(self) -> dict[str, str | int]:
        """Return a validated copy, including after nested dictionary mutation."""
        return _WIRE_PARAMETERS.validate_python(self.values)
