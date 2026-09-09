"""Pinned handoff outcomes and their conversation/voice metadata projections."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    model_validator,
)

from eylo.framework.agents.common import FrameworkMetadata
from eylo.framework.agents.tool import (
    ToolCompletionMetadata,
    ToolCompletionMode,
    ToolResult,
)
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.participants import (
    ParticipantInDb,
    ParticipantKind,
)


class HandoffState(str, Enum):
    """One execution outcome; existing wire flags are boundary projections."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    LIMIT_REACHED = "limit_reached"
    LOOP_DETECTED = "loop_detected"
    EXECUTION_FAILED = "execution_failed"

    @property
    def circuit_breaker_triggered(self) -> bool:
        return self in (
            HandoffState.LIMIT_REACHED,
            HandoffState.LOOP_DETECTED,
            HandoffState.EXECUTION_FAILED,
        )


def require_handoff_target(
    state: HandoffState,
    agent: AgentInDb | None,
    participant: ParticipantInDb | None,
) -> None:
    """Check reference agreement; pinned topology authorization remains in dispatch."""
    if state is not HandoffState.SUCCEEDED:
        if agent is not None or participant is not None:
            raise ValueError("A refused handoff cannot carry an executable target.")
        return
    if agent is None or participant is None:
        raise ValueError("A successful handoff requires an exact target participant.")
    if (
        not isinstance(agent.id, UUID)
        or not isinstance(participant.id, UUID)
        or participant.entity_kind is not ParticipantKind.AGENT
        or participant.entity_id != str(agent.id)
        or participant.agent_id != agent.id
        or type(participant.agent_revision) is not int
        or participant.agent_revision <= 0
        or type(agent.published_revision) is not int
        or participant.agent_revision != agent.published_revision
    ):
        raise ValueError("Handoff target agent and participant revisions differ.")


class HandoffOutcome(BaseModel):
    """Detached result of the pinned switch, never authority to pick another target."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    content: StrictStr
    source_agent: AgentInDb
    requested_input: StrictStr | None = None
    target_agent: AgentInDb | None = None
    target_participant: ParticipantInDb | None = None
    state: HandoffState = HandoffState.REJECTED

    @model_validator(mode="after")
    def validate_target(self) -> HandoffOutcome:
        require_handoff_target(self.state, self.target_agent, self.target_participant)
        return self

    @property
    def succeeded(self) -> bool:
        return self.state is HandoffState.SUCCEEDED

    @property
    def circuit_breaker_triggered(self) -> bool:
        return self.state.circuit_breaker_triggered

    @property
    def handoff_loop_detected(self) -> bool:
        return self.state is HandoffState.LOOP_DETECTED


HandoffRevision = Annotated[int, Field(strict=True, gt=0)]


class HandoffMessageMetadata(FrameworkMetadata):
    """Existing public handoff summary shared by text and realtime transcripts."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    handoff_outcome: Literal[HandoffState.SUCCEEDED, HandoffState.REJECTED]
    swarm_id: UUID | None
    swarm_revision: HandoffRevision | None
    source_agent_id: UUID | None
    source_agent_revision: HandoffRevision | None
    source_participant_id: UUID | None
    target_agent_id: UUID | None
    target_agent_revision: HandoffRevision | None
    target_participant_id: UUID | None

    @model_validator(mode="after")
    def validate_references(self) -> HandoffMessageMetadata:
        target = (
            self.target_agent_id,
            self.target_agent_revision,
            self.target_participant_id,
        )
        if self.handoff_outcome is HandoffState.SUCCEEDED:
            if self.source_agent_id is None or any(value is None for value in target):
                raise ValueError(
                    "Successful handoff metadata requires source and target identities."
                )
        elif any(value is not None for value in target):
            raise ValueError(
                "Rejected handoff metadata cannot name an executable target."
            )
        return self


