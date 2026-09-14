"""Exact provider and tool references selected by Agent publication."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.common.identifiers import normalize_uuid_like
from eylo.modules.agents.domain import InvalidAgentDefinitionError
from eylo.modules.agents.models import AgentRevisionToolModel, AgentToolMappingModal


class AgentProviderReference(BaseModel):
    """A resolved config identity and revision; never an unresolved draft choice."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    config_id: UUID
    revision: int = Field(gt=0)

    @field_validator("config_id", mode="before")
    @classmethod
    def normalize_id(cls, value: object) -> object:
        return normalize_uuid_like(value)


class AgentProviderBindings(BaseModel):
    """Only explicitly selected providers, resolved in the Agent's organization."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    llm: AgentProviderReference
    email: AgentProviderReference | None
    webrtc: AgentProviderReference | None
    reranking: AgentProviderReference | None
    memory: AgentProviderReference | None
    file_upload_embedding: AgentProviderReference | None


def provider_pair(
    reference: AgentProviderReference | None,
) -> tuple[UUID | None, int | None]:
    """Project an optional complete reference into the two existing ORM columns."""
    if reference is None:
        return None, None
    return reference.config_id, reference.revision


def revisioned_tool_ref(
    row: AgentToolMappingModal | AgentRevisionToolModel,
) -> tuple[UUID, int]:
    """Fail closed if a revisioned grant violates the DB's exactly-one contract."""
    if (
        row.tool_id is None
        or row.tool_revision is None
        or row.tool_revision <= 0
        or row.curated_tool_id is not None
    ):
        raise InvalidAgentDefinitionError(
            "Agent tool grant must contain an exact revisioned tool reference."
        )
    return row.tool_id, row.tool_revision


def curated_tool_ref(row: AgentToolMappingModal | AgentRevisionToolModel) -> UUID:
    """A curated grant identifies code-owned tools without a definition revision."""
    if (
        row.curated_tool_id is None
        or row.tool_id is not None
        or row.tool_revision is not None
    ):
        raise InvalidAgentDefinitionError(
            "Agent curated tool grant must not contain a revisioned tool reference."
        )
    return row.curated_tool_id
