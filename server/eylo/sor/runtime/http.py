"""Bounded origin-pinned JSON transport for SOR vendor adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin

from eylo.common.http_egress import (
    DEFAULT_RESPONSE_BODY_BYTES,
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpOrigin,
    HttpRoutePolicy,
    OriginBoundHeaders,
    parse_https_target,
)
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAFE_TRANSPORT_RETRY_DELAYS = (0.25, 1.0)
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_MAX_BINARY_REDIRECTS = 3
_PROTECTED_HEADERS = frozenset(
    {
        "authorization",
        "connection",
        "content-length",
        "cookie",
        "host",
        "proxy-authorization",
        "transfer-encoding",
    }
)


class SorHttpTransport(Protocol):
    """Structural socket port used by real and recorded transports."""

    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


class SorVendorTransportError(SorVendorOperationError):
    """A vendor egress failure raised by the shared JSON transport."""


def _transport_error(
    error: TimeoutError | HttpEgressPolicyError,
) -> SorVendorTransportError:
    if isinstance(error, TimeoutError):
        return SorVendorTransportError(
            SorVendorErrorCode.VENDOR_TIMEOUT,
            "The vendor did not answer within the operation budget.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    code = {
        "dns_resolution_failed": SorVendorErrorCode.VENDOR_DNS_UNAVAILABLE,
        "transport_failed": SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
    }.get(error.code, SorVendorErrorCode.VENDOR_EGRESS_REJECTED)
    summary = (
        "The vendor connection failed before a response was received."
        if error.code == "transport_failed"
        else "The vendor request was refused by the egress boundary."
    )
    return SorVendorTransportError(
        code,
        summary,
        recovery=(
            SorRecoveryPolicy.RETRY
            if error.code in {"dns_resolution_failed", "transport_failed"}
            else SorRecoveryPolicy.TERMINAL
        ),
    )


@dataclass(frozen=True, slots=True)
class SorJsonResponse:
    """One bounded JSON response including safe request-correlation headers."""

    status_code: int
    data: Any = field(repr=False)
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def header_values(self, name: str) -> tuple[str, ...]:
        expected = name.casefold()
        return tuple(value for key, value in self.headers if key.casefold() == expected)


@dataclass(frozen=True, slots=True)
class SorBinaryResponse:
    """One bounded binary response with no request or credential material."""

    status_code: int
    content: bytes = field(repr=False)
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def header_values(self, name: str) -> tuple[str, ...]:
        expected = name.casefold()
        return tuple(value for key, value in self.headers if key.casefold() == expected)


class SorJsonHttpClient:
    """Send relative JSON requests to one exact HTTPS origin."""

    def __init__(
        self,
        *,
        origin: str,
        authorization: str,
        transport: SorHttpTransport | None = None,
        timeout_seconds: float = 20.0,
        response_body_limit: int = DEFAULT_RESPONSE_BODY_BYTES,
        default_headers: Mapping[str, str] | None = None,
    ) -> None:
        try:
            parsed_origin = HttpOrigin.parse(origin)
            origin_headers = OriginBoundHeaders(
                origin=parsed_origin,
                values={"Authorization": authorization},
            )
            policy = HttpDestinationPolicy(
                primary=HttpRoutePolicy(origin=parsed_origin, path_prefix="/"),
            )
        except HttpEgressPolicyError as error:
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_TRANSPORT_INVALID,
                "The vendor transport configuration is invalid.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error
        self._origin = parsed_origin
        self._origin_headers = origin_headers
        self._policy = policy
        self._transport = transport or SafeHttpTransport()
        self._timeout_seconds = timeout_seconds
        self._response_body_limit = response_body_limit
        self._default_headers = _validated_default_headers(default_headers)

    async def request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, object] | None = None,
        payload: object | None = None,
        idempotency_key: str | None = None,
        if_unmodified_since: str | None = None,
        retry_transport_failures: bool = False,
    ) -> SorJsonResponse:
        request = self._build(
            path,
            method=method,
            query=query,
            payload=payload,
            idempotency_key=idempotency_key,
            if_unmodified_since=if_unmodified_since,
        )
        response = await self._send(
            request,
            retry_transport_failures=retry_transport_failures,
        )
        return SorJsonResponse(
            status_code=response.status_code,
            data=_parse_json(response),
            headers=response.headers,
        )

    async def request_binary(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        response_body_limit: int,
    ) -> SorBinaryResponse:
        """Read bounded bytes while keeping auth on the configured origin only."""
        request = self._build_binary(
            path,
            query=query,
            response_body_limit=response_body_limit,
        )
        response = await self._send(request)
        current_url = request.url
        redirects = 0
        while response.status_code in _REDIRECT_STATUS_CODES:
            locations = response.header_values("location")
            if len(locations) != 1 or not locations[0].strip():
                raise SorVendorTransportError(
                    SorVendorErrorCode.VENDOR_REDIRECT_INVALID,
                    "The vendor returned an invalid download redirect.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            if redirects >= _MAX_BINARY_REDIRECTS:
                raise SorVendorTransportError(
                    SorVendorErrorCode.VENDOR_REDIRECT_LIMIT,
                    "The vendor download exceeded its redirect limit.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            next_url = urljoin(current_url, locations[0].strip())
            try:
                origin, target_path = parse_https_target(next_url)
                if origin.port != 443:
                    raise HttpEgressPolicyError(
                        "port_not_allowed",
                        "Vendor downloads require the default HTTPS port.",
                    )
                policy = HttpDestinationPolicy(
                    primary=HttpRoutePolicy(
                        origin=origin,
                        path_prefix=target_path,
                    )
                )
                request = HttpEgressRequest(
                    method="GET",
                    url=next_url,
                    policy=policy,
                    headers={
                        "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
                        "User-Agent": "eylo-sor/1",
                    },
                    origin_headers=(
                        self._origin_headers if origin == self._origin else None
                    ),
                    response_body_limit=response_body_limit,
                    total_timeout_seconds=self._timeout_seconds,
                )
            except HttpEgressPolicyError as error:
                raise SorVendorTransportError(
                    SorVendorErrorCode.VENDOR_REDIRECT_INVALID,
                    "The vendor returned an invalid download redirect.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                ) from error
            current_url = next_url
            redirects += 1
            response = await self._send(request)
        return SorBinaryResponse(
            status_code=response.status_code,
            content=response.body,
            headers=response.headers,
        )

    async def _send(
        self,
        request: HttpEgressRequest,
        *,
        retry_transport_failures: bool = False,
    ) -> HttpEgressResponse:
        retry_delays = (
            _SAFE_TRANSPORT_RETRY_DELAYS
            if request.method in _SAFE_METHODS or retry_transport_failures
            else ()
        )
        for attempt in range(len(retry_delays) + 1):
            try:
                return await self._transport.send(request)
            except (TimeoutError, HttpEgressPolicyError) as error:
                transport_error = _transport_error(error)
                if attempt >= len(retry_delays) or not transport_error.retryable:
                    raise transport_error from error
                await asyncio.sleep(retry_delays[attempt])
        raise AssertionError("Vendor transport retry loop did not return.")

    def _build_binary(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None,
        response_body_limit: int,
    ) -> HttpEgressRequest:
        if "://" in path or not path.startswith("/"):
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_PATH_INVALID,
                "A SOR adapter must use an absolute path on its pinned origin.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        pairs = _query_pairs(query)
        url = f"{self._origin}{path}"
        if pairs:
            url = f"{url}?{urlencode(pairs)}"
        try:
            return HttpEgressRequest(
                method="GET",
                url=url,
                policy=self._policy,
                headers={
                    "Accept": "*/*",
                    "User-Agent": "eylo-sor/1",
                    **self._default_headers,
                },
                origin_headers=self._origin_headers,
                response_body_limit=response_body_limit,
                total_timeout_seconds=self._timeout_seconds,
            )
        except HttpEgressPolicyError as error:
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_REQUEST_INVALID,
                "The vendor request was rejected before network access.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error

    def _build(
        self,
        path: str,
        *,
        method: str,
        query: Mapping[str, object] | None,
        payload: object | None,
        idempotency_key: str | None,
        if_unmodified_since: str | None,
    ) -> HttpEgressRequest:
        if "://" in path or not path.startswith("/"):
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_PATH_INVALID,
                "A SOR adapter must use an absolute path on its pinned origin.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        normalized_method = method.strip().upper()
        if payload is not None and normalized_method in _SAFE_METHODS:
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_REQUEST_INVALID,
                "A safe-method vendor request cannot carry a body.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        body = b""
        headers = {
            "Accept": "application/json",
            "User-Agent": "eylo-sor/1",
            **self._default_headers,
        }
        if payload is not None:
            try:
                body = json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
            except (TypeError, ValueError) as error:
                raise SorVendorTransportError(
                    SorVendorErrorCode.VENDOR_REQUEST_INVALID,
                    "The vendor request payload is not JSON serializable.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                ) from error
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        if if_unmodified_since is not None:
            if (
                not if_unmodified_since.strip()
                or len(if_unmodified_since) > 128
                or "\r" in if_unmodified_since
                or "\n" in if_unmodified_since
            ):
                raise SorVendorTransportError(
                    SorVendorErrorCode.VENDOR_REQUEST_INVALID,
                    "The conditional source revision is invalid.",
                    recovery=SorRecoveryPolicy.TERMINAL,
                )
            headers["If-Unmodified-Since"] = if_unmodified_since.strip()
        pairs = _query_pairs(query)
        url = f"{self._origin}{path}"
        if pairs:
            url = f"{url}?{urlencode(pairs)}"
        try:
            return HttpEgressRequest(
                method=normalized_method,
                url=url,
                policy=self._policy,
                headers=headers,
                origin_headers=self._origin_headers,
                body=body,
                response_body_limit=self._response_body_limit,
                total_timeout_seconds=self._timeout_seconds,
            )
        except HttpEgressPolicyError as error:
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_REQUEST_INVALID,
                "The vendor request was rejected before network access.",
                recovery=SorRecoveryPolicy.TERMINAL,
            ) from error


def _query_pairs(
    query: Mapping[str, object] | None,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name, value in (query or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((name, "true" if value else "false"))
        elif isinstance(value, (str, int, float)):
            pairs.append((name, str(value)))
        elif isinstance(value, (tuple, list)):
            for item in value:
                if isinstance(item, (str, int, float)) and not isinstance(item, bool):
                    pairs.append((name, str(item)))
                else:
                    raise SorVendorTransportError(
                        SorVendorErrorCode.VENDOR_QUERY_INVALID,
                        "Vendor query lists must contain scalar values.",
                        recovery=SorRecoveryPolicy.TERMINAL,
                    )
        else:
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_QUERY_INVALID,
                "Vendor query values must be scalar values or scalar lists.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
    return pairs


def _validated_default_headers(
    headers: Mapping[str, str] | None,
) -> dict[str, str]:
    """Validate adapter-owned headers without weakening the egress boundary."""
    validated: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in (headers or {}).items():
        normalized_name = name.strip()
        normalized_value = value.strip()
        folded_name = normalized_name.casefold()
        if (
            not normalized_name
            or folded_name in _PROTECTED_HEADERS
            or folded_name in seen
            or not normalized_value
            or any(character in normalized_name for character in "\r\n:")
            or "\r" in normalized_value
            or "\n" in normalized_value
            or len(normalized_name) > 128
            or len(normalized_value) > 4096
        ):
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_TRANSPORT_INVALID,
                "The vendor transport headers are invalid.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        seen.add(folded_name)
        validated[normalized_name] = normalized_value
    return validated


def _parse_json(response: HttpEgressResponse) -> object | None:
    if not response.body:
        return None
    media_types = response.header_values("content-type")
    if media_types:
        media_type = media_types[0].split(";", 1)[0].strip().casefold()
        if media_type != "application/json" and not media_type.endswith("+json"):
            raise SorVendorTransportError(
                SorVendorErrorCode.VENDOR_MEDIA_UNSUPPORTED,
                "The vendor returned an unsupported response media type.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SorVendorTransportError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "The vendor returned invalid JSON.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


__all__ = [
    "SorBinaryResponse",
    "SorHttpTransport",
    "SorJsonHttpClient",
    "SorJsonResponse",
    "SorVendorTransportError",
]
