"""Map existing Eylo domain objects into framework primitives.

These helpers are deliberately small and one-way. They let the new framework
consume today's DB-backed conversation state without changing existing runners.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, StrictBool, StrictStr, TypeAdapter

from eylo.framework.agents.agent import AgentSpec
from eylo.framework.agents.common import FrameworkMetadata
from eylo.framework.agents.context import RunInput, RunMessage
from eylo.framework.agents.handoff import HandoffSpec
from eylo.framework.agents.history import ToolResultMessageData
from eylo.framework.agents.model import ModelSettings
from eylo.framework.agents.tool import (
    ToolExecutionMode,
    ToolIdentity,
    ToolKind,
    ToolResult,
    ToolSpec,
)
from eylo.modules.agents.models import AgentStatus
from eylo.modules.conversations.schemas.conversations import HandoffTool
from eylo.modules.conversations.schemas.message_content import (
    AssistantMessageContent,
    SystemMessageContent,
    TextMessageContentBlocks,
    UserMessageContent,
    WidgetResponseMessageContent,
)
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageKind,
    MessageMeta,
)
from eylo.modules.tools.models import ToolExecutionMode as PlatformToolExecutionMode
from eylo.modules.tools.models import ToolKind as PlatformToolKind

if TYPE_CHECKING:
    from eylo.modules.agents.schemas.indb import AgentInDb
    from eylo.modules.conversations.schemas.conversations import ConversationContext
    from eylo.modules.conversations.schemas.messages import MessageInDb
    from eylo.modules.tools.schemas.indb import ToolInDb


class ExistingAgentMetadata(FrameworkMetadata):
    """Metadata carried from existing agent records into framework specs."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    slug: StrictStr
    status: AgentStatus = Field(strict=True)


class ExistingToolMetadata(FrameworkMetadata):
    """Identity shared by persisted and code-defined platform tools."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    id: UUID
    slug: StrictStr
    mcp_server_id: UUID | None = None


class ExistingRevisionedToolMetadata(ExistingToolMetadata):
    """Identity for a persisted tool definition pinned to one revision."""

    revision: int = Field(strict=True, gt=0)


class ExistingCodeDefinedToolMetadata(ExistingToolMetadata):
    """Identity for executable code whose deployed catalog is authoritative."""

    definition_key: StrictStr = Field(min_length=1, pattern=r"\S")


class ExistingHandoffToolMetadata(ExistingToolMetadata):
    """Generated handoff identity; execution rechecks the pinned swarm topology."""

    target_agent_revision: int = Field(strict=True, gt=0)


class ExistingRunInputMetadata(FrameworkMetadata):
    """Framework metadata derived from the current conversation context."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    conversation_id: UUID
    organization_id: UUID | None = None
    external_id: StrictStr | None = None
    request_id: UUID | None = None
    widget_interfaces_enabled: StrictBool
    transient_tool_message_count: int = Field(default=0, strict=True, ge=0)


class ExistingToolCallMetadata(FrameworkMetadata):
    """Framework metadata for a persisted tool-use message."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    id: ToolIdentity
    name: ToolIdentity
    arguments: dict[str, JsonValue]


class ExistingToolResultMetadata(FrameworkMetadata):
    """Framework metadata for a persisted tool-result message."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    tool_call_id: ToolIdentity
    name: ToolIdentity | None = None
    is_error: StrictBool
    content: JsonValue


_TOOL_RESULT_BATCH = TypeAdapter(tuple[ExistingToolResultMetadata, ...])


