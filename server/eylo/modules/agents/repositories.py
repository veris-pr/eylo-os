"""Persistence for Agent drafts, swarm membership and background attachments."""

from copy import deepcopy
from typing import List, Optional, Type
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from eylo.common.repositories import BaseORMRepository
from eylo.modules.agents.models import (
    AgentBackgroundAgentModel,
    AgentStatus,
    AgentSwarmMappingModel,
    AgentSwarmModel,
    AgentToolMappingModal,
    AgentsModel,
)
from eylo.modules.agents.schemas.indb import AgentCreate, AgentUpdate, AgentUpdateField


class AgentsRepository(BaseORMRepository[AgentsModel]):
    @property
    def model(self) -> Type[AgentsModel]:
        return AgentsModel

    async def create(self, request: AgentCreate) -> AgentsModel:
        agent = self.model(
            organization_id=request.organization_id,
            name=request.name,
            description=request.description,
            kind=request.kind,
            implementation=request.implementation,
            prompt=request.prompt,
            llm_provider_config_id=request.llm_provider_config_id,
            llm_provider_config_revision=None,
            email_provider_config_id=request.email_provider_config_id,
            email_provider_config_revision=None,
            webrtc_provider_config_id=request.webrtc_provider_config_id,
            webrtc_provider_config_revision=None,
            voice_config_id=request.voice_config_id,
            voice_config_revision=request.voice_config_revision,
            reranking_provider_config_id=request.reranking_provider_config_id,
            reranking_provider_config_revision=None,
            memory_provider_config_id=request.memory_provider_config_id,
            memory_provider_config_revision=None,
            allow_file_uploads=request.allow_file_uploads,
            file_upload_embedding_provider_config_id=(
                request.file_upload_embedding_provider_config_id
            ),
            file_upload_embedding_provider_config_revision=None,
            instruction_template_id=request.instruction_template_id,
            llm_overrides=request.llm_overrides.model_dump(
                mode="json", exclude_none=True
            ),
        )
        return await self.save_(agent)

    async def list_by_organization_id(
        self,
        organization_id: UUID,
        include_inactive: bool = False,
    ) -> List[AgentsModel]:
        filters = [
            self.model.organization_id == organization_id,
            self.model.deleted.is_(False),
        ]
        if not include_inactive:
            filters.append(
                self.model.status.in_([AgentStatus.ACTIVE, AgentStatus.DRAFT])
            )
        return await self.filter_all_(filters=filters)

    async def list_by_ids(
        self,
        agent_ids: List[UUID],
        organization_id: UUID,
    ) -> List[AgentsModel]:
        """Bulk fetch agents by IDs within an organization.

        Args:
            agent_ids: List of agent IDs to fetch
            organization_id: Organization ID for access control

        Returns:
            List of agent models matching the IDs

        """
        if not agent_ids:
            return []

        filters = [
            self.model.id.in_(agent_ids),
            self.model.organization_id == organization_id,
            self.model.deleted.is_(False),
        ]
        return await self.filter_all_(filters=filters)

    async def get_by_id_and_organization(
        self, pk: UUID, organization_id: UUID
    ) -> Optional[AgentsModel]:
        """Get a non-deleted agent by its ID and organization ID."""
        return await self.filter_one_(
            filters=[
                self.model.id == pk,
                self.model.organization_id == organization_id,
                self.model.deleted.is_(False),
            ]
        )

    async def update_(
        self,
        agent_id: UUID,
        organization_id: UUID,
        payload: AgentUpdate,
    ) -> Optional[AgentsModel]:
        """Update an agent by its ID and organization ID."""
        agent_model = await self.get_by_id_and_organization(
            pk=agent_id, organization_id=organization_id
        )

        if not agent_model:
            return None

        fields = payload.model_fields_set
        if AgentUpdateField.ID in fields and payload.id is not None:
            agent_model.id = payload.id
        if (
            AgentUpdateField.ORGANIZATION_ID in fields
            and payload.organization_id is not None
        ):
            agent_model.organization_id = payload.organization_id
        if AgentUpdateField.NAME in fields and payload.name is not None:
            agent_model.name = payload.name
        if AgentUpdateField.LLM_PROVIDER_CONFIG_ID in fields:
            agent_model.llm_provider_config_id = payload.llm_provider_config_id
        if AgentUpdateField.LLM_PROVIDER_CONFIG_REVISION in fields:
            agent_model.llm_provider_config_revision = (
                payload.llm_provider_config_revision
            )
        if AgentUpdateField.EMAIL_PROVIDER_CONFIG_ID in fields:
            agent_model.email_provider_config_id = payload.email_provider_config_id
        if AgentUpdateField.EMAIL_PROVIDER_CONFIG_REVISION in fields:
            agent_model.email_provider_config_revision = (
                payload.email_provider_config_revision
            )
        if AgentUpdateField.WEBRTC_PROVIDER_CONFIG_ID in fields:
            agent_model.webrtc_provider_config_id = payload.webrtc_provider_config_id
        if AgentUpdateField.WEBRTC_PROVIDER_CONFIG_REVISION in fields:
            agent_model.webrtc_provider_config_revision = (
                payload.webrtc_provider_config_revision
            )
        if AgentUpdateField.VOICE_CONFIG_ID in fields:
            agent_model.voice_config_id = payload.voice_config_id
        if AgentUpdateField.VOICE_CONFIG_REVISION in fields:
            agent_model.voice_config_revision = payload.voice_config_revision
        if (
            AgentUpdateField.LLM_OVERRIDES in fields
            and payload.llm_overrides is not None
        ):
            agent_model.llm_overrides = payload.llm_overrides.model_dump(
                exclude_unset=True
            )
        if AgentUpdateField.RERANKING_PROVIDER_CONFIG_ID in fields:
            agent_model.reranking_provider_config_id = (
                payload.reranking_provider_config_id
            )
        if AgentUpdateField.RERANKING_PROVIDER_CONFIG_REVISION in fields:
            agent_model.reranking_provider_config_revision = (
                payload.reranking_provider_config_revision
            )
        if AgentUpdateField.MEMORY_PROVIDER_CONFIG_ID in fields:
            agent_model.memory_provider_config_id = payload.memory_provider_config_id
        if AgentUpdateField.MEMORY_PROVIDER_CONFIG_REVISION in fields:
            agent_model.memory_provider_config_revision = (
                payload.memory_provider_config_revision
            )
        if AgentUpdateField.ALLOW_FILE_UPLOADS in fields:
            agent_model.allow_file_uploads = payload.allow_file_uploads
        if AgentUpdateField.FILE_UPLOAD_EMBEDDING_PROVIDER_CONFIG_ID in fields:
            agent_model.file_upload_embedding_provider_config_id = (
                payload.file_upload_embedding_provider_config_id
            )
        if AgentUpdateField.FILE_UPLOAD_EMBEDDING_PROVIDER_CONFIG_REVISION in fields:
            agent_model.file_upload_embedding_provider_config_revision = (
                payload.file_upload_embedding_provider_config_revision
            )
        if AgentUpdateField.INSTRUCTION_TEMPLATE_ID in fields:
            agent_model.instruction_template_id = payload.instruction_template_id
        if AgentUpdateField.DESCRIPTION in fields and payload.description is not None:
            agent_model.description = payload.description
        if (
            AgentUpdateField.IMPLEMENTATION in fields
            and payload.implementation is not None
        ):
            agent_model.implementation = payload.implementation
        if AgentUpdateField.PROMPT in fields and payload.prompt is not None:
            agent_model.prompt = deepcopy(payload.prompt)

        return await self.save_(agent_model)


