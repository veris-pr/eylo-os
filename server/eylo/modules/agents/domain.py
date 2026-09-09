"""Typed contracts for immutable executable agent definitions."""

from __future__ import annotations

from typing import Protocol, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    model_validator,
)

from eylo.common.revisions import DefinitionRef
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.templates.domain import TemplateConsumerKind, TemplateSegment
from eylo.modules.tools.schemas.indb import ToolInDb
from eylo.modules.voice.schemas.runtime import VoiceConfigSnapshot


class InvalidAgentDefinitionError(ValueError):
    """Raised when a draft cannot become a complete executable revision."""


class InvalidSwarmDefinitionError(ValueError):
    """Raised when a swarm draft cannot become an executable topology."""


class SwarmNotFoundError(LookupError):
    """Raised for missing or foreign swarm identity without disclosing which."""


class SwarmMemberNotFoundError(LookupError):
    """Raised when an organization-owned agent/member cannot be selected."""


class ResolvedExecutableAgent(BaseModel):
    """One exact agent revision ready for any supported runtime."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    ref: DefinitionRef
    agent: AgentInDb
    consumer_kind: TemplateConsumerKind
    system_prompt: str | None
    prompt_segments: tuple[TemplateSegment, ...]
    tools: tuple[ToolInDb, ...]
    background_agents: tuple[DefinitionRef, ...]
    voice_config: VoiceConfigSnapshot | None

    @model_validator(mode="after")
    def validate_exact_revision(self) -> Self:
        if self.agent.id != self.ref.definition_id:
            raise InvalidAgentDefinitionError(
                "Resolved agent identity does not match its exact revision ref."
            )
        if self.agent.published_revision != self.ref.revision:
            raise InvalidAgentDefinitionError(
                "Resolved agent payload does not match its exact revision ref."
            )
        return self

    def with_tools(self, tools: tuple[ToolInDb, ...]) -> Self:
        """Revalidate a runtime projection after the consumer filters its tools."""
        return type(self)(
            ref=self.ref,
            agent=self.agent,
            consumer_kind=self.consumer_kind,
            system_prompt=self.system_prompt,
            prompt_segments=self.prompt_segments,
            tools=tools,
            background_agents=self.background_agents,
            voice_config=self.voice_config,
        )


class ResolveExecutableAgent(Protocol):
    """Port shared by conversation, voice, background, sandbox, and schedule runs."""

    async def resolve_exact(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        revision: int,
        consumer_kind: TemplateConsumerKind,
    ) -> ResolvedExecutableAgent: ...

    async def resolve_for_new_work(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        consumer_kind: TemplateConsumerKind,
    ) -> ResolvedExecutableAgent: ...


class ResolvedSwarmMember(BaseModel):
    """One exact executable agent authorized by a topology revision."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    executable_agent: ResolvedExecutableAgent
    description: str | None = None


class ResolvedSwarmTopology(BaseModel):
    """One immutable swarm topology plus its exact executable members."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    ref: DefinitionRef
    organization_id: UUID
    name: str
    slug: str
    description: str | None
    members: tuple[ResolvedSwarmMember, ...]

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        if not self.members:
            raise InvalidSwarmDefinitionError(
                "A published swarm topology requires at least one member."
            )
        member_ids = [
            member.executable_agent.ref.definition_id for member in self.members
        ]
        if len(member_ids) != len(set(member_ids)):
            raise InvalidSwarmDefinitionError(
                "A swarm topology cannot contain the same agent twice."
            )
        if any(
            member.executable_agent.agent.organization_id != self.organization_id
            for member in self.members
        ):
            raise InvalidSwarmDefinitionError(
                "Every swarm member must belong to the topology organization."
            )
        return self

    def member_by_agent_id(self, agent_id: UUID) -> ResolvedSwarmMember | None:
        return next(
            (
                member
                for member in self.members
                if member.executable_agent.ref.definition_id == agent_id
            ),
            None,
        )

    def member_by_slug(self, slug: str) -> ResolvedSwarmMember | None:
        return next(
            (
                member
                for member in self.members
                if member.executable_agent.agent.slug == slug
            ),
            None,
        )


class ResolveExecutableSwarm(Protocol):
    """Port for current-published selection and exact topology resolution."""

    async def resolve_exact(
        self,
        *,
        organization_id: UUID,
        swarm_id: UUID,
        revision: int,
        consumer_kind: TemplateConsumerKind,
    ) -> ResolvedSwarmTopology: ...

    async def resolve_for_new_work(
        self,
        *,
        organization_id: UUID,
        swarm_id: UUID,
        consumer_kind: TemplateConsumerKind,
    ) -> ResolvedSwarmTopology: ...


__all__ = [
    "InvalidAgentDefinitionError",
    "InvalidSwarmDefinitionError",
    "ResolveExecutableAgent",
    "ResolveExecutableSwarm",
    "ResolvedExecutableAgent",
    "ResolvedSwarmMember",
    "ResolvedSwarmTopology",
    "SwarmMemberNotFoundError",
    "SwarmNotFoundError",
]
