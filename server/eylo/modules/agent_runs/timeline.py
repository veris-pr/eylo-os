"""Agent-run-owned, content-free details for durable session timeline facts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.modules.agent_runs.domain import AgentInputRequestKind, AgentRunOutcome
from eylo.modules.user_sessions.fact_payloads import ToolWaitTimelineFact


class AgentRunRefusalReason(StrEnum):
    """Safe startup refusal codes; never include authority or credential content."""

    AGENT_REVISION_UNAVAILABLE = "agent_revision_unavailable"
    PRINCIPAL_INACTIVE = "principal_inactive"


class _AgentRunTimelineFact(BaseModel):
    """Keep source types intact until the existing flat JSON filing boundary."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    def to_payload(self) -> dict[str, JsonValue]:
        """Do not add omitted fields to historical event shapes."""
        return self.model_dump(mode="json", exclude_unset=True)


class AgentRunTimelineIdentity(_AgentRunTimelineFact):
    """Pinned Agent identity; workflow facts identify the run by subject ID only."""

    agent_id: UUID
    agent_revision: int
    run_id: UUID | None = None


class AgentInputReferenceFact(_AgentRunTimelineFact):
    """Link a run's wait or resume to its persisted input request."""

    input_request_id: UUID


class AgentInputTimelineFact(AgentInputReferenceFact):
    """Classify a request or answer without recording the question or response."""

    request_kind: AgentInputRequestKind


class AgentRunOutcomeFact(_AgentRunTimelineFact):
    """A terminal outcome without the result or failure summary."""

    outcome: AgentRunOutcome


class AgentRunRefusalFact(_AgentRunTimelineFact):
    """One supported refusal code for a worker claim."""

    reason: AgentRunRefusalReason


type AgentRunTimelineDetails = (
    AgentInputReferenceFact
    | AgentInputTimelineFact
    | AgentRunOutcomeFact
    | AgentRunRefusalFact
    | ToolWaitTimelineFact
)
