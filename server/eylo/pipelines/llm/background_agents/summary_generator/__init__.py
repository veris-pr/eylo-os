"""Background context compaction, token estimates, and summary generation."""

from .agent import process_context_management_request
from .token_counter import (
    AnthropicTokenCounter,
    BedrockTokenCounter,
    ContextTokenCount,
    GeminiTokenCounter,
    OpenAITokenCounter,
    TokenCounter,
    get_token_counter,
)
from .utils import (
    MessageGroup,
    context_management_trigger,
    count_conversation_tokens,
    flatten_groups,
    get_max_tokens_for_model,
    group_messages_by_request,
    summarize_messages_with_llm,
)

__all__ = [
    # Agent
    "process_context_management_request",
    # Token Counting
    "TokenCounter",
    "ContextTokenCount",
    "OpenAITokenCounter",
    "AnthropicTokenCounter",
    "BedrockTokenCounter",
    "GeminiTokenCounter",
    "get_token_counter",
    # Utilities
    "MessageGroup",
    "count_conversation_tokens",
    "flatten_groups",
    "get_max_tokens_for_model",
    "group_messages_by_request",
    "context_management_trigger",
    "summarize_messages_with_llm",
]
