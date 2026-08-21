"""Resolve exact published Agent, tool, and live source authority for SOR work."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.revisions import RevisionAvailability
from eylo.modules.agents.models import AgentRevisionModel, AgentRevisionToolModel
from eylo.modules.connections.domain import (
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.models import ExternalConnectionModel
from eylo.modules.tools.services.tool_register import system_tool_id
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorFieldMappingState,
    SorMappingState,
    SorProfile,
    SorSourceAccess,
    SorSourceState,
    SorToolEffect,
    SorToolSpec,
)
from eylo.sor.shared.models import (
    SorAgentRevisionSourceGrantModel,
    SorFieldMappingModel,
    SorMappingRevisionModel,
    SorSourceGrantModel,
    SorSourceModel,
    SorSourceStreamModel,
)


class SorAuthorityError(Exception):
    """A safe refusal that does not reveal unavailable source identities."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AuthorizedSorSource:
    """Immutable facts an Agent read or command may use after authorization."""

    source_id: UUID
    name: str
    profile: SorProfile
    vendor_key: str
    access: SorSourceAccess
    active_mapping_revision_id: UUID
    config_revision: int
    freshness_target_seconds: int
    last_successful_sync_at: datetime | None


def resolve_profile_tool(
    *,
    registry: SorRegistry,
    profile: SorProfile,
    tool_name: str,
    effect: SorToolEffect | None = None,
    entity: str | None = None,
) -> SorToolSpec:
    """Resolve one explicit profile tool and validate its declared scope."""
    tool = next(
        (
            candidate
            for candidate in registry.get_profile(profile).tools
            if candidate.name == tool_name
        ),
        None,
    )
    if tool is None or (effect is not None and tool.effect is not effect):
        raise SorAuthorityError(
            "SOR_TOOL_UNAVAILABLE",
            "The requested source tool is unavailable.",
        )
    if entity is not None and entity not in tool.target_entities:
        raise SorAuthorityError(
            "SOR_TOOL_ENTITY_UNAVAILABLE",
            "The requested source tool cannot target this entity.",
        )
    return tool


