"""Draft grants, immutable Agent revision snapshots, and live SOR authority."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.agents.models import AgentRevisionToolModel, AgentsModel
from eylo.modules.agents.services.revisions import AgentRevisionService
from eylo.modules.tools.services.tool_register import system_tool_id
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.tools import iter_sor_tool_declarations

from .contracts import (
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorSourceAccess,
    SorSourceState,
    SorToolEffect,
)
from .models import (
    SorAgentRevisionSourceGrantModel,
    SorFieldMappingModel,
    SorSourceGrantModel,
    SorSourceModel,
    SorSourceStreamModel,
)
from .repositories import SorRepository
from .schemas import SorSourceGrantResponse
from .services import SorConfigurationError, SorNotFoundError


class SorGrantPublicationError(Exception):
    """A live draft grant cannot be copied into a published Agent revision."""


class SorSourceGrantService:
    """Own explicit Agent-to-source authority without inferring configured access."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def list_for_agent(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
    ) -> tuple[SorSourceGrantResponse, ...]:
        """List the Agent draft's live grants with safe source labels."""
        await self._require_agent(
            organization_id=organization_id,
            agent_id=agent_id,
        )
        rows = (
            await self.session.execute(
                select(SorSourceGrantModel, SorSourceModel)
                .join(
                    SorSourceModel,
                    (SorSourceModel.id == SorSourceGrantModel.source_id)
                    & (
                        SorSourceModel.organization_id
                        == SorSourceGrantModel.organization_id
                    ),
                )
                .where(
                    SorSourceGrantModel.organization_id == organization_id,
                    SorSourceGrantModel.agent_id == agent_id,
                    SorSourceGrantModel.deleted.is_(False),
                    SorSourceModel.deleted.is_(False),
                )
                .order_by(SorSourceModel.name.asc(), SorSourceModel.id.asc())
            )
        ).all()
        return tuple(_grant_response(grant, source) for grant, source in rows)

    async def grant(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        source_id: UUID,
        access: SorSourceAccess,
        expected_draft_version: int,
        actor_id: UUID | None,
    ) -> SorSourceGrantResponse:
        """Create or change one live grant and advance the Agent draft once."""
        await self._require_agent(
            organization_id=organization_id,
            agent_id=agent_id,
            for_update=True,
        )
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        await self._require_grantable_source(source=source, access=access)

        existing = await self.repository.get_live_source_grant(
            organization_id=organization_id,
            agent_id=agent_id,
            source_id=source_id,
            for_update=True,
        )
        if existing is not None and existing.access is access:
            return _grant_response(existing, source)

        await AgentRevisionService(self.session).mark_draft_changed(
            organization_id=organization_id,
            agent_id=agent_id,
            expected_draft_version=expected_draft_version,
        )
        if existing is None:
            existing = SorSourceGrantModel(
                organization_id=organization_id,
                agent_id=agent_id,
                source_id=source_id,
                access=access,
                revision=1,
                granted_by=actor_id,
            )
            self.session.add(existing)
        else:
            existing.access = access
            existing.revision += 1
            existing.granted_by = actor_id
        await self.session.flush()
        return _grant_response(existing, source)

    async def revoke(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        source_id: UUID,
        expected_draft_version: int,
        actor_id: UUID | None,
    ) -> None:
        """Soft-revoke authority so published snapshots retain their identity."""
        await self._require_agent(
            organization_id=organization_id,
            agent_id=agent_id,
            for_update=True,
        )
        grant = await self.repository.get_live_source_grant(
            organization_id=organization_id,
            agent_id=agent_id,
            source_id=source_id,
            for_update=True,
        )
        if grant is None:
            raise SorNotFoundError("SOR source grant not found.")
        await AgentRevisionService(self.session).mark_draft_changed(
            organization_id=organization_id,
            agent_id=agent_id,
            expected_draft_version=expected_draft_version,
        )
        grant.revision += 1
        grant.deleted = True
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoked_by = actor_id
        await self.session.flush()

    async def snapshot_agent_revision(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        agent_revision: int,
    ) -> tuple[SorAgentRevisionSourceGrantModel, ...]:
        """Copy every live draft grant into one immutable Agent revision."""
        grants = await self.repository.list_live_source_grants(
            organization_id=organization_id,
            agent_id=agent_id,
            for_update=True,
        )
        source_grants: list[tuple[SorSourceGrantModel, SorSourceModel]] = []
        for grant in grants:
            source = await self.repository.get_source(
                organization_id=organization_id,
                source_id=grant.source_id,
            )
            if source is None or source.active_mapping_revision_id is None:
                raise SorGrantPublicationError(
                    "Every SOR source grant must reference a configured source."
                )
            source_grants.append((grant, source))

        await self._validate_assigned_tools(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_revision=agent_revision,
            source_grants=source_grants,
        )

        snapshots: list[SorAgentRevisionSourceGrantModel] = []
        for grant, source in source_grants:
            snapshot = SorAgentRevisionSourceGrantModel(
                organization_id=organization_id,
                agent_id=agent_id,
                agent_revision=agent_revision,
                source_id=grant.source_id,
                source_grant_id=grant.id,
                source_grant_revision=grant.revision,
                access=grant.access,
            )
            self.session.add(snapshot)
            snapshots.append(snapshot)
            # Avoid PostgreSQL insertmanyvalues UUID sentinel mismatches. Agent
            # source grants are operator-bounded, so individual INSERTs remain
            # one atomic publication transaction.
            await self.session.flush()
        return tuple(snapshots)

    async def _validate_assigned_tools(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        agent_revision: int,
        source_grants: list[tuple[SorSourceGrantModel, SorSourceModel]],
    ) -> None:
        """Reject SOR tools that no granted source can execute exactly."""
        revision_tool_ids = set(
            (
                await self.session.scalars(
                    select(AgentRevisionToolModel.tool_id).where(
                        AgentRevisionToolModel.organization_id == organization_id,
                        AgentRevisionToolModel.agent_id == agent_id,
                        AgentRevisionToolModel.agent_revision == agent_revision,
                        AgentRevisionToolModel.tool_id.is_not(None),
                        AgentRevisionToolModel.deleted.is_(False),
                    )
                )
            ).all()
        )
        assigned = tuple(
            declaration
            for declaration in iter_sor_tool_declarations()
            if system_tool_id(declaration.spec.name, organization_id)
            in revision_tool_ids
        )
        if not assigned:
            return

        registry = get_sor_registry()
        stream_entities: dict[UUID, frozenset[str]] = {}
        stream_keys: dict[UUID, frozenset[str]] = {}
        for _grant, source in source_grants:
            streams = await self.repository.list_streams(
                organization_id=organization_id,
                source_id=source.id,
            )
            stream_entities[source.id] = frozenset(
                stream.canonical_entity_kind for stream in streams
            )
            stream_keys[source.id] = frozenset(
                stream.vendor_object_key for stream in streams
            )

        for declaration in assigned:
            for grant, source in source_grants:
                if source.profile is not declaration.profile:
                    continue
                try:
                    manifest = registry.get_manifest(
                        profile=source.profile,
                        vendor_key=source.vendor_key,
                    )
                except KeyError:
                    continue
                executable = (
                    manifest.readable_tools
                    if declaration.spec.effect is SorToolEffect.READ
                    else manifest.writable_tools
                )
                if declaration.spec.name not in executable:
                    continue
                if (
                    declaration.spec.effect is SorToolEffect.MUTATION
                    and grant.access is not SorSourceAccess.READ_WRITE
                ):
                    continue
                relevant_entities = declaration.spec.target_entities.intersection(
                    stream_entities[source.id]
                )
                if not relevant_entities:
                    continue
                if declaration.spec.effect is SorToolEffect.MUTATION:
                    result_stream = manifest.mutation_result_streams.get(
                        declaration.spec.name
                    )
                    if (
                        result_stream is None
                        or result_stream not in stream_keys[source.id]
                    ):
                        continue
                    if not await self._has_active_mapping_for_stream(
                        organization_id=organization_id,
                        source=source,
                        vendor_object_key=result_stream,
                    ):
                        continue
                if (
                    declaration.spec.effect is SorToolEffect.MUTATION
                    and not await self._has_writable_mapping(
                        organization_id=organization_id,
                        source=source,
                        entities=relevant_entities,
                    )
                ):
                    continue
                break
            else:
                raise SorGrantPublicationError(
                    f"Assigned source tool {declaration.spec.name} has no granted "
                    "source that can execute it."
                )

    async def _has_writable_mapping(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        entities: frozenset[str],
    ) -> bool:
        mapping_id = await self.session.scalar(
            select(SorFieldMappingModel.id)
            .join(
                SorSourceStreamModel,
                and_(
                    SorSourceStreamModel.organization_id
                    == SorFieldMappingModel.organization_id,
                    SorSourceStreamModel.source_id == SorFieldMappingModel.source_id,
                    SorSourceStreamModel.vendor_object_key
                    == SorFieldMappingModel.vendor_object_key,
                ),
            )
            .where(
                SorFieldMappingModel.organization_id == organization_id,
                SorFieldMappingModel.source_id == source.id,
                SorFieldMappingModel.mapping_revision_id
                == source.active_mapping_revision_id,
                SorFieldMappingModel.direction == SorFieldMappingDirection.READ_WRITE,
                SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
                SorFieldMappingModel.deleted.is_(False),
                SorSourceStreamModel.canonical_entity_kind.in_(entities),
                SorSourceStreamModel.deleted.is_(False),
            )
            .limit(1)
        )
        return mapping_id is not None

    async def _has_active_mapping_for_stream(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        vendor_object_key: str,
    ) -> bool:
        """Confirm read-after-write can project the declared result stream."""
        mapping_id = await self.session.scalar(
            select(SorFieldMappingModel.id)
            .where(
                SorFieldMappingModel.organization_id == organization_id,
                SorFieldMappingModel.source_id == source.id,
                SorFieldMappingModel.mapping_revision_id
                == source.active_mapping_revision_id,
                SorFieldMappingModel.vendor_object_key == vendor_object_key,
                SorFieldMappingModel.direction != SorFieldMappingDirection.IGNORE,
                SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
                SorFieldMappingModel.deleted.is_(False),
            )
            .limit(1)
        )
        return mapping_id is not None

    async def _require_agent(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        for_update: bool = False,
    ) -> AgentsModel:
        query = select(AgentsModel).where(
            AgentsModel.organization_id == organization_id,
            AgentsModel.id == agent_id,
            AgentsModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        agent = await self.session.scalar(query)
        if agent is None:
            raise SorNotFoundError("Agent not found.")
        return agent

    async def _require_grantable_source(
        self,
        *,
        source: SorSourceModel,
        access: SorSourceAccess,
    ) -> None:
        if source.state is SorSourceState.DISABLED:
            raise SorConfigurationError("Disabled SOR sources cannot be granted.")
        if source.active_mapping_revision_id is None:
            raise SorConfigurationError(
                "Publish a source mapping before granting Agent access."
            )
        if access is SorSourceAccess.READ:
            return
        try:
            manifest = get_sor_registry().get_manifest(
                profile=source.profile,
                vendor_key=source.vendor_key,
            )
        except KeyError as error:
            raise SorConfigurationError(
                "The source adapter is unavailable in this deployment."
            ) from error
        if not manifest.writable_entities:
            raise SorConfigurationError("This source adapter is read-only.")
        writable_mapping = await self.session.scalar(
            select(SorFieldMappingModel.id)
            .where(
                SorFieldMappingModel.organization_id == source.organization_id,
                SorFieldMappingModel.source_id == source.id,
                SorFieldMappingModel.mapping_revision_id
                == source.active_mapping_revision_id,
                SorFieldMappingModel.direction == SorFieldMappingDirection.READ_WRITE,
                SorFieldMappingModel.state == SorFieldMappingState.ACTIVE,
                SorFieldMappingModel.deleted.is_(False),
            )
            .limit(1)
        )
        if writable_mapping is None:
            raise SorConfigurationError(
                "Publish at least one writable field mapping before granting "
                "read-write access."
            )


def _grant_response(
    grant: SorSourceGrantModel,
    source: SorSourceModel,
) -> SorSourceGrantResponse:
    return SorSourceGrantResponse(
        id=grant.id,
        organization_id=grant.organization_id,
        agent_id=grant.agent_id,
        source_id=grant.source_id,
        source_name=source.name,
        profile=source.profile,
        vendor_key=source.vendor_key,
        access=grant.access,
        revision=grant.revision,
        granted_by=grant.granted_by,
        created_at=grant.created_at,
        updated_at=grant.updated_at,
    )


__all__ = ["SorGrantPublicationError", "SorSourceGrantService"]
