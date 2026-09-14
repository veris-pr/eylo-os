"""Typed runtime state shared by conversation, durable, and live-voice runners."""

from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema

from eylo.common.contracts.tool_availability import ToolAvailabilityFacts
from eylo.framework.agents.common import JsonObject
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.messages import MessageInDb
from eylo.modules.tools.schemas.indb import ToolInDb
from eylo.pipelines.outbound.durable_execution import (
    CommandStepContext,
    DurableStepContext,
)
from eylo.pipelines.voice.live_buffer import LiveVoiceBufferIdentity


class AgentExecutionScope(BaseModel):
    """Non-conversation authority; its ID never denotes a conversation DB row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    organization_id: UUID
    swarm_id: None = None
    swarm_revision: None = None
    channel: None = None
    meta: JsonObject = Field(default_factory=dict)


class AgentExecutionParticipant(BaseModel):
    """Principal or published agent identity, not a persisted participant row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    entity_id: str
    agent_id: UUID | None = None
    agent_revision: int | None = None


class AgentExecutionContext(BaseModel):
    """Hydrated tool/model context for work without a persisted conversation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    conversation: AgentExecutionScope
    primary_agent: AgentInDb
    tools: list[ToolInDb]
    system_prompt: str
    principal_participant: AgentExecutionParticipant
    agent_participant: AgentExecutionParticipant
    messages: list[MessageInDb] = Field(default_factory=list)
    handoff_agents: tuple[AgentInDb, ...] = ()
    widget_interfaces_enabled: bool = False
    external_id: str | None = None
    tool_availability: ToolAvailabilityFacts = Field(
        default_factory=ToolAvailabilityFacts
    )

    def get_tools(self) -> list[ToolInDb]:
        from eylo.pipelines.system_tools.availability import (
            filter_available_system_tools,
        )

        return filter_available_system_tools(self.tools, self.tool_availability)

    def get_messages(self) -> list[MessageInDb]:
        return self.messages

    def get_primary_contact(self) -> AgentExecutionParticipant:
        return self.principal_participant

    def get_primary_agent(self) -> AgentExecutionParticipant:
        return self.agent_participant


PlatformExecutionContext = ConversationContext | AgentExecutionContext
ContextT = TypeVar("ContextT", bound=PlatformExecutionContext)


class PlatformRunState(BaseModel, Generic[ContextT]):
    """Live application state, excluded from framework snapshots.

    Command IDs refer to their product-owned persisted rows, never raw content.
    A live voice command can execute a step without acquiring durable event-wait
    authority. Only ``durable_context`` supplies that stronger contract.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    conversation_context: ContextT = Field(repr=False, exclude=True)
    agent_run_id: UUID | None = None
    durable_context: SkipJsonSchema[InstanceOf[DurableStepContext] | None] = Field(
        default=None, repr=False, exclude=True
    )
    command_context: SkipJsonSchema[InstanceOf[CommandStepContext] | None] = Field(
        default=None, repr=False, exclude=True
    )
    live_voice_identity: LiveVoiceBufferIdentity | None = None
    command_ids: dict[str, UUID] = Field(default_factory=dict)

    @property
    def step_context(self) -> CommandStepContext | None:
        if self.durable_context is not None:
            return self.durable_context
        return self.command_context


def execution_context_from(local_context: object) -> PlatformExecutionContext:
    """Resolve known platform context types without duck-typed casts or dict keys."""
    if isinstance(local_context, PlatformRunState):
        return local_context.conversation_context
    if isinstance(local_context, (ConversationContext, AgentExecutionContext)):
        return local_context
    raise ValueError("Platform execution requires a typed execution context.")
