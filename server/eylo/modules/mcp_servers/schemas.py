"""Credential-free operator projections for MCP definitions and discovery."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_serializer

from eylo.common.identifiers import normalize_uuid_like
from eylo.common.revisions import DefinitionLifecycle, RevisionAvailability
from eylo.modules.tools.models import ToolExecutionMode
from eylo.modules.tools.schemas.executors.mcp import MCPToolEffect

_PublicUUID = Annotated[UUID, BeforeValidator(normalize_uuid_like)]


class MCPServerAuthMode(StrEnum):
    """Public indication of configured authentication, never its values."""

    NONE = "none"
    HEADERS = "headers"


class MCPServerRead(BaseModel):
    """Allowlisted server metadata; neither encrypted nor resolved secrets escape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: _PublicUUID
    name: str
    slug: str
    url: str
    transport: str
    protocol_version: str
    auth_mode: MCPServerAuthMode
    header_names: list[str]
    lifecycle: DefinitionLifecycle
    published_revision: int | None
    draft_version: int
    draft_dirty: bool
    discovered_at: datetime | None
    discovered_tool_count: int | None

    @field_serializer("discovered_at")
    def serialize_discovered_at(self, value: datetime | None) -> str | None:
        """Retain the existing ISO offset spelling, including UTC +00:00."""
        return value.isoformat() if value is not None else None


class MCPDiscoveredToolRead(BaseModel):
    """Published tool facts reviewed before an explicit Agent assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: _PublicUUID
    wire_id: str | None
    slug: str
    name: str
    description: str | None
    effect: MCPToolEffect
    execution_mode: ToolExecutionMode
    lifecycle: DefinitionLifecycle
    published_revision: int | None


class MCPDiscoveryRead(BaseModel):
    """Complete bounded discovery outcome, not the remote server's raw payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int
    tools: list[MCPDiscoveredToolRead]


class MCPServerRevisionRead(BaseModel):
    """Exact revision revocation status without the private definition config."""

    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    server_id: _PublicUUID
    revision: int
    availability: RevisionAvailability
    revoked_at: datetime | None
    revoked_by: _PublicUUID | None
    revocation_reason: str | None
    cancellation_requested_at: datetime | None

    @field_serializer("revoked_at", "cancellation_requested_at")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        """Match the former FastAPI encoding of raw datetime dictionary values."""
        return value.isoformat() if value is not None else None
