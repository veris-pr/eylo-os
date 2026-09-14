"""Application contract for querying organization-owned Agents."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from eylo.modules.agents.models import AgentKind, AgentStatus


class AgentSortField(str, Enum):
    NAME = "name"
    STATUS = "status"
    KIND = "kind"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class AgentSortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class AgentListQuery(BaseModel):
    """Validated filters; organization authority and pagination stay with the caller."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )

    agent_ids: tuple[UUID, ...] = ()
    search: str | None = None
    statuses: tuple[AgentStatus, ...] = ()
    kinds: tuple[AgentKind, ...] = ()
    sort_by: AgentSortField = AgentSortField.UPDATED_AT
    sort_direction: AgentSortDirection = AgentSortDirection.DESC

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value: str | None) -> str | None:
        """Keep the existing blank-as-absent agent search contract."""
        return value.strip() or None if value is not None else None
