"""Content-free lifecycle details owned by the user-session timeline."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.common.contracts.provider_config import Capability
from eylo.modules.user_sessions.domain import UserSessionEntryChannel


class _TimelineFact(BaseModel):
    """Keep omitted details distinct from explicit nulls in stored event payloads."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json", exclude_unset=True)


class SessionLifecycleFact(_TimelineFact):
    """Session-owned connection sequence and optional lifecycle context."""

    connection_sequence: int
    entry_channel: UserSessionEntryChannel | None = None
    reason: str | None = None


class ToolWaitTimelineFact(_TimelineFact):
    """Identify the durable product operation awaited by an Agent run."""

    tool_owner_kind: str
    tool_owner_id: UUID


class ProviderTimelineFact(_TimelineFact):
    """Provider classification without credentials or native response content."""

    provider_kind: Capability
    vendor: str | None = None
