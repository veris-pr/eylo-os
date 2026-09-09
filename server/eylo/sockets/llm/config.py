"""Validation shared by LLM vendor adapters at their public boundary."""

from eylo.common.contracts.llm_runtime import InvalidLLMConfig, LLMInferenceConfig


def require_model(config: LLMInferenceConfig) -> str:
    """Return one explicit model name; vendor adapters never select a model."""
    return config.generation.model.value


def require_max_tokens(config: LLMInferenceConfig) -> int:
    """Return an explicit output-token limit for providers that require one."""
    value = config.generation.max_tokens
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidLLMConfig(
            "LLM max_tokens must be configured explicitly for this provider."
        )
    return value


def configured_generation_params(
    config: LLMInferenceConfig,
    *,
    max_tokens_parameter: str,
    stop_sequences_parameter: str | None,
    top_k_parameter: str | None = None,
) -> dict[str, int | float | list[str]]:
    """Translate only operator-supplied generation settings for one vendor."""
    generation = config.generation
    values: dict[str, int | float | list[str]] = {}
    if generation.max_tokens is not None:
        values[max_tokens_parameter] = generation.max_tokens
    if generation.temperature is not None:
        values["temperature"] = generation.temperature
    if generation.top_p is not None:
        values["top_p"] = generation.top_p
    if top_k_parameter is not None and generation.top_k is not None:
        values[top_k_parameter] = generation.top_k
    if stop_sequences_parameter is not None and generation.stop_sequences is not None:
        values[stop_sequences_parameter] = list(generation.stop_sequences)
    return values


__all__ = [
    "configured_generation_params",
    "require_max_tokens",
    "require_model",
]
