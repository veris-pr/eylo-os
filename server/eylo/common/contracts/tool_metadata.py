"""Code-owned tool declaration metadata, independent of registry and execution."""

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

_TOOL_METADATA_ATTRIBUTE = "__eylo_tool_metadata__"


class ToolFeatureFlag(StrEnum):
    SPAWN_TASK_FNF = "ENABLE_SPAWN_TASK_FNF"


class ToolCatalogVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"


class ToolFunctionMetadata(BaseModel):
    """Immutable declaration; the live schema class is not a JSON payload."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    input_schema: SkipJsonSchema[type[BaseModel] | None] = Field(
        default=None, repr=False, exclude=True
    )
    feature_flag: ToolFeatureFlag | None = None
    visibility: ToolCatalogVisibility = ToolCatalogVisibility.VISIBLE


_DEFAULT_METADATA = ToolFunctionMetadata()


def set_tool_metadata[Function: Callable[..., object]](
    function: Function, metadata: ToolFunctionMetadata
) -> Function:
    """Attach validated metadata without wrapping or changing function identity."""
    setattr(function, _TOOL_METADATA_ATTRIBUTE, ToolFunctionMetadata.model_validate(metadata))
    return function


def get_tool_metadata(function: Callable[..., object]) -> ToolFunctionMetadata:
    """Undeclared functions use signature inference and ordinary catalog visibility."""
    metadata = getattr(function, _TOOL_METADATA_ATTRIBUTE, None)
    if metadata is None:
        return _DEFAULT_METADATA
    return ToolFunctionMetadata.model_validate(metadata)
