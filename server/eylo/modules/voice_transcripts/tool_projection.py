"""Project validated conversation tool content into transcript-owned fields."""

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.message_content import (
    ToolResultMessageContent,
    ToolUseMessageContent,
)
from eylo.common.contracts.messages import MessageInDb, MessageKind


class TranscriptToolFields(BaseModel):
    """Keep the persisted first-tool projection without exposing raw values in repr."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    name: str | None = None
    call_id: str | None = None
    input: JsonObject | None = Field(default=None, repr=False)
    output: JsonObject | None = Field(default=None, repr=False)

    @classmethod
    def from_message(cls, message: MessageInDb) -> "TranscriptToolFields":
        """Use canonical content types; absent tool results retain their null envelope."""
        content = message.content
        if message.kind is MessageKind.TOOL_USE and isinstance(
            content, ToolUseMessageContent
        ):
            item = content.content
            return cls(name=item.name, call_id=item.id, input=item.input)
        if message.kind is MessageKind.TOOL_RESULT:
            if isinstance(content, ToolResultMessageContent) and content.content:
                result = content.content[0]
                return cls(
                    name=result.name,
                    call_id=result.tool_use_id,
                    output={"content": result.content, "is_error": result.is_error},
                )
            return cls(output={"content": None, "is_error": None})
        return cls()
