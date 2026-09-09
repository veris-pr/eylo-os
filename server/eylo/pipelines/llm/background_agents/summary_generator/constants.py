"""Context-compaction triggers and existing background-generation limits."""

from enum import Enum
from typing import Final

from eylo.modules.llm_configs.domain import LLMOverrides


class ContextManagementTrigger(str, Enum):
    """Why compaction should run; not a persisted message or task state."""

    NOT_REQUIRED = "not_required"
    TOKENS = "tokens"
    GROUPS = "groups"


DEFAULT_TOKEN_THRESHOLD: Final = 0.7
DEFAULT_GROUP_THRESHOLD: Final = 20
DEFAULT_RECENT_GROUPS: Final = 5
SUMMARY_GENERATION_OVERRIDES: Final = LLMOverrides(max_tokens=2000, temperature=0.3)
FALLBACK_CHARACTERS_PER_TOKEN: Final = 4