async def resolve_agent_sources(
    session: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    profile: SorProfile,
    tool_name: str,
    requested_source_ids: Sequence[UUID] = (),
    effect: SorToolEffect | None = None,
    entity: str | None = None,
    registry: SorRegistry | None = None,
) -> tuple[AuthorizedSorSource, ...]:
    """Resolve sources only when revision, tool, snapshot, and live grant agree."""
    resolved_registry = registry or get_sor_registry()
    tool = resolve_profile_tool(
        registry=resolved_registry,
        profile=profile,
        tool_name=tool_name,
        effect=effect,
        entity=entity,
    )
    await _require_published_revision_tool(
        session,
        organization_id=organization_id,
        agent_id=agent_id,
        agent_revision=agent_revision,
        tool_name=tool.name,
    )

    predicates = [
        SorAgentRevisionSourceGrantModel.organization_id == organization_id,
        SorAgentRevisionSourceGrantModel.agent_id == agent_id,
        SorAgentRevisionSourceGrantModel.agent_revision == agent_revision,
        SorAgentRevisionSourceGrantModel.deleted.is_(False),
        SorSourceGrantModel.deleted.is_(False),
        SorSourceGrantModel.access == SorAgentRevisionSourceGrantModel.access,
        SorSourceModel.organization_id == organization_id,
        SorSourceModel.profile == profile,
        SorSourceModel.state.in_((SorSourceState.ACTIVE, SorSourceState.DEGRADED)),
        SorSourceModel.deleted.is_(False),
        SorMappingRevisionModel.state == SorMappingState.ACTIVE,
        SorMappingRevisionModel.deleted.is_(False),
        ExternalConnectionModel.owner_kind == ConnectionOwnerKind.ORGANIZATION,
        ExternalConnectionModel.status == ExternalConnectionStatus.ACTIVE,
        ExternalConnectionModel.deleted.is_(False),
    ]
    if tool.effect is SorToolEffect.MUTATION:
        predicates.extend(
            (
                SorAgentRevisionSourceGrantModel.access
                == SorSourceAccess.READ_WRITE,
                SorSourceGrantModel.access == SorSourceAccess.READ_WRITE,
            )
        )
    requested = tuple(dict.fromkeys(requested_source_ids))
    if requested:
        predicates.append(SorSourceModel.id.in_(requested))
    if entity is not None:
        predicates.append(
            select(SorFieldMappingModel.id)
            .join(
                SorSourceStreamModel,
                and_(
                    SorSourceStreamModel.organization_id
                    == SorFieldMappingModel.organization_id,
                    SorSourceStreamModel.source_id
                    == SorFieldMappingModel.source_id,
                    SorSourceStreamModel.vendor_object_key
                    == SorFieldMappingModel.vendor_object_key,
                ),
            )
            .where(
                SorFieldMappingModel.organization_id == organization_id,
                SorFieldMappingModel.source_id == SorSourceModel.id,
                SorFieldMappingModel.mapping_revision_id
                == SorSourceModel.active_mapping_revision_id,
                SorSourceStreamModel.canonical_entity_kind == entity,
                SorSourceStreamModel.deleted.is_(False),
                SorFieldMappingModel.agent_visible.is_(True),
                SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
                SorFieldMappingModel.deleted.is_(False),
            )
            .exists()
        )

    rows = (
        await session.execute(
            select(
                SorAgentRevisionSourceGrantModel,
                SorSourceGrantModel,
                SorSourceModel,
            )
            .join(
                SorSourceGrantModel,
                and_(
                    SorSourceGrantModel.id
                    == SorAgentRevisionSourceGrantModel.source_grant_id,
                    SorSourceGrantModel.source_id
                    == SorAgentRevisionSourceGrantModel.source_id,
                    SorSourceGrantModel.organization_id
                    == SorAgentRevisionSourceGrantModel.organization_id,
                    SorSourceGrantModel.agent_id
                    == SorAgentRevisionSourceGrantModel.agent_id,
                    SorSourceGrantModel.revision
                    == SorAgentRevisionSourceGrantModel.source_grant_revision,
                ),
            )
            .join(
                SorSourceModel,
                and_(
                    SorSourceModel.id
                    == SorAgentRevisionSourceGrantModel.source_id,
                    SorSourceModel.organization_id
                    == SorAgentRevisionSourceGrantModel.organization_id,
                ),
            )
            .join(
                SorMappingRevisionModel,
                and_(
                    SorMappingRevisionModel.id
                    == SorSourceModel.active_mapping_revision_id,
                    SorMappingRevisionModel.source_id == SorSourceModel.id,
                    SorMappingRevisionModel.organization_id
                    == SorSourceModel.organization_id,
                ),
            )
            .join(
                ExternalConnectionModel,
                and_(
                    ExternalConnectionModel.id
                    == SorSourceModel.external_connection_id,
                    ExternalConnectionModel.organization_id
                    == SorSourceModel.organization_id,
                    ExternalConnectionModel.vendor_key == SorSourceModel.vendor_key,
                ),
            )
            .where(*predicates)
            .order_by(SorSourceModel.name.asc(), SorSourceModel.id.asc())
        )
    ).all()
    authorized_rows = []
    for revision_grant, live_grant, source in rows:
        try:
            manifest = resolved_registry.get_manifest(
                profile=source.profile,
                vendor_key=source.vendor_key,
            )
        except KeyError:
            continue
        executable_tools = (
            manifest.readable_tools
            if tool.effect is SorToolEffect.READ
            else manifest.writable_tools
        )
        if tool.name in executable_tools:
            authorized_rows.append((revision_grant, live_grant, source))

    if requested and {source.id for _, _, source in authorized_rows} != set(requested):
        raise SorAuthorityError(
            "SOR_SOURCE_UNAVAILABLE",
            "One or more requested sources are unavailable.",
        )
    return tuple(
        AuthorizedSorSource(
            source_id=source.id,
            name=source.name,
            profile=source.profile,
            vendor_key=source.vendor_key,
            access=revision_grant.access,
            active_mapping_revision_id=source.active_mapping_revision_id,
            config_revision=source.config_revision,
            freshness_target_seconds=source.freshness_target_seconds,
            last_successful_sync_at=source.last_successful_sync_at,
        )
        for revision_grant, _live_grant, source in authorized_rows
    )


async def _require_published_revision_tool(
    session: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    tool_name: str,
) -> None:
    revision = await session.scalar(
        select(AgentRevisionModel.id).where(
            AgentRevisionModel.organization_id == organization_id,
            AgentRevisionModel.agent_id == agent_id,
            AgentRevisionModel.revision == agent_revision,
            AgentRevisionModel.availability == RevisionAvailability.PUBLISHED.value,
            AgentRevisionModel.deleted.is_(False),
        )
    )
    if revision is None:
        raise SorAuthorityError(
            "AGENT_REVISION_UNAVAILABLE",
            "The pinned Agent revision cannot access source data.",
        )
    revision_tool = await session.scalar(
        select(AgentRevisionToolModel.id).where(
            AgentRevisionToolModel.organization_id == organization_id,
            AgentRevisionToolModel.agent_id == agent_id,
            AgentRevisionToolModel.agent_revision == agent_revision,
            AgentRevisionToolModel.tool_id
            == system_tool_id(tool_name, organization_id),
            AgentRevisionToolModel.deleted.is_(False),
        )
    )
    if revision_tool is None:
        raise SorAuthorityError(
            "AGENT_REVISION_TOOL_UNAVAILABLE",
            "The pinned Agent revision has no matching source tool.",
        )


__all__ = [
    "AuthorizedSorSource",
    "SorAuthorityError",
    "resolve_agent_sources",
    "resolve_profile_tool",
]
