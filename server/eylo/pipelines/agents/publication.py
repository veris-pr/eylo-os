"""Atomic publication of an Agent definition plus product-owned snapshots."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.agents.domain import InvalidAgentDefinitionError
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.agents.services.indb import AgentService
from eylo.modules.agents.services.revisions import AgentRevisionService
from eylo.sor.shared.grant_services import (
    SorGrantPublicationError,
    SorSourceGrantService,
)


async def publish_agent_definition(
    *,
    session: AsyncSession,
    organization_id: UUID,
    agent_id: UUID,
    expected_draft_version: int,
    actor_id: UUID | None,
) -> AgentInDb:
    """Publish core Agent state and SOR authority in the same DB transaction."""
    revision = await AgentRevisionService(session).publish(
        organization_id=organization_id,
        agent_id=agent_id,
        expected_draft_version=expected_draft_version,
        actor_id=actor_id,
    )
    try:
        await SorSourceGrantService(session).snapshot_agent_revision(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_revision=revision.revision,
        )
    except SorGrantPublicationError as error:
        raise InvalidAgentDefinitionError(str(error)) from error
    return await AgentService(session).get_by_organization_and_id(
        organization_id,
        agent_id,
    )


__all__ = ["publish_agent_definition"]
