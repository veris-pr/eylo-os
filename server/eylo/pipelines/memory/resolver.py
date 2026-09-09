"""Compose explicit memory, embedding, and extraction-LLM authority."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.embedding import (
    DocumentEmbedder,
    EmbeddingError,
    EmbeddingSpace,
    QueryEmbedder,
)
from eylo.common.contracts.llm_runtime import LLMInferenceConfig
from eylo.common.contracts.memory import (
    MemoryError as MemoryProviderError,
)
from eylo.common.contracts.memory import (
    MemoryExtractionAuthority,
    MemoryTextCompleter,
)
from eylo.common.contracts.messages import MessageKind
from eylo.common.database import async_session_factory, get_transaction
from eylo.modules.agent_runs.budgets import (
    finish_current_memory_formation_execution,
    meter_current_execution_usage,
)
from eylo.modules.embedding_configs.domain import InvalidEmbeddingConfig
from eylo.modules.llm_configs.domain import LLMOverrides, ResolvedLLM
from eylo.modules.llm_configs.wiring import build_llm_config_resolver
from eylo.modules.memory.reindex_service import MemoryReindexService
from eylo.modules.memory_configs.catalog import MemoryProviders
from eylo.modules.memory_configs.domain import InvalidMemoryConfig, ResolvedMemory
from eylo.modules.memory_configs.wiring import build_memory_config_resolver
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.embedding.resolver import (
    EmbeddingRuntime,
    resolve_compatible_embedding_runtime,
    resolve_pinned_embedding_runtime,
)
from eylo.pipelines.llm.runtime import build_llm_adapter
from eylo.sockets.llm.transient import text_message, text_parts, tool_uses
from eylo.sockets.memory.base import MemoryVendorAdapter
from eylo.sockets.memory.extraction import EXTRACTION_PROMPT_REVISION
from eylo.sockets.memory.vendors.pgvector import PgVectorMemoryAdapter

_EXTRACTION_TIMEOUT_SECONDS = 15.0
_EXTRACTION_MAX_TOKENS = 1500
_EXTRACTION_TEMPERATURE = 0.0


class _DependencyRevisionMode(StrEnum):
    CURRENT = "current"
    PINNED = "pinned"


@dataclass(frozen=True)
class MemoryRuntime:
    authority: ResolvedMemory
    adapter: MemoryVendorAdapter
    embedding_space: EmbeddingSpace
    extraction_authority: MemoryExtractionAuthority
    reconciliation_completer: MemoryTextCompleter


async def resolve_memory_adapter(
    organization_id: UUID,
    db: AsyncSession | None = None,
    *,
    provider_config_id: UUID | None = None,
    provider_config_revision: int | None = None,
) -> MemoryVendorAdapter:
    """Build exactly the requested current or pinned memory adapter."""
    return (
        await resolve_memory_runtime(
            organization_id,
            db,
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
        )
    ).adapter


async def resolve_memory_runtime(
    organization_id: UUID,
    db: AsyncSession | None = None,
    *,
    provider_config_id: UUID | None = None,
    provider_config_revision: int | None = None,
    embedding_space: EmbeddingSpace | None = None,
) -> MemoryRuntime:
    """Build memory from explicit current or durable pinned authority."""
    resolver = build_memory_config_resolver(db)
    if provider_config_revision is None:
        resolved = await resolver.resolve(
            organization_id,
            provider_config_id=provider_config_id,
        )
        dependency_revision = _DependencyRevisionMode.CURRENT
    else:
        if provider_config_id is None:
            raise _memory_not_configured("provider_config")
        resolved = await resolver.resolve_pinned(
            organization_id,
            provider_config_id=provider_config_id,
            revision=provider_config_revision,
        )
        dependency_revision = _DependencyRevisionMode.PINNED

    if resolved.provider is not MemoryProviders.PGVECTOR:
        raise _memory_not_configured("supported_provider")

    embedding = await _embedding_runtime(
        organization_id,
        resolved,
        db,
        embedding_space=embedding_space,
    )
    llm = await _llm_runtime(
        organization_id,
        resolved,
        db,
        revision_mode=dependency_revision,
    )
    _validate_dependency_authority(resolved, llm)
    document_embedder, query_embedder = _embedding_functions(embedding)
    completer = build_memory_completer(llm)
    extraction_authority = MemoryExtractionAuthority(
        provider_config_id=llm.provider_config_id,
        provider_config_revision=llm.provider_config_revision,
        provider=llm.provider.value,
        model=llm.generation.model.value,
        prompt_revision=EXTRACTION_PROMPT_REVISION,
    )
    adapter = PgVectorMemoryAdapter(
        async_session_factory,
        document_embedder,
        query_embedder,
        completer,
        embedding.space,
        memory_provider_config_id=resolved.provider_config_id,
        memory_provider_config_revision=resolved.provider_config_revision,
        extraction_authority=extraction_authority,
        before_formation_commit=finish_current_memory_formation_execution,
    )
    return MemoryRuntime(
        authority=resolved,
        adapter=adapter,
        embedding_space=embedding.space,
        extraction_authority=extraction_authority,
        reconciliation_completer=completer,
    )


async def _embedding_runtime(
    organization_id: UUID,
    resolved: ResolvedMemory,
    db: AsyncSession | None,
    *,
    embedding_space: EmbeddingSpace | None,
) -> EmbeddingRuntime:
    if embedding_space is None:
        expected_space = await MemoryReindexService(
            db if db is not None else get_transaction()
        ).active_space(
            organization_id=organization_id,
            memory_provider_config_id=resolved.provider_config_id,
        )
    else:
        expected_space = embedding_space
    exact_revision = embedding_space is not None
    try:
        if embedding_space is not None:
            runtime = await resolve_pinned_embedding_runtime(
                organization_id,
                provider_config_id=embedding_space.provider_config_id,
                provider_config_revision=embedding_space.provider_config_revision,
                db=db,
            )
        else:
            runtime = await resolve_compatible_embedding_runtime(
                organization_id,
                persisted_space=expected_space,
                db=db,
            )
    except (InvalidEmbeddingConfig, NotConfiguredError):
        if exact_revision:
            raise MemoryProviderError(
                "Pinned memory embedding authority is unavailable."
            ) from None
        raise
    if not runtime.space.is_compatible_with(expected_space):
        raise MemoryProviderError(
            "Memory job embedding authority does not match its space."
        )
    return runtime


async def _llm_runtime(
    organization_id: UUID,
    resolved: ResolvedMemory,
    db: AsyncSession | None,
    *,
    revision_mode: _DependencyRevisionMode,
) -> ResolvedLLM:
    resolver = build_llm_config_resolver(db)
    overrides = memory_llm_overrides()
    if revision_mode is _DependencyRevisionMode.PINNED:
        return await resolver.resolve_llm_pinned(
            organization_id,
            provider_config_id=resolved.llm_provider_config_id,
            revision=resolved.llm_provider_config_revision,
            overrides=overrides,
        )
    return await resolver.resolve_llm(
        organization_id,
        provider_config_id=resolved.llm_provider_config_id,
        overrides=overrides,
    )


def memory_llm_overrides() -> LLMOverrides:
    """One extraction policy shared by verification and live composition."""
    return LLMOverrides(
        max_tokens=_EXTRACTION_MAX_TOKENS,
        temperature=_EXTRACTION_TEMPERATURE,
    )


def _embedding_functions(
    runtime: EmbeddingRuntime,
) -> tuple[DocumentEmbedder, QueryEmbedder]:
    async def embed_documents(texts: list[str]) -> list[list[float]]:
        try:
            return await runtime.embed_documents(texts)
        except EmbeddingError as error:
            raise MemoryProviderError(
                "Memory embedding failed.",
                vendor=error.vendor,
                retryable=error.retryable,
            ) from None

    async def embed_query(text: str) -> list[float]:
        try:
            return await runtime.embed_query(text)
        except EmbeddingError as error:
            raise MemoryProviderError(
                "Memory query embedding failed.",
                vendor=error.vendor,
                retryable=error.retryable,
            ) from None

    return embed_documents, embed_query


def build_memory_completer(llm: ResolvedLLM) -> MemoryTextCompleter:
    """Use the selected native LLM adapter for bounded extraction completion."""
    adapter = build_llm_adapter(llm)
    generation = LLMInferenceConfig(generation=llm.generation)

    async def complete(*, system: str, user: str) -> str:
        sender_id = uuid4()
        conversation_id = uuid4()
        try:
            async with asyncio.timeout(_EXTRACTION_TIMEOUT_SECONDS):
                response = await adapter.run_inference(
                    messages=[
                        text_message(
                            sender_id,
                            conversation_id,
                            MessageKind.USER,
                            user,
                        )
                    ],
                    system_prompt=system,
                    tools=[],
                    llm_config=generation,
                )
        except Exception as error:
            if isinstance(error, NotConfiguredError):
                raise
            raise MemoryProviderError(
                "Memory extraction provider failed.",
                vendor=llm.provider.value,
                retryable=True,
            ) from None
        usage = response.usage
        await meter_current_execution_usage(
            input_tokens=None if usage is None else usage.input_tokens,
            output_tokens=None if usage is None else usage.output_tokens,
        )
        if tool_uses(response.content):
            raise MemoryProviderError(
                "Memory extraction provider returned an unexpected tool call.",
                vendor=llm.provider.value,
            )
        content = "\n".join(text_parts(response.content)).strip()
        if not content:
            raise MemoryProviderError(
                "Memory extraction provider returned no text.",
                vendor=llm.provider.value,
            )
        return content

    return complete


def _validate_dependency_authority(
    memory: ResolvedMemory,
    llm: ResolvedLLM,
) -> None:
    metadata = memory.verification_metadata
    expected = {
        "llm_provider_config_id": str(llm.provider_config_id),
        "llm_provider_config_revision": llm.provider_config_revision,
        "llm_provider": llm.provider.value,
        "llm_model": llm.generation.model.value,
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise _memory_not_configured("reverify_dependencies")
    if memory.llm_provider_config_id != llm.provider_config_id:
        raise InvalidMemoryConfig(
            "Verified memory dependency identity does not match its config."
        )


def _memory_not_configured(missing: str) -> NotConfiguredError:
    return NotConfiguredError(
        capability=Capability.MEMORY,
        missing=[missing],
        configure_via="/api/memory-configs",
    )
