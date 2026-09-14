"""Application services for the `agents` domain."""

import json
from collections.abc import Sequence
from enum import StrEnum
from typing import ClassVar, Final, TypeVar

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from eylo.modules.tools.models import ToolExecutionMode, ToolKind
from eylo.modules.tools.schemas.indb import ToolInDb

ToolContextT = TypeVar("ToolContextT")
type ToolExecutionResult = str | dict[str, JsonValue] | list[JsonValue]

_JSON_RESULT = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))
_MAX_VALIDATION_FIELD_PATHS: Final = 8


class ToolDispatchCode(StrEnum):
    """Stable machine-readable outcomes; messages never include rejected values."""

    FAILED = "tool_dispatch_failed"
    NOT_FOUND = "tool_not_found"
    AMBIGUOUS_NAME = "ambiguous_tool_name"
    EXECUTION_BLOCKED = "tool_execution_blocked"
    APPROVAL_REQUIRED = "tool_approval_required"
    EXECUTOR_UNAVAILABLE = "tool_executor_unavailable"
    INVALID_INPUT = "invalid_tool_input"


class ToolDispatchError(RuntimeError):
    """Base failure for exact model-name resolution or stored dispatch policy."""

    code: ClassVar[ToolDispatchCode] = ToolDispatchCode.FAILED
    safe_message = "Tool dispatch failed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class ModelToolNotFoundError(ToolDispatchError):
    """The model requested a name absent from its exact filed tool list."""

    code = ToolDispatchCode.NOT_FOUND
    safe_message = "Requested tool is not available."


class AmbiguousModelToolNameError(ToolDispatchError):
    """More than one filed tool advertises the same model-visible name."""

    code = ToolDispatchCode.AMBIGUOUS_NAME
    safe_message = "Requested tool identity is ambiguous."


class ToolExecutionBlockedError(ToolDispatchError):
    """Stored policy forbids executing this exact tool revision."""

    code = ToolDispatchCode.EXECUTION_BLOCKED
    safe_message = "Tool execution is disabled by policy."


class ToolApprovalRequiredError(ToolDispatchError):
    """Stored policy requires a durable approval before execution."""

    code = ToolDispatchCode.APPROVAL_REQUIRED
    safe_message = "Tool execution requires approval."


class ToolExecutorNotFoundError(ToolDispatchError):
    """The exact stored tool kind has no matching runtime executor."""

    code = ToolDispatchCode.EXECUTOR_UNAVAILABLE
    safe_message = "Tool executor is unavailable."


class ToolInputValidationError(ToolDispatchError):
    """Tool input failed schema validation without retaining rejected values."""

    code = ToolDispatchCode.INVALID_INPUT

    def __init__(self, field_paths: tuple[str, ...]) -> None:
        self.field_paths = field_paths
        fields = ", ".join(field_paths) if field_paths else "input"
        RuntimeError.__init__(self, f"Invalid tool input for field(s): {fields}.")


def resolve_model_tool(
    tools: Sequence[ToolInDb],
    model_name: str,
) -> ToolInDb:
    """Resolve only the exact name advertised to the model for this run."""
    matches = [
        tool for tool in tools if tool.llm_config and tool.llm_config.name == model_name
    ]
    if not matches:
        raise ModelToolNotFoundError()
    if len(matches) > 1:
        raise AmbiguousModelToolNameError()
    return matches[0]


def require_tool_execution_allowed(tool: ToolInDb) -> None:
    """Enforce the immutable policy stored on this exact tool revision."""
    if tool.execution_mode is ToolExecutionMode.DISABLED:
        raise ToolExecutionBlockedError()
    if tool.execution_mode is ToolExecutionMode.REQUIRES_APPROVAL:
        raise ToolApprovalRequiredError()


async def execute_exact_tool(
    tool: ToolInDb,
    tool_input: dict[str, JsonValue],
    ctx: ToolContextT,
) -> ToolExecutionResult:
    """Forward caller-owned context unchanged after enforcing exact tool policy.

    Context is opaque to this registry dispatcher; the registered callable owns
    its requirements. Do not manufacture a conversation for non-conversation runs.
    """
    require_tool_execution_allowed(tool)

    if tool.kind in (ToolKind.SYSTEM, ToolKind.LOCAL):
        from eylo.modules.tools.services.tool_register import (
            build_fn_declaration,
            local_tools_registry,
            system_tools_registry,
        )

        registry = (
            system_tools_registry
            if tool.kind is ToolKind.SYSTEM
            else local_tools_registry
        )
        tool_fn = registry.registered_tools.get(tool.slug)
        if tool_fn is None:
            raise ToolExecutorNotFoundError()
        declaration = build_fn_declaration(tool_fn)
        try:
            validated = declaration.model_validate(tool_input)
        except ValidationError as error:
            raise ToolInputValidationError(
                _validation_field_paths(error, declaration)
            ) from None
        result = await tool_fn(**validated.model_dump(), ctx=ctx)
        return _normalize_tool_result(result)

    if tool.kind is ToolKind.MCP:
        raise ToolExecutorNotFoundError()

    raise ToolExecutorNotFoundError()


def _normalize_tool_result(value: object) -> ToolExecutionResult:
    """Keep the agent-loop boundary stable for every valid JSON result."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            result = _JSON_RESULT.validate_python(value)
        except ValidationError:
            raise TypeError("Tool returned a result that is not valid JSON.") from None
        if isinstance(result, (dict, list)):
            return result
    if value is None or isinstance(value, (bool, int, float)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    raise TypeError(f"Tool returned unsupported result type {type(value).__name__}.")


def _validation_field_paths(
    error: ValidationError,
    declaration: type[BaseModel],
) -> tuple[str, ...]:
    """Return bounded schema-owned field names without rejected input values."""
    declared_fields = declaration.model_fields.keys()
    paths: list[str] = []
    for detail in error.errors(include_input=False, include_url=False):
        location = detail.get("loc") or ()
        field = location[0] if location else None
        safe_field = (
            field if isinstance(field, str) and field in declared_fields else "input"
        )
        if safe_field not in paths:
            paths.append(safe_field)
        if len(paths) == _MAX_VALIDATION_FIELD_PATHS:
            break
    return tuple(paths)
