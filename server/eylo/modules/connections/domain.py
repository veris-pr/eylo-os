"""Domain values and failures for source-neutral external connections."""

from enum import Enum


class ConnectionOwnerKind(str, Enum):
    """The organization subject that owns one external account connection."""

    ORGANIZATION = "ORGANIZATION"
    CONTACT = "CONTACT"


class ConnectionAuthKind(str, Enum):
    """Credential protocol used by an external account."""

    NO_AUTH = "no_auth"
    API_KEY = "api_key"
    BASIC = "basic"
    OAUTH2 = "oauth2"


class ExternalConnectionStatus(str, Enum):
    """Lifecycle state of a source-neutral external account connection."""

    INITIATED = "INITIATED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    REVOKED = "REVOKED"


class ExternalConnectionError(Exception):
    """Base failure for external-connection domain operations."""


class ExternalConnectionNotFoundError(ExternalConnectionError):
    """The requested connection is absent from the organization boundary."""


class ExternalConnectionRevisionConflictError(ExternalConnectionError):
    """The connection changed after the caller resolved its credentials."""


class ExternalConnectionStateError(ExternalConnectionError):
    """The requested lifecycle transition is not allowed."""


__all__ = [
    "ConnectionAuthKind",
    "ConnectionOwnerKind",
    "ExternalConnectionError",
    "ExternalConnectionNotFoundError",
    "ExternalConnectionRevisionConflictError",
    "ExternalConnectionStateError",
    "ExternalConnectionStatus",
]
