"""Assemble canonical tool calls and serialize tool results without vendor SDKs."""

import json
import math
from typing import Never

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from eylo.common.utils.toon_serde import toon_encode
from eylo.sockets.llm.schemas import LLMToolContent, LLMToolUseBlock

_TOOL_INPUT = TypeAdapter(dict[str, JsonValue])


class ToolCallAssemblyError(ValueError):
    """A tool call cannot safely become executable; payloads are never retained."""


def _reject_json_constant(_: str) -> Never:
    raise ToolCallAssemblyError("Tool input must contain finite JSON numbers")


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ToolCallAssemblyError("Tool input must contain finite JSON numbers")
    return number


class ToolCallBuffer(BaseModel):
    """Buffer function arguments; the vendor owns indexing and terminal validation."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, hide_input_in_errors=True
    )

    id: str = ""
    name: str = ""
    arguments: str = Field(default="", repr=False)

    def append(
        self, *, call_id: str | None, name: str | None, arguments: str | None
    ) -> None:
        if call_id:
            if self.id and self.id != call_id:
                raise ToolCallAssemblyError("Tool call identity changed")
            self.id = call_id
        if name:
            if self.name and self.name != name:
                raise ToolCallAssemblyError("Tool call name changed")
            self.name = name
        if arguments is not None:
            self.arguments += arguments

    def to_block(self) -> LLMToolContent:
        if not self.id.strip() or not self.name.strip():
            raise ToolCallAssemblyError("Tool call identity is missing")
        try:
            decoded: object = json.loads(
                self.arguments,
                parse_constant=_reject_json_constant,
                parse_float=_finite_json_float,
            )
            arguments = _TOOL_INPUT.validate_python(decoded, strict=True)
        except ValueError:
            raise ToolCallAssemblyError(
                "Tool input must be a finite JSON object"
            ) from None
        return LLMToolContent(
            id=self.id,
            content=LLMToolUseBlock(id=self.id, name=self.name, input=arguments),
        )


def complete_tool_calls(calls: list[ToolCallBuffer]) -> list[LLMToolContent]:
    """After vendor terminal validation, validate the whole batch before exposing it."""
    if len({call.id for call in calls}) != len(calls):
        raise ToolCallAssemblyError("Tool call identity is duplicated")
    return [call.to_block() for call in calls]


def serialize_tool_content(content: object) -> str:
    """Preserve text and the existing TOON encoding without importing a vendor SDK."""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return toon_encode(content)
    return str(content)
