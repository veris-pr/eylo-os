"""Translate typed HTTP/WebSocket establishment failures at the adapter boundary."""

from __future__ import annotations

import asyncio
import errno
import socket
import ssl
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import NoReturn

import aiohttp
from websockets.exceptions import InvalidHandshake, InvalidMessage, InvalidStatus

from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionFailed,
    STTConnectionFailureKind,
)

_HTTP_FAILURE_KINDS: dict[int, STTConnectionFailureKind] = {
    HTTPStatus.UNAUTHORIZED: STTConnectionFailureKind.AUTHENTICATION,
    HTTPStatus.FORBIDDEN: STTConnectionFailureKind.AUTHORIZATION,
    HTTPStatus.REQUEST_TIMEOUT: STTConnectionFailureKind.TIMEOUT,
    HTTPStatus.TOO_MANY_REQUESTS: STTConnectionFailureKind.RATE_LIMITED,
    HTTPStatus.INTERNAL_SERVER_ERROR: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.BAD_GATEWAY: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.SERVICE_UNAVAILABLE: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
}
_NETWORK_ERRNOS = frozenset(
    {
        errno.ECONNABORTED,
        errno.ECONNREFUSED,
        errno.ECONNRESET,
        errno.EHOSTUNREACH,
        errno.ENETDOWN,
        errno.ENETRESET,
        errno.ENETUNREACH,
        errno.EPIPE,
        errno.ETIMEDOUT,
    }
)


def websocket_connection_failure_kind(
    error: Exception,
) -> STTConnectionFailureKind | None:
    """Classify known transport types, never error text or arbitrary cause chains.

    ``None`` preserves unknown/programming/native-protocol exceptions unchanged.
    TLS refusal takes precedence over its network-error base classes.
    """
    if isinstance(
        error, (ssl.SSLError, aiohttp.ClientSSLError, aiohttp.ServerFingerprintMismatch)
    ):
        return STTConnectionFailureKind.TLS
    if isinstance(error, TimeoutError):
        return STTConnectionFailureKind.TIMEOUT
    if isinstance(error, InvalidStatus):
        return _HTTP_FAILURE_KINDS.get(
            error.response.status_code, STTConnectionFailureKind.REQUEST_REJECTED
        )
    if isinstance(error, aiohttp.ClientResponseError):
        return _HTTP_FAILURE_KINDS.get(
            error.status, STTConnectionFailureKind.REQUEST_REJECTED
        )
    if isinstance(error, InvalidMessage) and isinstance(error.__cause__, EOFError):
        return STTConnectionFailureKind.NETWORK
    if isinstance(error, InvalidHandshake):
        return STTConnectionFailureKind.PROTOCOL
    if isinstance(error, socket.gaierror):
        return (
            STTConnectionFailureKind.NETWORK
            if error.errno == socket.EAI_AGAIN
            else STTConnectionFailureKind.REQUEST_REJECTED
        )
    if isinstance(error, (ConnectionError, aiohttp.ServerDisconnectedError)):
        return STTConnectionFailureKind.NETWORK
    if isinstance(error, OSError) and error.errno in _NETWORK_ERRNOS:
        return STTConnectionFailureKind.NETWORK
    return None


def raise_websocket_connection_error(error: BaseException) -> NoReturn:
    """Raise a safe typed failure; cancellation and unclassified errors survive."""
    if isinstance(error, Exception):
        kind = websocket_connection_failure_kind(error)
        if kind is not None:
            raise STTConnectionFailed(
                "STT provider connection failed.", kind=kind
            ) from error
    raise error


async def close_failed_websocket_connection(
    error: BaseException, disconnect: Callable[[], Awaitable[None]]
) -> NoReturn:
    """Close before translation; cleanup errors must never become retryable timeouts."""
    try:
        await disconnect()
    except Exception as cleanup_error:
        if isinstance(error, asyncio.CancelledError):
            raise error from cleanup_error
        raise STTConnectionCleanupFailed(
            "STT failed connection cleanup could not be completed."
        ) from cleanup_error
    raise_websocket_connection_error(error)
