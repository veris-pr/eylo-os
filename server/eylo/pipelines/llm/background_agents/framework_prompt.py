"""Resolved-provider prompt runner for lightweight background agents."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.llm_response import LLMStopReason
from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.framework.agents.errors import ModelOutputLimitError
from eylo.modules.agent_runs.budgets import meter_current_agent_run_usage
from eylo.modules.agents.models import AgentStatus
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.messages import MessageKind
from eylo.modules.llm_configs.domain import LLMOverrides, ResolvedLLM
from eylo.modules.llm_configs.resolver import LLMConfigResolver
from eylo.modules.llm_configs.wiring import build_llm_config_resolver
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.sockets.llm import LLMContentType, LLMFactory, LLMResponse
from eylo.sockets.llm.transient import text_message

logger = logging.getLogger(__name__)


class BackgroundPrompt(BaseModel):
    """One instruction and user-text input; not a vendor message envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    system_prompt: str = Field(repr=False, exclude=True)
    user_content: str = Field(repr=False, exclude=True)


class BackgroundPromptResult(BaseModel):
    """Sanitized output metadata from one background LLM request."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    text: str = Field(repr=False)
    model: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


async def resolve_background_agent(
    agent: AgentInDb,
    *,
    generation_overrides: LLMOverrides | None = None,
    resolver: LLMConfigResolver | None = None,
) -> ResolvedLLM:
    """Resolve one agent config with optional job-specific generation limits."""
    if agent.status is not AgentStatus.ACTIVE:
        raise NotConfiguredError(
            capability=Capability.LLM,
            missing=["published_agent"],
            configure_via=f"/api/agents/{agent.id}",
        )
    if (
        agent.llm_provider_config_id is None
        or agent.llm_provider_config_revision is None
    ):
        raise NotConfiguredError(
            capability=Capability.LLM,
            missing=["provider_config", "provider_config_revision"],
            configure_via=f"/api/agents/{agent.id}",
        )
    effective_overrides = agent.llm_overrides.model_dump(exclude_none=True)
    if generation_overrides is not None:
        effective_overrides.update(generation_overrides.to_storage())
    if resolver is None:
        resolver = build_llm_config_resolver()
    return await resolver.resolve_llm_pinned(
        agent.organization_id,
        provider_config_id=agent.llm_provider_config_id,
        revision=agent.llm_provider_config_revision,
        overrides=effective_overrides,
    )


async def run_background_prompt_agent(
    *,
    agent_name: str,
    prompt: BackgroundPrompt,
    sender_id: UUID,
    conversation_id: UUID,
    resolved: ResolvedLLM,
) -> BackgroundPromptResult | None:
    """Run a one-shot prompt through the agent's resolved native adapter."""
    adapter = LLMFactory.from_resolved(resolved).adapter
    response = await adapter.run_inference(
        messages=[
            text_message(
                sender_id,
                conversation_id,
                MessageKind.USER,
                prompt.user_content,
            )
        ],
        system_prompt=prompt.system_prompt,
        tools=[],
        llm_config=LLMInferenceConfig(generation=resolved.generation),
    )
    usage = response.usage
    await meter_current_agent_run_usage(
        input_tokens=None if usage is None else usage.input_tokens,
        output_tokens=None if usage is None else usage.output_tokens,
    )
    result = _result_from_response(response)
    if result is None:
        logger.warning("Background agent %s returned no text", agent_name)
    return result


def _result_from_response(response: LLMResponse) -> BackgroundPromptResult | None:
    if response.stop_reason is LLMStopReason.MAX_TOKENS:
        raise ModelOutputLimitError
    text = next(
        (
            block.content.text
            for block in response.content
            if block.type == LLMContentType.TEXT
        ),
        None,
    )
    if not text or not text.strip():
        return None
    usage = response.usage
    return BackgroundPromptResult(
        text=text.strip(),
        model=response.model,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
    )
