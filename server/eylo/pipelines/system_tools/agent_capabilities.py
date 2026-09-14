"""Resolve provider-backed capabilities bound to one agent.

This pipeline owns the cross-module composition. A ready email config somewhere
in the organization does not make an agent's different, disabled email binding
usable. Every fact below follows the exact config and revision that the agent
relationship will execute.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.provider_config import Capability
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.provider_configs.crypto import (
    SecretDecryptionError,
    get_secret_cipher,
)
from eylo.modules.provider_configs.repository import ProviderConfigRepository
from eylo.modules.sandbox.models import SandboxGrantModel
from eylo.modules.telephony.repositories import PhoneNumberRepository

ProviderRef = tuple[UUID | None, int | None]


async def resolve_agent_tool_capabilities(
    session: AsyncSession,
    agent: AgentInDb,
    *,
    provider_refs: Mapping[Capability, ProviderRef] | None = None,
) -> frozenset[Capability]:
    """Return capabilities backed by this agent's exact active relationships."""
    organization_id = agent.organization_id
    if organization_id is None:
        raise ValueError("Agent tool capabilities require an organization.")
    agent_id = agent.id
    repository = ProviderConfigRepository(session, get_secret_cipher())
    available: set[Capability] = set()

    configured_refs: dict[Capability, ProviderRef] = {
        Capability.EMAIL: (
            agent.email_provider_config_id,
            agent.email_provider_config_revision,
        ),
        Capability.MEMORY: (
            agent.memory_provider_config_id,
            agent.memory_provider_config_revision,
        ),
    }
    for capability, configured_ref in configured_refs.items():
        config_id, revision = (
            provider_refs.get(capability, configured_ref)
            if provider_refs is not None
            else configured_ref
        )
        if await _is_verified_exact(
            repository,
            organization_id=organization_id,
            capability=capability,
            config_id=config_id,
            revision=revision,
        ):
            available.add(capability)

    phone_number = await PhoneNumberRepository(session).get_active_by_outbound_agent_id(
        organization_id=organization_id,
        outbound_agent_id=agent_id,
    )
    if phone_number is not None and await _is_verified_exact(
        repository,
        organization_id=organization_id,
        capability=Capability.TELEPHONY,
        config_id=phone_number.provider_config_id,
        revision=phone_number.provider_config_revision,
    ):
        available.add(Capability.TELEPHONY)

    grant = await session.scalar(
        select(SandboxGrantModel).where(
            SandboxGrantModel.organization_id == organization_id,
            SandboxGrantModel.agent_id == agent_id,
            SandboxGrantModel.deleted.is_(False),
        )
    )
    if grant is not None and await _is_verified_exact(
        repository,
        organization_id=organization_id,
        capability=Capability.SANDBOX,
        config_id=grant.sandbox_provider_config_id,
        revision=grant.sandbox_provider_config_revision,
    ):
        available.add(Capability.SANDBOX)

    return frozenset(available)


async def _is_verified_exact(
    repository: ProviderConfigRepository,
    *,
    organization_id: UUID,
    capability: Capability,
    config_id: UUID | None,
    revision: int | None,
) -> bool:
    if config_id is None or revision is None:
        return False
    try:
        config = await repository.get_revision(
            organization_id,
            UUID(str(config_id)),
            int(revision),
        )
    except SecretDecryptionError:
        return False
    return bool(
        config is not None
        and config.capability is capability
        and config.configured
        and config.verified
    )


__all__ = ["ProviderRef", "resolve_agent_tool_capabilities"]
