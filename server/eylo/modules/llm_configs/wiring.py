"""Application dependency wiring for organization-scoped LLM configuration."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import current_transaction, get_transaction, start_transaction
from eylo.modules.llm_configs.domain import LLMOverrides, ResolvedLLM
from eylo.modules.llm_configs.resolver import LLMConfigResolver
from eylo.modules.llm_configs.service import LLMConfigReferences, LLMConfigService
from eylo.modules.provider_configs.crypto import get_secret_cipher
from eylo.modules.provider_configs.repository import ProviderConfigRepository
from eylo.modules.provider_configs.service import ProviderConfigService


def build_llm_config_service(
    db: AsyncSession | None = None,
    *,
    references: LLMConfigReferences | None = None,
) -> LLMConfigService:
    """Build an LLM config service for an explicit or active transaction."""
    session = db if db is not None else get_transaction()
    provider_configs = ProviderConfigService(
        ProviderConfigRepository(session, get_secret_cipher())
    )
    return LLMConfigService(provider_configs, references=references)


def build_llm_config_resolver(
    db: AsyncSession | None = None,
) -> LLMConfigResolver:
    """Build an LLM resolver for an explicit or active transaction."""
    return LLMConfigResolver(build_llm_config_service(db))


async def resolve_pinned_llm(
    organization_id: UUID,
    *,
    provider_config_id: UUID,
    revision: int,
    overrides: LLMOverrides | None = None,
) -> ResolvedLLM:
    """Return detached values; own a read scope only without a caller transaction.

    Reusing an active caller avoids a second checked-out connection. Its owner
    must end that transaction before external work; this function never commits
    or closes the caller's session.
    """
    session = current_transaction()
    if session is not None:
        return await build_llm_config_resolver(session).resolve_llm_pinned(
            organization_id,
            provider_config_id=provider_config_id,
            revision=revision,
            overrides=overrides,
        )
    async with start_transaction(ro=True) as session:
        return await build_llm_config_resolver(session).resolve_llm_pinned(
            organization_id,
            provider_config_id=provider_config_id,
            revision=revision,
            overrides=overrides,
        )
