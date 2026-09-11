"""Bounded agent lifecycle event production.

Lifecycle events are lossy UI deltas. This adapter projects only stable IDs and
correlation metadata so a large conversation context can never make the event
silently exceed the ephemeral event limit.
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.base import (
    AgentLifecycleEvent,
    AgentLifecycleOutcome,
    AgentResponseCompleteEvent,
)
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.participants import ParticipantKind


class _AgentLifecycleRun(BaseModel):
    """Correlate all emitted stages of one request with the same run identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    run_id: UUID
    started_at: datetime.datetime


class AgentLifecycleEmitter:
    """Emit one monotonic, request-scoped lifecycle stream at a time."""

    def __init__(self) -> None:
        self._run: _AgentLifecycleRun | None = None
        self._sequence = 0

    def emit(
        self,
        event_type: type[AgentLifecycleEvent],
        *,
        context: ConversationContext,
        request_id: UUID,
        message_id: UUID | None = None,
        outcome: AgentLifecycleOutcome | None = None,
    ) -> None:
        run = self._start_request_if_needed(request_id)
        self._sequence += 1

        terminal_fields: dict[str, AgentLifecycleOutcome] = {}
        if event_type is AgentResponseCompleteEvent:
            if outcome is None:
                raise ValueError("Terminal agent lifecycle event requires an outcome.")
            terminal_fields["outcome"] = outcome
        elif outcome is not None:
            raise ValueError("Only terminal agent lifecycle events accept an outcome.")

        emit_ephemeral(
            event_type(
                organization_id=context.conversation.organization_id,
                conversation_id=context.conversation.id,
                contact_ids=tuple(
                    participant.entity_id
                    for participant in context.participants
                    if participant.entity_kind == ParticipantKind.CONTACT
                ),
                request_id=request_id,
                message_id=message_id,
                run_id=run.run_id,
                run_started_at=run.started_at,
                sequence=self._sequence,
                **terminal_fields,
            )
        )

    def _start_request_if_needed(self, request_id: UUID) -> _AgentLifecycleRun:
        if self._run is None or self._run.request_id != request_id:
            self._run = _AgentLifecycleRun(
                request_id=request_id,
                run_id=uuid4(),
                started_at=datetime.datetime.now(datetime.UTC),
            )
            self._sequence = 0
        return self._run
