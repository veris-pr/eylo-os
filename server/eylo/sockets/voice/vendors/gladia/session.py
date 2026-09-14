"""Create a Gladia Live v2 session without retries or unrestricted redirects."""

from __future__ import annotations

import asyncio
from http import HTTPStatus

import httpx
from pydantic import SecretStr, ValidationError

from eylo.sockets.stt.exceptions import (
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
)
from eylo.sockets.voice.vendors.gladia.wire import (
    GLADIA_LIVE_URL,
    GladiaLiveRequest,
    GladiaLiveSession,
)

_SESSION_TIMEOUT_SECONDS = 10.0
_MAX_SESSION_RESPONSE_BYTES = 64 * 1024
_API_KEY_HEADER = "x-gladia-key"
_STATUS_FAILURES: dict[int, STTConnectionFailureKind] = {
    HTTPStatus.UNAUTHORIZED: STTConnectionFailureKind.AUTHENTICATION,
    HTTPStatus.FORBIDDEN: STTConnectionFailureKind.AUTHORIZATION,
    HTTPStatus.REQUEST_TIMEOUT: STTConnectionFailureKind.TIMEOUT,
    HTTPStatus.TOO_MANY_REQUESTS: STTConnectionFailureKind.RATE_LIMITED,
    HTTPStatus.INTERNAL_SERVER_ERROR: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.BAD_GATEWAY: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.SERVICE_UNAVAILABLE: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
}


def gladia_http_failure_kind(status: int) -> STTConnectionFailureKind:
    """Use native HTTP status, never vendor error text, to classify a refusal."""
    return _STATUS_FAILURES.get(status, STTConnectionFailureKind.REQUEST_REJECTED)


async def create_gladia_session(
    request: GladiaLiveRequest, *, api_key: SecretStr
) -> GladiaLiveSession:
    """Close local HTTP resources on every exit; uncertain POSTs are never retried.

    The caller owns the returned vendor session. Cancellation cannot establish
    whether a remote session was created, so callers must not translate it into
    authorization to create a second session.
    """
    try:
        async with (
            asyncio.timeout(_SESSION_TIMEOUT_SECONDS),
            httpx.AsyncClient(
                timeout=_SESSION_TIMEOUT_SECONDS, follow_redirects=False
            ) as client,
        ):
            async with client.stream(
                "POST",
                GLADIA_LIVE_URL,
                headers={_API_KEY_HEADER: api_key.get_secret_value()},
                json=request.model_dump(mode="json"),
            ) as response:
                if response.status_code != HTTPStatus.CREATED:
                    raise STTConnectionRetryUnsafe(
                        "Gladia session creation was refused.",
                        kind=gladia_http_failure_kind(response.status_code),
                    )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_SESSION_RESPONSE_BYTES:
                        raise STTConnectionRetryUnsafe(
                            "Gladia session response exceeded its limit.",
                            kind=STTConnectionFailureKind.PROTOCOL,
                        )
                    body.extend(chunk)
                try:
                    return GladiaLiveSession.model_validate_json(bytes(body))
                except ValidationError:
                    raise STTConnectionRetryUnsafe(
                        "Gladia returned an invalid session response.",
                        kind=STTConnectionFailureKind.PROTOCOL,
                    ) from None
    except (httpx.TimeoutException, TimeoutError):
        raise STTConnectionRetryUnsafe(
            "Gladia session creation timed out; its remote outcome is unknown.",
            kind=STTConnectionFailureKind.TIMEOUT,
        ) from None
    except httpx.TransportError:
        raise STTConnectionRetryUnsafe(
            "Gladia session transport failed; its remote outcome is unknown.",
            kind=STTConnectionFailureKind.NETWORK,
        ) from None
