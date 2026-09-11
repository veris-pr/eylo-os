"""Project correlated agent lifecycle events onto WebSocket UI deltas.

These handlers are presentation-only. Runtime work and terminal persistence
complete before the corresponding event is emitted. Each payload carries a
request ID, run ID, run start time, and monotonic sequence so clients can reject
late or reordered delivery.
"""

import logging
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_serializer

from eylo.events.schema.py_events.base import (
    AgentLifecycleEvent,
    AgentLifecycleOutcome,
    AgentProcessingEvent,
    AgentResponseCompleteEvent,
    AgentRunInferenceEvent,
    AgentRunToolEvent,
    AgentToolResponseEvent,
)
from eylo.listeners.py_events.utils import broadcast_to_conversation_contacts
from eylo.pipelines.websocket.schemas import WsEventAction

logger = logging.getLogger(__name__)


class AgentLifecycleStatus(StrEnum):
    """Widget-owned spellings for the six projected run stages."""

    THINKING = "thinking"
    PROCESSING = "processing"
    TOOL_EXECUTING = "tool_executing"
    TOOL_COMPLETED = "tool_completed"
    COMPLETE = "complete"
    ERROR = "error"


class AgentLifecycleDelta(BaseModel):
    """Correlated presentation data; never contains tool inputs or results."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    conversation_id: UUID
    message_id: UUID | None
    request_id: UUID
    run_id: UUID
    run_started_at: datetime
    sequence: int = Field(ge=1)
    terminal: bool
    status: AgentLifecycleStatus
    message: str | None = None
    outcome: AgentLifecycleOutcome | None = None

    @field_serializer("run_started_at")
    def serialize_run_started_at(self, value: datetime) -> str:
        """Retain the existing explicit UTC offset rather than changing it to Z."""
        return value.isoformat()


def _lifecycle_payload(
    event: AgentLifecycleEvent,
    *,
    status: AgentLifecycleStatus,
    message: str | None = None,
) -> dict[str, JsonValue]:
    delta = AgentLifecycleDelta(
        conversation_id=event.conversation_id,
        message_id=event.message_id,
        request_id=event.request_id,
        run_id=event.run_id,
        run_started_at=event.run_started_at,
        sequence=event.sequence,
        terminal=isinstance(event, AgentResponseCompleteEvent),
        status=status,
        message=message,
        outcome=(
            event.outcome if isinstance(event, AgentResponseCompleteEvent) else None
        ),
    )
    omitted_fields: set[str] = set()
    if not message:
        omitted_fields.add("message")
    if not isinstance(event, AgentResponseCompleteEvent):
        omitted_fields.add("outcome")
    return delta.model_dump(mode="json", exclude=omitted_fields)


async def _broadcast(
    event: AgentLifecycleEvent,
    *,
    kind: WsEventAction,
    status: AgentLifecycleStatus,
    message: str | None,
) -> None:
    await broadcast_to_conversation_contacts(
        contact_ids=event.contact_ids,
        organization_id=event.organization_id,
        conversation_id=event.conversation_id,
        kind=kind,
        payload=_lifecycle_payload(event, status=status, message=message),
        event_name=status.replace("_", " ").title(),
    )


async def handle_agent_thinking(event: AgentRunInferenceEvent) -> None:
    """Broadcast that the current run entered LLM inference."""
    await _broadcast(
        event,
        kind=WsEventAction.AGENT_THINKING,
        status=AgentLifecycleStatus.THINKING,
        message="Thinking...",
    )


async def handle_agent_processing(event: AgentProcessingEvent) -> None:
    """Broadcast that the agent accepted and started processing the request."""
    await _broadcast(
        event,
        kind=WsEventAction.AGENT_PROCESSING,
        status=AgentLifecycleStatus.PROCESSING,
        message="Processing...",
    )


async def handle_tool_executing(event: AgentRunToolEvent) -> None:
    """Broadcast tool executing event when agent starts a tool call.

    Shows users which tool the agent is using in real-time.
    """
    await _broadcast(
        event,
        kind=WsEventAction.TOOL_EXECUTING,
        status=AgentLifecycleStatus.TOOL_EXECUTING,
        message="Using tools...",
    )


async def handle_tool_completed(event: AgentToolResponseEvent) -> None:
    """Broadcast tool completed event when tool execution finishes.

    Signals to the widget that the tool has finished and agent is processing results.
    """
    await _broadcast(
        event,
        kind=WsEventAction.TOOL_COMPLETED,
        status=AgentLifecycleStatus.TOOL_COMPLETED,
        message="Analyzing results...",
    )


async def handle_agent_response_complete(event: AgentResponseCompleteEvent) -> None:
    """Broadcast the completed or failed terminal state for the correlated run."""
    failed = event.outcome is AgentLifecycleOutcome.FAILED
    await _broadcast(
        event,
        kind=WsEventAction.AGENT_RESPONSE_COMPLETE,
        status=AgentLifecycleStatus.ERROR if failed else AgentLifecycleStatus.COMPLETE,
        message="The agent could not complete this request." if failed else None,
    )