class AgentToolMappingRepository(BaseORMRepository[AgentToolMappingModal]):
    @property
    def model(self) -> Type[AgentToolMappingModal]:
        return AgentToolMappingModal

    async def create_(
        self,
        *,
        agent_id: UUID,
        tool_id: UUID,
        tool_revision: int,
        organization_id: UUID,
    ) -> AgentToolMappingModal:
        agent_tool_mapping = self.model(
            agent_id=agent_id,
            tool_id=tool_id,
            tool_revision=tool_revision,
            organization_id=organization_id,
        )
        return await self.save_(agent_tool_mapping)

    async def list_tools_by_agent_id(
        self, agent_id: UUID
    ) -> List[AgentToolMappingModal]:
        """List revisioned platform and MCP tool mappings for a given agent.

        Curated grants are excluded: they carry no `tool_id` and no revision,
        and every caller here resolves a `(tool_id, tool_revision)` pair. They
        are listed through `AgentToolService.list_curated_tool_ids` instead.
        """
        return await self.filter_all_(
            filters=[
                self.model.agent_id == agent_id,
                self.model.tool_id.is_not(None),
            ]
        )

    async def delete_by_agent_and_tool_id(self, agent_id: UUID, tool_id: UUID) -> None:
        """Delete a tool mapping for a given agent."""
        mapping = await self.filter_one_(
            filters=[
                self.model.agent_id == agent_id,
                self.model.tool_id == tool_id,
            ]
        )
        if mapping:
            await self.delete_(mapping, hard_delete=True)


