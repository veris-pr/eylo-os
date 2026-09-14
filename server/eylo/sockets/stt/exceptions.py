"""Errors for the `stt` socket."""

from enum import StrEnum


class STTConnectionFailureKind(StrEnum):
    """Socket-owned causes; native SDK error names stay inside adapters."""

    NETWORK = "network"
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    REQUEST_REJECTED = "request_rejected"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    TLS = "tls"
    PROTOCOL = "protocol"
    UNKNOWN = "unknown"


RETRYABLE_STT_CONNECTION_KINDS = frozenset(
    {
        STTConnectionFailureKind.NETWORK,
        STTConnectionFailureKind.TIMEOUT,
        STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    }
)


class STTConfigurationError(ValueError):
    """Invalid resolved settings; messages must not expose credential values."""


class STTConnectionError(Exception):
    """Custom exception for connection errors."""

    pass


class STTConnectionClosed(STTConnectionError):
    """Custom exception for closed connection errors."""

    pass


class STTConnectionFailed(STTConnectionError):
    """A classified establishment failure, never evidence that audio was not sent.

    Unknown failures are terminal. Throttling/quota refusal needs provider-specific
    recovery rather than an immediate retry with the same request.
    """

    def __init__(
        self,
        message: str = "STT connection failed.",
        *,
        kind: STTConnectionFailureKind = STTConnectionFailureKind.UNKNOWN,
    ) -> None:
        if not isinstance(kind, STTConnectionFailureKind):
            raise TypeError("STT connection failure kind must be an enum member.")
        super().__init__(message)
        self.kind = kind


class STTConnectionRetryUnsafe(STTConnectionFailed):
    """A known establishment cause does not authorize another native attempt."""


class STTConnectionCleanupFailed(STTConnectionError):
    """A failed attempt could not close; opening another connection is unsafe."""


class STTFinalizationFailed(Exception):
    """Resources closed, but final transcript production/delivery did not finish."""
