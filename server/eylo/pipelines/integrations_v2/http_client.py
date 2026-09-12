"""Origin-bound vendor transport for one curated tool invocation.

This is where a curated tool's `ctx.read(...)` becomes a real request. The path
a tool supplies is joined onto the vendor's declared base URL and the result is
pinned by `HttpDestinationPolicy` to that one origin and path subtree, so a tool
that computes a path from vendor content still cannot reach another host.

Reads send directly. Mutations run inside `execute_outbound_attempt`, which owns
the committed `TOOL_USE` effect, the idempotency key, and the retry decision —
there is deliberately no second retry path here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from http import HTTPStatus
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    JsonValue,
    TypeAdapter,
    ValidationError,
)
from pydantic.json_schema import SkipJsonSchema

from eylo.common.http_egress import (
    DEFAULT_RESPONSE_BODY_BYTES,
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpMethod,
    HttpOrigin,
    HttpRoutePolicy,
    parse_https_target,
)
from eylo.common.outbound import (
    OutboundAttemptIdentity,
    OutboundAttemptSpec,
    OutboundOwnerKind,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
    OutboundTransportKind,
)
from eylo.pipelines.outbound.durable_execution import (
    CommandStepContext,
    execute_outbound_attempt,
)
from eylo.sockets.http.transport import SafeHttpTransport

from .contracts import (
    DEFAULT_JSON_MEDIA_TYPE,
    RESERVED_HEADER_NAMES,
    JsonMediaType,
    VendorHttpErrorCode,
    VendorQuery,
    VendorResponse,
    VendorToolError,
)
from .credentials import VendorWireAuth

_SAFE_METHODS = frozenset({HttpMethod.GET, HttpMethod.HEAD, HttpMethod.OPTIONS})
_RETRYABLE_STATUS = frozenset(
    {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_EARLY,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
_MAX_MUTATIONS_PER_CALL = 20
_DEFAULT_VENDOR_TIMEOUT_SECONDS = 20.0

_QUERY = TypeAdapter(VendorQuery, config=ConfigDict(strict=True, allow_inf_nan=False))
_JSON_VALUE = TypeAdapter(JsonValue, config=ConfigDict(strict=True, allow_inf_nan=False))

MAX_VENDOR_RESPONSE_BYTES = DEFAULT_RESPONSE_BODY_BYTES


class VendorTransport(Protocol):
    """Structural port for the socket that actually sends."""

    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


class DurableMutationOwner(BaseModel):
    """Committed product IDs; the live step context never enters snapshots."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    tool_use_message_id: UUID
    tool_id: UUID
    durable_context: SkipJsonSchema[InstanceOf[CommandStepContext]] = Field(
        repr=False, exclude=True
    )