class AgentSwarmRepository(BaseORMRepository[AgentSwarmModel]):
    @property
    def model(self) -> Type[AgentSwarmModel]:
        return AgentSwarmModel

    async def create(
        self, name: str, description: str | None, organization_id: UUID
    ) -> AgentSwarmModel:
        agent_swarm = self.model(
            name=name,
            description=description,
            organization_id=organization_id,
        )
        return await self.save_(agent_swarm)

    async def list_by_organization_id(
        self,
        organization_id: UUID,
    ) -> List[AgentSwarmModel]:
        filters = [
            self.model.organization_id == organization_id,
        ]
        return await self.filter_all_(filters=filters)

    async def get_by_id_and_organization(
        self, pk: UUID, organization_id: UUID
    ) -> Optional[AgentSwarmModel]:
        """Get an agent swarm by its ID and organization ID."""
        return await self.filter_one_(
            filters=[
                self.model.id == pk,
                self.model.organization_id == organization_id,
            ]
        )


class AgentSwarmMappingRepository(BaseORMRepository[AgentSwarmMappingModel]):
    @property
    def model(self) -> Type[AgentSwarmMappingModel]:
        return AgentSwarmMappingModel

    async def create(
        self,
        agent_id: UUID,
        swarm_id: UUID,
        organization_id: UUID,
        agent_description: Optional[str],
    ) -> AgentSwarmMappingModel:
        agent_swarm_mapping = self.model(
            agent_id=agent_id,
            swarm_id=swarm_id,
            organization_id=organization_id,
            agent_description=agent_description,
        )
        return await self.save_(agent_swarm_mapping)

    async def list_by_swarm_id(
        self,
        swarm_id: UUID,
        organization_id: UUID,
    ) -> List[AgentSwarmMappingModel]:
        filters = [
            self.model.swarm_id == swarm_id,
            self.model.organization_id == organization_id,
        ]
        return await self.filter_all_(filters=filters)

    async def delete_agent_from_swarm(
        self, agent_id: UUID, swarm_id: UUID, organization_id: UUID
    ) -> bool:
        result = await self.db_session.execute(
            delete(self.model).where(
                self.model.agent_id == agent_id,
                self.model.swarm_id == swarm_id,
                self.model.organization_id == organization_id,
            )
        )
        if not isinstance(result, CursorResult):
            raise TypeError("Swarm membership deletion requires a DML row count.")
        return result.rowcount > 0


class AgentBackgroundAgentRepository(BaseORMRepository[AgentBackgroundAgentModel]):
    @property
    def model(self) -> Type[AgentBackgroundAgentModel]:
        return AgentBackgroundAgentModel

    async def create_(
        self, agent_id: UUID, background_agent_id: UUID, enabled: bool = False
    ) -> AgentBackgroundAgentModel:
        return await self.save_(
            self.model(
                agent_id=agent_id,
                background_agent_id=background_agent_id,
                enabled=enabled,
            )
        )

    async def list_by_agent_id(
        self, agent_id: UUID
    ) -> List[AgentBackgroundAgentModel]:
        return await self.filter_all_(filters=[self.model.agent_id == agent_id])

    async def list_enabled_by_agent_id(
        self, agent_id: UUID
    ) -> List[AgentBackgroundAgentModel]:
        """The dispatch path's query: only attachments that should run."""
        return await self.filter_all_(
            filters=[
                self.model.agent_id == agent_id,
                self.model.enabled.is_(True),
            ]
        )

    async def get_attachment(
        self, agent_id: UUID, background_agent_id: UUID
    ) -> Optional[AgentBackgroundAgentModel]:
        return await self.filter_one_(
            filters=[
                self.model.agent_id == agent_id,
                self.model.background_agent_id == background_agent_id,
            ]
        )

    async def delete_attachment(
        self, agent_id: UUID, background_agent_id: UUID
    ) -> bool:
        mapping = await self.get_attachment(agent_id, background_agent_id)
        if mapping is None:
            return False
        await self.delete_(mapping, hard_delete=True)
        return True