class ExistingRunMessageMetadata(FrameworkMetadata):
    """Framework metadata derived from a persisted conversation message."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    kind: MessageKind
    content_kind: MessageContentKind
    request_id: UUID | None = None
    meta: MessageMeta
    content_blocks: TextMessageContentBlocks | None = None
    widget_response: WidgetResponseMessageContent | None = None
    tool_call: ExistingToolCallMetadata | None = None
    tool_result: ExistingToolResultMetadata | None = None
    tool_results: tuple[ExistingToolResultMetadata, ...] | None = None


class AgentSpecContext(Protocol):
    """Small platform context required to build one framework agent spec."""

    @property
    def primary_agent(self) -> AgentInDb | None: ...

    @property
    def handoff_agents(self) -> Sequence[AgentInDb] | None: ...

    def get_tools(self) -> Sequence[ToolInDb]: ...


def agent_spec_from_context(context: AgentSpecContext) -> AgentSpec:
    """Build an ``AgentSpec`` from a fully hydrated conversation context."""
    if context.primary_agent is None:
        raise ValueError("ConversationContext has no primary_agent.")

    tools = tuple(tool_spec_from_indb(tool) for tool in context.get_tools())
    handoffs = tuple(
        HandoffSpec(
            name=f"transfer_to_{agent.slug}",
            description=agent.description or f"Transfer to {agent.name}.",
            target_agent_id=agent.id,
        )
        for agent in context.handoff_agents or ()
    )

    return agent_spec_from_indb(context.primary_agent, tools=tools, handoffs=handoffs)


def agent_spec_from_indb(
    agent: AgentInDb,
    *,
    tools: tuple[ToolSpec, ...] = (),
    handoffs: tuple[HandoffSpec, ...] = (),
) -> AgentSpec:
    """Build a framework agent config from an existing ``AgentInDb``."""
    if agent.status is not AgentStatus.ACTIVE:
        raise ValueError("Only published agents can be executed.")
    if (
        agent.llm_provider_config_id is None
        or agent.llm_provider_config_revision is None
    ):
        raise ValueError("Published agent is missing pinned LLM authority.")
    overrides = agent.llm_overrides
    return AgentSpec(
        id=agent.id,
        organization_id=agent.organization_id,
        name=agent.name,
        instructions=agent.description or agent.name,
        model_settings=ModelSettings(
            provider_config_id=agent.llm_provider_config_id,
            provider_config_revision=agent.llm_provider_config_revision,
            model=overrides.model.value if overrides.model is not None else None,
            max_tokens=overrides.max_tokens,
            temperature=overrides.temperature,
            top_p=overrides.top_p,
            top_k=overrides.top_k,
            stop_sequences=overrides.stop_sequences,
        ),
        tools=tools,
        handoffs=handoffs,
        metadata=ExistingAgentMetadata(
            slug=agent.slug,
            status=agent.status,
        ),
    )


def tool_spec_from_indb(tool: ToolInDb) -> ToolSpec:
    """Build a framework tool config from an existing ``ToolInDb``."""
    model_name = tool.llm_config.name
    if not model_name.strip():
        raise ValueError(f"Tool {tool.id} has no model-visible name.")
    return ToolSpec(
        name=model_name,
        description=tool.llm_config.description or tool.description,
        kind=_tool_kind_from_existing(tool.kind),
        input_schema=tool.get_input_schema(),
        execution_mode=_tool_execution_mode_from_existing(tool),
        metadata=_tool_metadata_from_existing(tool),
    )


def run_input_from_context(
    context: ConversationContext, *, request_id: UUID | None = None
) -> RunInput:
    """Build LLM-visible input from a hydrated conversation context."""
    if context.primary_agent is None:
        raise ValueError("ConversationContext has no primary_agent.")

    agent = agent_spec_from_context(context)
    messages = tuple(
        run_message_from_indb(message) for message in context.get_messages()
    )

    return RunInput(
        instructions=context.system_prompt or agent.instructions,
        messages=messages,
        tools=agent.tools,
        metadata=ExistingRunInputMetadata(
            conversation_id=context.conversation.id,
            organization_id=context.conversation.organization_id,
            request_id=request_id,
            external_id=context.external_id,
            widget_interfaces_enabled=context.widget_interfaces_enabled,
        ),
    )


def run_message_from_indb(message: MessageInDb) -> RunMessage:
    """Convert an existing persisted message into framework-visible input."""
    tool_call_metadata: ExistingToolCallMetadata | None = None
    tool_result_metadata: ExistingToolResultMetadata | None = None
    tool_results_metadata: tuple[ExistingToolResultMetadata, ...] | None = None
    content_blocks: TextMessageContentBlocks | None = None
    widget_response: WidgetResponseMessageContent | None = None

    if message.kind == MessageKind.TOOL_USE:
        parsed = message.get_tool_use_content()
        tool_call_metadata = ExistingToolCallMetadata(
            id=parsed.content.id,
            name=parsed.content.name,
            arguments=parsed.content.input,
        )
    elif message.kind == MessageKind.TOOL_RESULT:
        parsed = message.get_tool_result_content()
        results = tuple(
            ExistingToolResultMetadata(
                tool_call_id=result.tool_use_id,
                name=result.name,
                is_error=result.is_error,
                content=result.content,
            )
            for result in parsed.content
        )
        if len(results) == 1:
            tool_result_metadata = results[0]
        else:
            tool_results_metadata = results
    else:
        parsed = message.get_parsed_content()
        if isinstance(parsed, WidgetResponseMessageContent):
            widget_response = parsed
        elif isinstance(
            parsed,
            UserMessageContent | AssistantMessageContent | SystemMessageContent,
        ):
            content_blocks = parsed.content

    metadata = ExistingRunMessageMetadata(
        kind=message.kind,
        content_kind=message.content_kind,
        request_id=message.request_id,
        meta=message.meta or MessageMeta(),
        content_blocks=content_blocks,
        widget_response=widget_response,
        tool_call=tool_call_metadata,
        tool_result=tool_result_metadata,
        tool_results=tool_results_metadata,
    )

    return RunMessage(
        id=message.id,
        role=_message_role(message.kind),
        content=message.get_text_content() or "",
        metadata=metadata,
    )


def tool_results_from_run_message(
    message: RunMessage,
) -> tuple[ExistingToolResultMetadata, ...] | None:
    """Decode persisted batches and existing single-result live/framework messages.

    None means a non-result message. An empty tuple preserves an empty result
    row for the shared history validator to reject, rather than inventing text.
    """
    single = message.metadata.get("tool_result")
    batch = message.metadata.get("tool_results")
    if batch is not None:
        if single is not None:
            raise ValueError(
                "Run message contains both singular and batched tool results."
            )
        return _TOOL_RESULT_BATCH.validate_python(batch)
    if single is not None:
        if isinstance(single, ToolResultMessageData):
            return (
                ExistingToolResultMetadata(
                    tool_call_id=single.tool_call_id,
                    name=single.name,
                    is_error=single.is_error,
                    content=single.content,
                ),
            )
        if isinstance(single, ToolResult):
            return (
                ExistingToolResultMetadata(
                    tool_call_id=single.tool_call_id,
                    is_error=single.is_error,
                    content=single.content,
                ),
            )
        return (ExistingToolResultMetadata.model_validate(single),)
    return None


# Platform enums are translated here; the standalone framework never imports them.
_PLATFORM_TO_FRAMEWORK_KIND = {
    PlatformToolKind.SYSTEM: ToolKind.SYSTEM,
    PlatformToolKind.LOCAL: ToolKind.LOCAL,
    # MCP is an external call as far as the agent loop is concerned. It does not
    # get its own framework value: the framework describes tool *families*, not
    # transports, and teaching it one protocol name would invite the next one.
    # Which transport runs it is decided by the platform's own dispatch.
    PlatformToolKind.MCP: ToolKind.API,
    # Curated tools reach a vendor, but the agent loop calls them exactly like
    # any other in-process tool. Same reasoning as MCP above: the framework
    # describes families, and dispatch decides the transport.
    PlatformToolKind.CURATED: ToolKind.LOCAL,
}

_PLATFORM_TO_FRAMEWORK_EXECUTION_MODE = {
    PlatformToolExecutionMode.AUTO: ToolExecutionMode.AUTO,
    PlatformToolExecutionMode.REQUIRES_APPROVAL: ToolExecutionMode.REQUIRES_APPROVAL,
    PlatformToolExecutionMode.DISABLED: ToolExecutionMode.DISABLED,
}


def _tool_metadata_from_existing(tool: ToolInDb) -> ExistingToolMetadata:
    """Distinguish tool revisions, deployed code and generated agent handoffs."""
    if isinstance(tool, HandoffTool):
        return ExistingHandoffToolMetadata(
            id=tool.id,
            slug=tool.slug,
            mcp_server_id=tool.mcp_server_id,
            target_agent_revision=tool.target_agent_revision,
        )
    if tool.published_revision is not None:
        if tool.kind is PlatformToolKind.CURATED:
            raise ValueError("A curated tool cannot carry a persisted revision.")
        return ExistingRevisionedToolMetadata(
            id=tool.id,
            slug=tool.slug,
            mcp_server_id=tool.mcp_server_id,
            revision=tool.published_revision,
        )

    if tool.kind is PlatformToolKind.CURATED:
        if not tool.wire_id:
            raise ValueError("A curated tool requires its registry wire identity.")
        definition_key = tool.wire_id
    elif tool.kind is PlatformToolKind.SYSTEM:
        definition_key = tool.slug
    else:
        raise ValueError(
            f"Tool kind {tool.kind.value!r} requires a published revision."
        )

    return ExistingCodeDefinedToolMetadata(
        id=tool.id,
        slug=tool.slug,
        mcp_server_id=tool.mcp_server_id,
        definition_key=definition_key,
    )


def _tool_kind_from_existing(kind: PlatformToolKind) -> ToolKind:
    """Map one supported stored tool kind onto the framework vocabulary."""
    if not isinstance(kind, PlatformToolKind):
        raise ValueError("Stored tool kind must use the platform enum.")
    return _PLATFORM_TO_FRAMEWORK_KIND[kind]


def _tool_execution_mode_from_existing(tool: ToolInDb) -> ToolExecutionMode:
    """Map the persisted exact policy onto the framework contract."""
    mode = tool.execution_mode
    if not isinstance(mode, PlatformToolExecutionMode):
        raise ValueError("Stored tool execution mode must use the platform enum.")
    return _PLATFORM_TO_FRAMEWORK_EXECUTION_MODE[mode]


def _message_role(kind: MessageKind) -> str:
    if kind == MessageKind.USER:
        return "user"
    if kind == MessageKind.ASSISTANT:
        return "assistant"
    if kind == MessageKind.SYSTEM:
        return "system"
    if kind == MessageKind.TOOL_RESULT:
        return "tool"
    return "assistant"
