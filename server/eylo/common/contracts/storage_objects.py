"""Provider-neutral observations consumed by storage and document workflows."""

from pydantic import BaseModel, ConfigDict, Field


class StoredObject(BaseModel):
    """One validated object observation; size is bytes, not a truthy predicate."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    key: str
    size: int = Field(ge=0)
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
