"""Publication authority for immutable executable agent revisions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.provider_config import Capability
from eylo.common.database import get_transaction
from eylo.common.revisions import (
    DefinitionHeaderState,
    DefinitionLifecycle,
    PublishedRevisionState,
    RevisionAvailability,
)
from eylo.modules.agents.domain import InvalidAgentDefinitionError
from eylo.modules.agents.models import (
    AgentBackgroundAgentModel,
    AgentKind,
    AgentRevisionBackgroundAgentModel,
    AgentRevisionModel,
    AgentRevisionToolModel,
    AgentStatus,
    AgentToolMappingModal,
    AgentsModel,
)
from eylo.modules.agents.publication_bindings import (
    AgentProviderBindings,
    AgentProviderReference,
    curated_tool_ref,
    provider_pair,
    revisioned_tool_ref,
)
from eylo.modules.templates.domain import TemplateKind
from eylo.modules.templates.service import TemplateService
from eylo.modules.tools.services.indb import ToolService
from eylo.modules.voice.services.voice_configs import VoiceConfigPublication


class AgentRevisionService:
    """Validate a complete draft, publish it, and load exact revisions."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db or get_transaction()

    async def publish(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        expected_draft_version: int,
        actor_id: UUID | None = None,
    ) -> AgentRevisionModel:
        header = await self._get_header(
            organization_id,
            agent_id,
            for_update=True,
        )
        next_revision = (header.published_revision or 0) + 1
        next_state = _header_state(header).publish(
            revision=next_revision,
            expected_draft_version=expected_draft_version,
        )

        template_id, template_revision = await self._resolve_template(header)
        provider_refs = await self._resolve_provider_refs(header)
        voice_publication = await self._resolve_voice_config(header)
        llm_id, llm_revision = provider_pair(provider_refs.llm)
        email_id, email_revision = provider_pair(provider_refs.email)
        webrtc_id, webrtc_revision = provider_pair(provider_refs.webrtc)
        reranking_id, reranking_revision = provider_pair(provider_refs.reranking)
        memory_id, memory_revision = provider_pair(provider_refs.memory)
        upload_embedding_id, upload_embedding_revision = provider_pair(
            provider_refs.file_upload_embedding
        )
        config = None if voice_publication is None else voice_publication.config
        stt_id, stt_revision = _voice_ref(
            None if config is None else config.stt_provider_config_id,
            None if config is None else config.stt_provider_config_revision,
            Capability.STT,
        )
        tts_id, tts_revision = _voice_ref(
            None if config is None else config.tts_provider_config_id,
            None if config is None else config.tts_provider_config_revision,
            Capability.TTS,
        )
        realtime_id, realtime_revision = _voice_ref(
            None if config is None else config.realtime_provider_config_id,
            None if config is None else config.realtime_provider_config_revision,
            Capability.REALTIME,
        )
        storage_id, storage_revision = _voice_ref(
            None if config is None else config.storage_provider_config_id,
            None if config is None else config.storage_provider_config_revision,
            Capability.STORAGE,
        )
        voice_config = (
            None
            if voice_publication is None
            else voice_publication.config.model_dump(mode="json")
        )
        tool_refs = await self._tool_refs(header)
        curated_tool_ids = await self._curated_tool_refs(header)
        background_refs = await self._background_refs(header)

        published_at = datetime.now(timezone.utc)
        revision = AgentRevisionModel(
            organization_id=organization_id,
            agent_id=agent_id,
            revision=next_revision,
            name=header.name,
            slug=header.slug,
            description=header.description,
            webhook=header.webhook,
            kind=_enum_value(header.kind),
            implementation=header.implementation,
            voice_config_id=(
                None if voice_publication is None else voice_publication.voice_config_id
            ),
            voice_config_revision=(
                None
                if voice_publication is None
                else voice_publication.voice_config_revision
            ),
            instruction_template_id=template_id,
            instruction_template_revision=template_revision,
            llm_provider_config_id=llm_id,
            llm_provider_config_revision=llm_revision,
            email_provider_config_id=email_id,
            email_provider_config_revision=email_revision,
            webrtc_provider_config_id=webrtc_id,
            webrtc_provider_config_revision=webrtc_revision,
            reranking_provider_config_id=reranking_id,
            reranking_provider_config_revision=reranking_revision,
            memory_provider_config_id=memory_id,
            memory_provider_config_revision=memory_revision,
            allow_file_uploads=header.allow_file_uploads,
            file_upload_embedding_provider_config_id=upload_embedding_id,
            file_upload_embedding_provider_config_revision=upload_embedding_revision,
            stt_provider_config_id=stt_id,
            stt_provider_config_revision=stt_revision,
            tts_provider_config_id=tts_id,
            tts_provider_config_revision=tts_revision,
            realtime_provider_config_id=realtime_id,
            realtime_provider_config_revision=realtime_revision,
            storage_provider_config_id=storage_id,
            storage_provider_config_revision=storage_revision,
            llm_overrides=dict(header.llm_overrides or {}),
            voice_config=voice_config,
            published_at=published_at,
            published_by=actor_id,
        )
        self._db.add(revision)
        await self._db.flush()

        self._db.add_all(
            [
                AgentRevisionToolModel(
                    agent_id=agent_id,
                    agent_revision=next_revision,
                    tool_id=tool_id,
                    tool_revision=tool_revision,
                    organization_id=organization_id,
                )
                for tool_id, tool_revision in tool_refs
            ]
        )
        # Curated grants carry no tool revision: their definition is code, so
        # there is nothing to pin into the revision beyond the binding itself.
        self._db.add_all(
            [
                AgentRevisionToolModel(
                    agent_id=agent_id,
                    agent_revision=next_revision,
                    tool_id=None,
                    tool_revision=None,
                    curated_tool_id=curated_tool_id,
                    organization_id=organization_id,
                )
                for curated_tool_id in curated_tool_ids
            ]
        )
        self._db.add_all(
            [
                AgentRevisionBackgroundAgentModel(
                    agent_id=agent_id,
                    agent_revision=next_revision,
                    background_agent_id=background_agent_id,
                    background_agent_revision=background_revision,
                    organization_id=organization_id,
                )
                for background_agent_id, background_revision in background_refs
            ]
        )
        await self._db.flush()

        header.llm_provider_config_id = llm_id
        header.llm_provider_config_revision = llm_revision
        header.email_provider_config_id = email_id
        header.email_provider_config_revision = email_revision
        header.webrtc_provider_config_id = webrtc_id
        header.webrtc_provider_config_revision = webrtc_revision
        header.reranking_provider_config_id = reranking_id
        header.reranking_provider_config_revision = reranking_revision
        header.memory_provider_config_id = memory_id
        header.memory_provider_config_revision = memory_revision
        header.file_upload_embedding_provider_config_id = upload_embedding_id
        header.file_upload_embedding_provider_config_revision = (
            upload_embedding_revision
        )
        _apply_header_state(header, next_state)
        header.status = AgentStatus.ACTIVE
        await self._db.flush()
        return revision

    async def withdraw(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
    ) -> AgentsModel:
        header = await self._get_header(
            organization_id,
            agent_id,
            for_update=True,
        )
        _apply_header_state(header, _header_state(header).withdraw())
        header.status = AgentStatus.INACTIVE
        await self._db.flush()
        return header

    async def mark_draft_changed(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        expected_draft_version: int,
    ) -> AgentsModel:
        """Advance optimistic draft state after a related aggregate changes."""
        header = await self._get_header(
            organization_id,
            agent_id,
            for_update=True,
        )
        _apply_header_state(
            header,
            _header_state(header).edit(expected_draft_version=expected_draft_version),
        )
        await self._db.flush()
        return header

    async def revoke(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
        actor_id: UUID,
        reason: str,
    ) -> AgentRevisionModel:
        header = await self._get_header(
            organization_id,
            agent_id,
            for_update=True,
        )
        row = await self.get_revision(
            organization_id=organization_id,
            agent_id=agent_id,
            revision=revision,
            for_update=True,
        )
        revoked = _revision_state(row).revoke(
            actor_id=actor_id,
            reason=reason,
            at=datetime.now(timezone.utc),
        )
        row.availability = revoked.availability.value
        row.revoked_at = revoked.revoked_at
        row.revoked_by = revoked.revoked_by
        row.revocation_reason = revoked.revocation_reason
        row.cancellation_requested_at = revoked.cancellation_requested_at
        if header.published_revision == revision:
            _apply_header_state(header, _header_state(header).withdraw())
            header.status = AgentStatus.INACTIVE
        await self._db.flush()
        return row

    async def resolve_for_new_work(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        for_update: bool = False,
    ) -> AgentRevisionModel:
        header = await self._get_header(
            organization_id,
            agent_id,
            for_update=for_update,
        )
        revision = _header_state(header).revision_for_new_work()
        return await self.get_revision(
            organization_id=organization_id,
            agent_id=agent_id,
            revision=revision,
            for_update=for_update,
        )

    async def list_available_for_widget(
        self,
        *,
        organization_id: UUID,
        agent_ids: Sequence[UUID] | None = None,
    ) -> list[AgentRevisionModel]:
        """List immutable revisions that may start a widget conversation."""
        query = (
            select(AgentRevisionModel)
            .join(
                AgentsModel,
                and_(
                    AgentsModel.id == AgentRevisionModel.agent_id,
                    AgentsModel.organization_id == AgentRevisionModel.organization_id,
                    AgentsModel.published_revision == AgentRevisionModel.revision,
                ),
            )
            .where(
                AgentRevisionModel.organization_id == organization_id,
                AgentRevisionModel.kind == AgentKind.CONVERSATIONAL.value,
                AgentRevisionModel.availability == RevisionAvailability.PUBLISHED.value,
                AgentRevisionModel.deleted.is_(False),
                AgentsModel.status == AgentStatus.ACTIVE,
                AgentsModel.deleted.is_(False),
            )
            .order_by(
                AgentRevisionModel.name.asc(),
                AgentRevisionModel.agent_id.asc(),
            )
        )
        if agent_ids is not None:
            query = query.where(AgentRevisionModel.agent_id.in_(agent_ids))
        rows = await self._db.scalars(query)
        return list(rows.all())

    async def get_revision(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
        for_update: bool = False,
    ) -> AgentRevisionModel:
        query = select(AgentRevisionModel).where(
            AgentRevisionModel.organization_id == organization_id,
            AgentRevisionModel.agent_id == agent_id,
            AgentRevisionModel.revision == revision,
            AgentRevisionModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        row = await self._db.scalar(query)
        if row is None:
            from eylo.modules.agents.exceptions import AgentNotFoundError

            raise AgentNotFoundError("Agent revision not found.")
        _revision_state(row).require_available()
        return row

    async def list_tool_refs(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
    ) -> list[tuple[UUID, int]]:
        rows = await self._db.scalars(
            select(AgentRevisionToolModel).where(
                AgentRevisionToolModel.organization_id == organization_id,
                AgentRevisionToolModel.agent_id == agent_id,
                AgentRevisionToolModel.agent_revision == revision,
                AgentRevisionToolModel.tool_id.is_not(None),
                AgentRevisionToolModel.deleted.is_(False),
            )
        )
        return [revisioned_tool_ref(row) for row in rows.all()]

    async def list_curated_tool_ids(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
    ) -> list[UUID]:
        """Curated tool grants pinned into one exact agent revision.

        Returned as bare ids rather than (id, revision) pairs: a curated tool's
        definition is code and has no revision to pin.
        """
        rows = await self._db.scalars(
            select(AgentRevisionToolModel).where(
                AgentRevisionToolModel.organization_id == organization_id,
                AgentRevisionToolModel.agent_id == agent_id,
                AgentRevisionToolModel.agent_revision == revision,
                AgentRevisionToolModel.curated_tool_id.is_not(None),
                AgentRevisionToolModel.deleted.is_(False),
            )
        )
        return [curated_tool_ref(row) for row in rows.all()]

    async def list_background_refs(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
    ) -> list[tuple[UUID, int]]:
        rows = await self._db.scalars(
            select(AgentRevisionBackgroundAgentModel).where(
                AgentRevisionBackgroundAgentModel.organization_id == organization_id,
                AgentRevisionBackgroundAgentModel.agent_id == agent_id,
                AgentRevisionBackgroundAgentModel.agent_revision == revision,
                AgentRevisionBackgroundAgentModel.deleted.is_(False),
            )
        )
        return [
            (row.background_agent_id, row.background_agent_revision)
            for row in rows.all()
        ]

    async def _get_header(
        self,
        organization_id: UUID,
        agent_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentsModel:
        query = select(AgentsModel).where(
            AgentsModel.organization_id == organization_id,
            AgentsModel.id == agent_id,
            AgentsModel.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        header = await self._db.scalar(query)
        if header is None:
            from eylo.modules.agents.exceptions import AgentNotFoundError

            raise AgentNotFoundError()
        return header

    async def _resolve_template(
        self,
        header: AgentsModel,
    ) -> tuple[UUID | None, int | None]:
        code_owned = (
            _enum_value(header.kind) == AgentKind.BACKGROUND.value
            and header.implementation is not None
        )
        if code_owned:
            if header.instruction_template_id is not None:
                raise InvalidAgentDefinitionError(
                    "Code-owned background agents cannot bind an instruction template."
                )
            return None, None
        if header.instruction_template_id is None:
            raise InvalidAgentDefinitionError(
                "Assign a published agent-instructions template before publishing."
            )
        template = await TemplateService(self._db).resolve_for_new_work(
            organization_id=header.organization_id,
            template_id=header.instruction_template_id,
        )
        if template.kind != TemplateKind.AGENT_INSTRUCTIONS.value:
            raise InvalidAgentDefinitionError(
                "Agent definitions require an agent-instructions template."
            )
        if template.variable_schema != {"variables": []}:
            raise InvalidAgentDefinitionError(
                "Agent instruction templates cannot declare runtime variables in V1."
            )
        return template.template_id, template.revision

    async def _resolve_provider_refs(
        self,
        header: AgentsModel,
    ) -> AgentProviderBindings:
        from eylo.modules.agents.services.indb import AgentService

        service = AgentService(self._db)
        if header.llm_provider_config_id is None:
            raise InvalidAgentDefinitionError(
                "Assign a ready LLM config before publishing the agent."
            )
        refs = AgentProviderBindings(
            llm=AgentProviderReference(
                config_id=header.llm_provider_config_id,
                revision=await service._resolve_llm_revision(
                    header.organization_id,
                    header.llm_provider_config_id,
                ),
            ),
            email=await _resolve_optional_provider(
                header.organization_id,
                header.email_provider_config_id,
                service._resolve_email_revision,
            ),
            webrtc=await _resolve_optional_provider(
                header.organization_id,
                header.webrtc_provider_config_id,
                service._resolve_webrtc_revision,
            ),
            reranking=await _resolve_optional_provider(
                header.organization_id,
                header.reranking_provider_config_id,
                service._resolve_reranking_revision,
            ),
            memory=await _resolve_optional_provider(
                header.organization_id,
                header.memory_provider_config_id,
                service._resolve_memory_revision,
            ),
            file_upload_embedding=await _resolve_optional_provider(
                header.organization_id,
                header.file_upload_embedding_provider_config_id,
                service._resolve_file_upload_embedding_revision,
            ),
        )
        if refs.email is None and await service._has_email_tools(
            header.id,
            header.organization_id,
        ):
            raise InvalidAgentDefinitionError(
                "Assign a ready email config before publishing an agent "
                "with the send_email tool."
            )
        if refs.memory is None and await service._has_memory_tools(
            header.id,
            header.organization_id,
        ):
            raise InvalidAgentDefinitionError(
                "Assign a ready memory config before publishing an agent "
                "with memory tools."
            )
        if header.allow_file_uploads and not await service._has_knowledge_tools(
            header.id,
            header.organization_id,
        ):
            raise InvalidAgentDefinitionError(
                "Assign kb_query, kb_write_destinations, and kb_write before "
                "publishing an agent with file uploads."
            )
        return refs

    async def _resolve_voice_config(
        self, header: AgentsModel
    ) -> VoiceConfigPublication | None:
        from eylo.modules.agents.exceptions import AgentVoiceConfigError
        from eylo.modules.voice.exceptions import (
            VoiceConfigConflict,
            VoiceConfigNotFound,
        )
        from eylo.modules.voice.services.voice_configs import VoiceConfigService

        if header.voice_config_id is None:
            if header.voice_config_revision is not None:
                raise AgentVoiceConfigError("Agent Voice Config binding is incomplete.")
            return None
        if header.voice_config_revision is None:
            raise AgentVoiceConfigError("Agent Voice Config binding is incomplete.")
        if _enum_value(header.kind) == AgentKind.BACKGROUND.value:
            raise AgentVoiceConfigError(
                "Background Agents cannot publish with a Voice Config."
            )
        try:
            return await VoiceConfigService(self._db).resolve_for_publish(
                organization_id=header.organization_id,
                voice_config_id=header.voice_config_id,
                expected_revision=header.voice_config_revision,
            )
        except (VoiceConfigNotFound, VoiceConfigConflict, ValueError) as error:
            raise AgentVoiceConfigError(str(error)) from error

    async def _tool_refs(self, header: AgentsModel) -> list[tuple[UUID, int]]:
        rows = await self._db.scalars(
            select(AgentToolMappingModal).where(
                AgentToolMappingModal.agent_id == header.id,
                AgentToolMappingModal.organization_id == header.organization_id,
                AgentToolMappingModal.tool_id.is_not(None),
                AgentToolMappingModal.deleted.is_(False),
            )
        )
        refs = [revisioned_tool_ref(row) for row in rows.all()]
        if refs:
            tools = await ToolService(self._db).list_exact(
                refs=refs,
                organization_id=header.organization_id,
            )
            if len(tools) != len(refs):
                raise InvalidAgentDefinitionError(
                    "Every agent tool grant must resolve to an exact available revision."
                )
            model_names = [tool.llm_config.name for tool in tools]
            if any(not name.strip() for name in model_names):
                raise InvalidAgentDefinitionError(
                    "Every tool in one agent revision requires a non-empty "
                    "model-visible name."
                )
            if len(model_names) != len(set(model_names)):
                raise InvalidAgentDefinitionError(
                    "Every tool in one agent revision requires a unique "
                    "model-visible name."
                )
        return refs

    async def _curated_tool_refs(self, header: AgentsModel) -> list[UUID]:
        """Curated tool grants on the draft, to copy into the new revision."""
        rows = await self._db.scalars(
            select(AgentToolMappingModal).where(
                AgentToolMappingModal.agent_id == header.id,
                AgentToolMappingModal.organization_id == header.organization_id,
                AgentToolMappingModal.curated_tool_id.is_not(None),
                AgentToolMappingModal.deleted.is_(False),
            )
        )
        return [curated_tool_ref(row) for row in rows.all()]

    async def _background_refs(
        self,
        header: AgentsModel,
    ) -> list[tuple[UUID, int]]:
        rows = await self._db.scalars(
            select(AgentBackgroundAgentModel).where(
                AgentBackgroundAgentModel.agent_id == header.id,
                AgentBackgroundAgentModel.enabled.is_(True),
                AgentBackgroundAgentModel.deleted.is_(False),
            )
        )
        refs: list[tuple[UUID, int]] = []
        for attachment in rows.all():
            target = await self._get_header(
                header.organization_id,
                attachment.background_agent_id,
            )
            if _enum_value(target.kind) != AgentKind.BACKGROUND.value:
                raise InvalidAgentDefinitionError(
                    "Enabled background attachments must reference background agents."
                )
            target_revision = _header_state(target).revision_for_new_work()
            await self.get_revision(
                organization_id=header.organization_id,
                agent_id=target.id,
                revision=target_revision,
            )
            refs.append((target.id, target_revision))
        return refs


def _header_state(row: AgentsModel) -> DefinitionHeaderState:
    return DefinitionHeaderState(
        lifecycle=DefinitionLifecycle(row.lifecycle),
        published_revision=row.published_revision,
        draft_version=row.draft_version,
        draft_dirty=row.draft_dirty,
    )


def _apply_header_state(row: AgentsModel, state: DefinitionHeaderState) -> None:
    row.lifecycle = state.lifecycle.value
    row.published_revision = state.published_revision
    row.draft_version = state.draft_version
    row.draft_dirty = state.draft_dirty


def _revision_state(row: AgentRevisionModel) -> PublishedRevisionState:
    return PublishedRevisionState(
        published_at=row.published_at,
        availability=RevisionAvailability(row.availability),
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
        revocation_reason=row.revocation_reason,
        cancellation_requested_at=row.cancellation_requested_at,
    )


async def _resolve_optional_provider(
    organization_id: UUID,
    config_id: UUID | None,
    resolve_revision: Callable[[UUID, UUID], Awaitable[int]],
) -> AgentProviderReference | None:
    if config_id is None:
        return None
    return AgentProviderReference(
        config_id=config_id,
        revision=await resolve_revision(organization_id, config_id),
    )


def _voice_ref(
    config_id: UUID | None,
    revision: int | None,
    capability: Capability,
) -> tuple[UUID | None, int | None]:
    # Common Voice Configs may retain selections that are inactive in the
    # chosen runtime mode. Publication marks active refs by resolving a
    # revision; only those exact pairs belong in the immutable Agent row.
    if revision is None:
        return None, None
    if config_id is None:
        raise InvalidAgentDefinitionError(
            f"Published {capability.value} voice provider revision has no config ID."
        )
    return provider_pair(AgentProviderReference(config_id=config_id, revision=revision))


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


__all__ = ["AgentRevisionService"]
