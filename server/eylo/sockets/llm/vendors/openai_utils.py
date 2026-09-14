"""Shared utilities for OpenAI vendor adapters.

Chat Completions, Responses, and realtime share function-schema projection.
Only the HTTP adapters use the client helper; realtime owns its WebSocket.
Tool-result serialization lives in the vendor-neutral llm/tool_content.py module.
"""

import logging
from collections.abc import Sequence

from openai import AsyncOpenAI
from openai.types.shared_params import FunctionDefinition
from pydantic import JsonValue, TypeAdapter

from eylo.common.contracts.tool_platform import PlatformTool
from eylo.common.contracts.tool_record import ToolRecord

logger = logging.getLogger(__name__)


def create_openai_client(api_key: str) -> AsyncOpenAI:
    """Build an authenticated client from explicitly resolved credentials."""
    return AsyncOpenAI(api_key=api_key)


_SCHEMA = TypeAdapter(dict[str, JsonValue])
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}
)
_SCHEMA_LIST_KEYWORDS = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})
_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "items",
        "additionalProperties",
        "contains",
        "not",
        "if",
        "then",
        "else",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
    }
)


def ensure_strict_mode_schema(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Close every object schema without mutating input or rewriting annotation data."""
    result: dict[str, JsonValue] = {}
    for key, value in schema.items():
        if key in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            result[key] = {
                name: ensure_strict_mode_schema(child)
                if isinstance(child, dict)
                else child
                for name, child in value.items()
            }
        elif key in _SCHEMA_LIST_KEYWORDS and isinstance(value, list):
            result[key] = [
                ensure_strict_mode_schema(child) if isinstance(child, dict) else child
                for child in value
            ]
        elif key in _SCHEMA_SINGLE_KEYWORDS and isinstance(value, dict):
            result[key] = ensure_strict_mode_schema(value)
        else:
            result[key] = value
    schema_type = result.get("type")
    if schema_type == "object" or (
        isinstance(schema_type, list) and "object" in schema_type
    ):
        result["additionalProperties"] = False
        properties = result.get("properties")
        if not isinstance(properties, dict):
            properties = {}
            result["properties"] = properties
        # OpenAI requires all properties. Preserve declared nullable unions/types;
        # do not invent nullability for non-nullable platform inputs.
        result["required"] = list(properties)
    return result


def extract_openai_function_declarations(
    tools: Sequence[ToolRecord],
) -> list[FunctionDefinition]:
    """Project tool schemas without modifying the canonical platform definitions.

    Callers own their API-specific wrapper and strict flag. Unconfigured or
    malformed tools retain the existing skip-and-log behavior; logs omit inputs.
    """
    declarations: list[FunctionDefinition] = []

    for tool in tools:
        try:
            if not tool.llm_config:
                logger.warning("Tool %s has no llm_config, skipping", tool.id)
                continue

            platform_tool = tool.llm_config
            if not isinstance(platform_tool, PlatformTool):
                logger.error(
                    "Unexpected llm_config type for tool %s: %s",
                    tool.id,
                    type(tool.llm_config),
                )
                continue

            input_schema = ensure_strict_mode_schema(
                _SCHEMA.validate_python(
                    platform_tool.input_schema.to_json_schema(), strict=True
                )
            )
            parameters: dict[str, object] = dict(input_schema)
            declarations.append(
                {
                    "name": platform_tool.name,
                    "description": platform_tool.description,
                    "parameters": parameters,
                }
            )
        except Exception as error:
            logger.error(
                "Tool transformation failed tool=%s error_type=%s",
                tool.id,
                type(error).__name__,
            )
            continue

    return declarations