class GuardedVendorClient:
    """One invocation's vendor transport, pinned to one origin.

    Instances are per tool call because the mutation sequence counter must
    restart with each committed `TOOL_USE`; two mutations in one call take
    distinct attempt identities, and a durable replay reproduces the same
    sequence in the same order.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth: VendorWireAuth,
        vendor: str,
        transport: VendorTransport | None = None,
        owner: DurableMutationOwner | None = None,
        static_headers: Mapping[str, str] | None = None,
        accept_media_type: JsonMediaType = DEFAULT_JSON_MEDIA_TYPE,
        total_timeout_seconds: float = _DEFAULT_VENDOR_TIMEOUT_SECONDS,
    ) -> None:
        try:
            origin, base_path = parse_https_target(base_url)
        except HttpEgressPolicyError as error:
            raise VendorToolError(
                VendorHttpErrorCode.BASE_URL_INVALID,
                "Vendor base URL is not a valid HTTPS target.",
            ) from error
        self._origin = origin
        self._base_path = base_path.rstrip("/")
        self._policy = HttpDestinationPolicy(
            primary=HttpRoutePolicy(origin=origin, path_prefix=base_path or "/")
        )
        self._auth = auth
        self._vendor = vendor
        self._transport: VendorTransport = transport or SafeHttpTransport()
        self._owner = owner
        self._timeout = total_timeout_seconds
        self._mutation_sequence = 0
        self._static_headers = self._checked_static_headers(static_headers)
        try:
            self._accept_media_type = TypeAdapter(JsonMediaType).validate_python(
                accept_media_type, strict=True
            )
        except ValidationError:
            raise VendorToolError(
                VendorHttpErrorCode.ACCEPT_INVALID,
                "Curated vendors may negotiate only JSON media types.",
            ) from None

    @staticmethod
    def _checked_static_headers(
        static_headers: Mapping[str, str] | None,
    ) -> dict[str, str]:
        """Re-check what the vendor spec already validated.

        The spec is the first gate, but the client is reachable directly, so a
        reserved name is refused here too rather than trusted to have been
        caught upstream.
        """
        checked: dict[str, str] = {}
        for name, value in (static_headers or {}).items():
            if name.casefold() in RESERVED_HEADER_NAMES:
                raise VendorToolError(
                    VendorHttpErrorCode.HEADER_RESERVED,
                    f"Header '{name}' cannot be set by a vendor.",
                )
            checked[name] = value
        return checked

    @property
    def origin(self) -> HttpOrigin:
        return self._origin

    async def read(
        self,
        path: str,
        *,
        method: str = HttpMethod.GET,
        query: VendorQuery | None = None,
        json: JsonValue = None,
    ) -> VendorResponse:
        request = self._build(path, method=method, query=query, payload=json)
        try:
            response = await self._transport.send(request)
        except HttpEgressPolicyError as error:
            raise VendorToolError(
                VendorHttpErrorCode.EGRESS_REJECTED,
                "Vendor request was refused by the egress boundary.",
            ) from error
        except TimeoutError as error:
            raise VendorToolError(
                VendorHttpErrorCode.UNAVAILABLE,
                "Vendor did not answer within the request budget.",
            ) from error
        return _parse(response)

    async def mutate(
        self,
        path: str,
        *,
        method: str = HttpMethod.POST,
        query: VendorQuery | None = None,
        json: JsonValue = None,
    ) -> VendorResponse:
        if self._owner is None:
            raise VendorToolError(
                VendorHttpErrorCode.DURABLE_OWNER_REQUIRED,
                "A vendor mutation requires a committed tool-use owner.",
            )
        if self._mutation_sequence >= _MAX_MUTATIONS_PER_CALL:
            raise VendorToolError(
                VendorHttpErrorCode.MUTATION_BUDGET_EXHAUSTED,
                "One curated tool call may not make this many vendor mutations.",
            )
        sequence = self._mutation_sequence
        self._mutation_sequence += 1

        owner = self._owner
        identity = OutboundAttemptIdentity(
            organization_id=owner.organization_id,
            owner_kind=OutboundOwnerKind.TOOL_CALL,
            owner_id=owner.tool_use_message_id,
            operation_key=f"integration.curated.{owner.tool_id.hex}.{sequence}",
        )
        request = self._build(
            path,
            method=method,
            query=query,
            payload=json,
            idempotency_key=identity.provider_idempotency_key,
        )
        spec = OutboundAttemptSpec(
            identity=identity,
            provider_operation=f"integration.curated.{self._vendor}.{sequence}",
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin=str(self._origin),
            request_fingerprint=_fingerprint(request),
        )
        replies: list[VendorResponse] = []

        async def send(
            authorization: OutboundSendAuthorization,
        ) -> OutboundSendOutcome:
            if authorization.attempt_id != identity.attempt_id:
                raise ValueError(
                    "Vendor send authorization belongs to another attempt."
                )
            try:
                response = await self._transport.send(request)
            except HttpEgressPolicyError:
                return OutboundSendTerminal(failure_code="egress_policy_rejected")
            except TimeoutError:
                return OutboundSendUnknown(failure_code="egress_outcome_unconfirmed")
            replies.append(_parse(response))
            return _outcome(request.method, response)

        await execute_outbound_attempt(
            spec=spec,
            context=owner.durable_context,
            sender=send,
        )
        if not replies:
            raise VendorToolError(
                VendorHttpErrorCode.OUTCOME_UNKNOWN,
                "Vendor mutation completed without a readable reply.",
            )
        return replies[-1]

    def _build(
        self,
        path: str,
        *,
        method: str,
        query: VendorQuery | None,
        payload: JsonValue,
        idempotency_key: str | None = None,
    ) -> HttpEgressRequest:
        url = self._url(path, query)
        method = method.strip().upper()
        body = b""
        # Vendor-declared headers go in first so the transport's own always
        # win. `CuratedVendorSpec` already refuses credential and transport
        # header names, so this cannot become a second credential channel.
        headers: dict[str, str] = dict(self._static_headers)
        headers["Accept"] = self._accept_media_type
        if payload is not None:
            if method in _SAFE_METHODS:
                raise VendorToolError(
                    VendorHttpErrorCode.REQUEST_INVALID,
                    "A safe-method vendor request cannot carry a body.",
                )
            try:
                validated = _JSON_VALUE.validate_python(payload)
                body = json.dumps(validated, ensure_ascii=False, allow_nan=False).encode()
            except (ValidationError, ValueError, TypeError):
                raise VendorToolError(
                    VendorHttpErrorCode.REQUEST_INVALID,
                    "Vendor request body must contain only finite JSON values.",
                ) from None
            headers["Content-Type"] = DEFAULT_JSON_MEDIA_TYPE
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            return HttpEgressRequest(
                method=method,
                url=url,
                policy=self._policy,
                headers=headers,
                origin_headers=self._auth.origin_headers,
                origin_query=self._auth.origin_query,
                body=body,
                response_body_limit=MAX_VENDOR_RESPONSE_BYTES,
                total_timeout_seconds=self._timeout,
            )
        except HttpEgressPolicyError as error:
            raise VendorToolError(
                VendorHttpErrorCode.REQUEST_INVALID,
                "Vendor request was rejected before reaching the network.",
            ) from error

    def _url(self, path: str, query: VendorQuery | None) -> str:
        if "://" in path:
            raise VendorToolError(
                VendorHttpErrorCode.PATH_INVALID,
                "A curated tool must supply a path, never a full URL.",
            )
        suffix = path if path.startswith("/") else f"/{path}"
        url = f"{self._origin}{self._base_path}{suffix}"
        pairs = _query_pairs(query)
        return f"{url}?{urlencode(pairs)}" if pairs else url


def _query_pairs(query: VendorQuery | None) -> list[tuple[str, str]]:
    """Repeat scalar lists; retain legacy boolean spelling and skip null values."""
    if query is None:
        return []
    try:
        validated = _QUERY.validate_python(query)
    except ValidationError:
        raise VendorToolError(
            VendorHttpErrorCode.QUERY_INVALID,
            "Vendor query values must be finite scalars or scalar lists.",
        ) from None
    pairs: list[tuple[str, str]] = []
    for name, value in validated.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append((name, "true" if value else "false"))
        elif isinstance(value, (str, int, float)):
            pairs.append((name, str(value)))
        elif isinstance(value, (list, tuple)):
            pairs.extend((name, str(item)) for item in value if item is not None)
    return pairs


def _parse(response: HttpEgressResponse) -> VendorResponse:
    """Expose parsed data and Link pagination only; never credential/cookie headers."""
    link_headers = response.header_values("link")
    if not response.body:
        return VendorResponse(
            status_code=response.status_code, data=None, link_headers=link_headers
        )
    media = _media_type(response)
    if media and media != DEFAULT_JSON_MEDIA_TYPE and not media.endswith("+json"):
        raise VendorToolError(
            VendorHttpErrorCode.MEDIA_UNSUPPORTED,
            "Vendor returned a media type curated tools do not accept.",
        )
    try:
        # JsonValue's JSON-mode schema accepts any decoded JSON, including NaN.
        # Validate the decoded Python value to enforce the finite-number contract.
        data = _JSON_VALUE.validate_python(json.loads(response.body))
    except (UnicodeDecodeError, ValueError):
        raise VendorToolError(
            VendorHttpErrorCode.RESPONSE_INVALID,
            "Vendor returned a body that is not valid JSON.",
        ) from None
    return VendorResponse(
        status_code=response.status_code, data=data, link_headers=link_headers
    )


def _media_type(response: HttpEgressResponse) -> str:
    values = response.header_values("content-type")
    if not values:
        return ""
    return values[0].split(";", 1)[0].strip().lower()


def _outcome(method: HttpMethod, response: HttpEgressResponse) -> OutboundSendOutcome:
    if HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
        return OutboundSendSucceeded(status_code=response.status_code)
    if response.status_code in _RETRYABLE_STATUS:
        failure = f"vendor_http_{response.status_code}"
        if method in _SAFE_METHODS or method in {HttpMethod.PUT, HttpMethod.DELETE}:
            return OutboundSendRetryable(failure_code=failure)
        return OutboundSendUnknown(failure_code=failure)
    return OutboundSendTerminal(failure_code=f"vendor_http_{response.status_code}")


def _fingerprint(request: HttpEgressRequest) -> str:
    digest = hashlib.sha256()
    digest.update(request.method.encode())
    digest.update(b"\0")
    digest.update(request.url.encode())
    digest.update(b"\0")
    digest.update(request.body)
    return digest.hexdigest()


__all__ = [
    "MAX_VENDOR_RESPONSE_BYTES",
    "DurableMutationOwner",
    "GuardedVendorClient",
    "VendorTransport",
]
