"""Public widget projections of curated connection and authorization events."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eylo.modules.integrations_v2.domain.enums import VendorAuthKind


class ConnectionRecoveryAction(StrEnum):
    RECONNECT = "reconnect"


class _ConnectionNotification(BaseModel):
    """Selected public fields only; credentials and internal error objects stay out."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    integration_id: UUID
    vendor: str | None


class WsConnectionStarted(_ConnectionNotification):
    contact_id: UUID


class WsConnectionSuccess(_ConnectionNotification):
    connection_id: UUID
    integration_name: str


class WsConnectionFailed(_ConnectionNotification):
    integration_name: str
    error: str = Field(repr=False)


class WsConnectionExpired(_ConnectionNotification):
    """Contact-wide reconnection notice; no conversation authority is implied."""

    connection_id: UUID
    integration_name: str | None
    reason: str = Field(repr=False)
    message: str = "Reconnect this service so the Agent can continue using it."
    action: ConnectionRecoveryAction = ConnectionRecoveryAction.RECONNECT


class WsAuthorizationRequired(_ConnectionNotification):
    """Conversation-scoped request to authorize one curated installation."""

    conversation_id: UUID
    contact_id: UUID
    vendor: str
    auth_kind: VendorAuthKind | None
    integration_name: str
    reason: str = Field(repr=False)
    message: str = Field(repr=False)
