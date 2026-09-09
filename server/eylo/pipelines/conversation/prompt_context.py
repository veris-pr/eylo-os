"""Prompt-only projections of hydrated conversation and recalled memory data."""

from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictBool,
    field_serializer,
)

from eylo.common.contracts.memory import MemoryLevel, MemoryRecall


class PromptContextValue(BaseModel):
    """Fixed projection fields; only customer context has an open JSON shape."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class PromptAgent(PromptContextValue):
    name: str
    description: str | None


class PromptInteraction(PromptContextValue):
    """Independent observed facts, not a replacement for the voice state machine."""

    voice: StrictBool
    phone: StrictBool
    widget: StrictBool


class PromptMemoryFact(PromptContextValue):
    id: UUID
    content: str


class PromptRecalledMemory(PromptMemoryFact):
    level: MemoryLevel


class PromptMemoryConflict(PromptContextValue):
    relationship_id: UUID
    level: MemoryLevel
    facts: tuple[PromptMemoryFact, PromptMemoryFact]


class PromptMemory(PromptContextValue):
    """Display evidence only; omits scope owners, vendor metadata and credentials."""

    facts: tuple[PromptRecalledMemory, ...]
    conflicts: tuple[PromptMemoryConflict, ...]


class ConversationPromptContext(PromptContextValue):
    current_time_utc: AwareDatetime
    agent: PromptAgent
    interaction: PromptInteraction
    memory: PromptMemory | None
    conversation_context: JsonValue

    @field_serializer("current_time_utc")
    def serialize_time(self, value: AwareDatetime) -> str:
        """Preserve the prompt's existing ISO timestamp including its UTC offset."""
        return value.isoformat()


def memory_prompt_from_recall(recall: MemoryRecall) -> PromptMemory | None:
    """Keep recall order and both conflict claims; never choose a winning fact."""
    if not recall.memories and not recall.conflicts:
        return None
    return PromptMemory(
        facts=tuple(
            PromptRecalledMemory(
                id=memory.id, level=memory.scope.level, content=memory.content
            )
            for memory in recall.memories
        ),
        conflicts=tuple(
            PromptMemoryConflict(
                relationship_id=conflict.relationship_id,
                level=conflict.facts[0].scope.level,
                facts=(
                    PromptMemoryFact(
                        id=conflict.facts[0].id, content=conflict.facts[0].content
                    ),
                    PromptMemoryFact(
                        id=conflict.facts[1].id, content=conflict.facts[1].content
                    ),
                ),
            )
            for conflict in recall.conflicts
        ),
    )
