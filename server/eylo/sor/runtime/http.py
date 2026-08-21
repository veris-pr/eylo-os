"""Bounded origin-pinned JSON transport for SOR vendor adapters."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

from eylo.common.http_egress import (
    DEFAULT_RESPONSE_BODY_BYTES,
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpOrigin,
    HttpRoutePolicy,
    OriginBoundHeaders,
)
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sor.shared.contracts import SorVendorOperationError

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAFE_TRANSPORT_RETRY_DELAYS = (0.25, 1.0)
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


def _transport_error(error: TimeoutError | HttpEgressPolicyError) -> SorVendorTransportError:
    if isinstance(error, TimeoutError):
        return SorVendorTransportError(
            "vendor_timeout",
            "The vendor did not answer within the operation budget.",
            retryable=True,
        )
    code = {
        "dns_resolution_failed": "vendor_dns_unavailable",
        "transport_failed": "vendor_transport_failed",
    }.get(error.code, "vendor_egress_rejected")
    summary = (
        "The vendor connection failed before a response was received."
        if error.code == "transport_failed"
        else "The vendor request was refused by the egress boundary."
    )
    return SorVendorTransportError(
        code,
        summary,
        retryable=error.code in {"dns_resolution_failed", "transport_failed"},
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
        return tuple(
            value for key, value in self.headers if key.casefold() == expected
        )


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
                "vendor_transport_invalid",
                "The vendor transport configuration is invalid.",
                retryable=False,
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
        normalized_method = method.strip().upper()
        retry_delays = (
            _SAFE_TRANSPORT_RETRY_DELAYS
            if normalized_method in _SAFE_METHODS or retry_transport_failures
            else ()
        )
        for attempt in range(len(retry_delays) + 1):
            try:
                response = await self._transport.send(request)
                break
            except (TimeoutError, HttpEgressPolicyError) as error:
                transport_error = _transport_error(error)
                if attempt >= len(retry_delays) or not transport_error.retryable:
                    raise transport_error from error
                await asyncio.sleep(retry_delays[attempt])
        return SorJsonResponse(
            status_code=response.status_code,
            data=_parse_json(response),
            headers=response.headers,
        )

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
                "vendor_path_invalid",
                "A SOR adapter must use an absolute path on its pinned origin.",
                retryable=False,
            )
        normalized_method = method.strip().upper()
        if payload is not None and normalized_method in _SAFE_METHODS:
            raise SorVendorTransportError(
                "vendor_request_invalid",
                "A safe-method vendor request cannot carry a body.",
                retryable=False,
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
                    "vendor_request_invalid",
                    "The vendor request payload is not JSON serializable.",
                    retryable=False,
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
                    "vendor_request_invalid",
                    "The conditional source revision is invalid.",
                    retryable=False,
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
                "vendor_request_invalid",
                "The vendor request was rejected before network access.",
                retryable=False,
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
                        "vendor_query_invalid",
                        "Vendor query lists must contain scalar values.",
                        retryable=False,
                    )
        else:
            raise SorVendorTransportError(
                "vendor_query_invalid",
                "Vendor query values must be scalar values or scalar lists.",
                retryable=False,
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
                "vendor_transport_invalid",
                "The vendor transport headers are invalid.",
                retryable=False,
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
                "vendor_media_unsupported",
                "The vendor returned an unsupported response media type.",
                retryable=False,
            )
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SorVendorTransportError(
            "vendor_response_invalid",
            "The vendor returned invalid JSON.",
            retryable=False,
        ) from error


__all__ = [
    "SorHttpTransport",
    "SorJsonHttpClient",
    "SorJsonResponse",
    "SorVendorTransportError",
]
