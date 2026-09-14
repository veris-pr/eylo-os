"""Composition seam between platform modules and the concrete LLM runtime."""

from enum import StrEnum
from typing import assert_never

from eylo.common.contracts.llm_runtime import LLMPromptCaching
from eylo.framework.agents.config import RunPromptCaching, RunStreaming
from eylo.modules.llm_configs.domain import ResolvedLLM
from eylo.pipelines.llm.background_agents.framework_prompt import (
    BackgroundPrompt,
    BackgroundPromptResult,
    resolve_background_agent,
    run_background_prompt_agent,
)
from eylo.sockets.llm import LLMFactory
from eylo.sockets.llm.base import LLMVendorAdapter
from eylo.sockets.llm.transient import (
    response_messages,
    text_message,
    text_parts,
    tool_result_messages,
    tool_uses,
)


class LLMInferenceMode(StrEnum):
    """Select the adapter entrypoint without changing provider generation settings."""

    SINGLE_RESPONSE = "single_response"
    STREAMING = "streaming"


def to_llm_prompt_caching(mode: RunPromptCaching) -> LLMPromptCaching:
    """Translate the framework choice without boolean or cross-enum coercion."""
    match mode:
        case RunPromptCaching.ENABLED:
            return LLMPromptCaching.ENABLED
        case RunPromptCaching.DISABLED:
            return LLMPromptCaching.DISABLED
        case _:
            assert_never(mode)


def to_llm_inference_mode(mode: RunStreaming) -> LLMInferenceMode:
    """Translate framework delivery into the platform adapter entrypoint."""
    match mode:
        case RunStreaming.ENABLED:
            return LLMInferenceMode.STREAMING
        case RunStreaming.DISABLED:
            return LLMInferenceMode.SINGLE_RESPONSE
        case _:
            assert_never(mode)


def build_llm_adapter(resolved: ResolvedLLM) -> LLMVendorAdapter:
    """Construct the concrete adapter for one fully resolved org config."""
    return LLMFactory.from_resolved(resolved).adapter


__all__ = [
    "BackgroundPrompt",
    "BackgroundPromptResult",
    "LLMInferenceMode",
    "build_llm_adapter",
    "resolve_background_agent",
    "response_messages",
    "run_background_prompt_agent",
    "text_message",
    "text_parts",
    "tool_result_messages",
    "tool_uses",
    "to_llm_inference_mode",
    "to_llm_prompt_caching",
]