class HandoffToolMetadata(HandoffMessageMetadata, ToolCompletionMetadata):
    """Typed legacy wire projection; runtime decisions use the outcome enum.

    Boolean fields remain only to preserve existing snapshots. They must agree
    with the outcome and completion mode; they are not independent control inputs.
    """

    handoff_context_changed: StrictBool
    handoff_occurred: StrictBool
    new_agent_id: UUID | None
    new_agent_revision: HandoffRevision | None
    new_participant_id: UUID | None
    circuit_breaker_triggered: StrictBool
    handoff_loop_detected: StrictBool

    @model_validator(mode="after")
    def validate_control(self) -> HandoffToolMetadata:
        succeeded = self.handoff_outcome is HandoffState.SUCCEEDED
        if (
            self.handoff_context_changed is not succeeded
            or self.handoff_occurred is not succeeded
        ):
            raise ValueError("Handoff flags must agree with the outcome.")
        if (self.new_agent_id, self.new_agent_revision, self.new_participant_id) != (
            self.target_agent_id,
            self.target_agent_revision,
            self.target_participant_id,
        ):
            raise ValueError("Handoff target mirrors must agree.")
        if self.circuit_breaker_triggered and succeeded:
            raise ValueError("A stopped handoff cannot succeed.")
        if self.handoff_loop_detected and not self.circuit_breaker_triggered:
            raise ValueError("A handoff loop requires a stopped handoff.")
        expected = (
            ToolCompletionMode.COMPLETE
            if self.circuit_breaker_triggered
            else ToolCompletionMode.CONTINUE
        )
        if self.terminal_response is not expected or self.terminal_artifact is not None:
            raise ValueError("Handoff completion must agree with its circuit breaker.")
        return self

    @classmethod
    def from_outcome(
        cls,
        outcome: HandoffOutcome,
        *,
        swarm_id: UUID | None,
        swarm_revision: int | None,
        source_agent_revision: int | None,
        source_participant_id: UUID | None,
    ) -> HandoffToolMetadata:
        outcome = HandoffOutcome.model_validate(outcome)
        agent = outcome.target_agent
        participant = outcome.target_participant
        return cls(
            handoff_outcome=HandoffState.SUCCEEDED
            if outcome.succeeded
            else HandoffState.REJECTED,
            swarm_id=swarm_id,
            swarm_revision=swarm_revision,
            source_agent_id=outcome.source_agent.id,
            source_agent_revision=source_agent_revision,
            source_participant_id=source_participant_id,
            target_agent_id=agent.id if agent else None,
            target_agent_revision=participant.agent_revision if participant else None,
            target_participant_id=participant.id if participant else None,
            new_agent_id=agent.id if agent else None,
            new_agent_revision=participant.agent_revision if participant else None,
            new_participant_id=participant.id if participant else None,
            handoff_context_changed=outcome.succeeded,
            handoff_occurred=outcome.succeeded,
            circuit_breaker_triggered=outcome.circuit_breaker_triggered,
            handoff_loop_detected=outcome.handoff_loop_detected,
            terminal_response=ToolCompletionMode.COMPLETE
            if outcome.circuit_breaker_triggered
            else ToolCompletionMode.CONTINUE,
            terminal_output=outcome.content
            if outcome.circuit_breaker_triggered
            else None,
        )


_HANDOFF_METADATA_SIGNALS = frozenset(
    {
        "handoff_context_changed",
        "handoff_occurred",
        "handoff_outcome",
        "new_agent_id",
        "new_participant_id",
    }
)


def handoff_metadata_from(result: ToolResult) -> HandoffToolMetadata | None:
    """Restore public snapshots at the pipeline owner, not inside the framework."""
    result = ToolResult.model_validate(result)
    metadata = result.metadata
    if isinstance(metadata, HandoffToolMetadata):
        handoff = type(metadata).model_validate(metadata)
    else:
        fields = metadata.model_dump()
        if _HANDOFF_METADATA_SIGNALS.isdisjoint(fields):
            return None
        handoff = HandoffToolMetadata.model_validate(fields)
    expected_error = handoff.handoff_outcome is not HandoffState.SUCCEEDED
    if result.is_error is not expected_error:
        raise ValueError("Tool result status must agree with its handoff outcome.")
    return handoff


def completed_handoffs(
    results: tuple[ToolResult, ...],
) -> tuple[HandoffToolMetadata, ...]:
    """Validate the batch before effects and return only completed switches."""
    metadata = tuple(handoff_metadata_from(result) for result in results)
    return tuple(
        item
        for item in metadata
        if item is not None and item.handoff_outcome is HandoffState.SUCCEEDED
    )
