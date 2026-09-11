"""Pure contracts for bounded HTTPS egress to explicitly declared routes."""

from __future__ import annotations

import re
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Self
from urllib.parse import SplitResult, parse_qsl, unquote, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBytes,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_RESPONSE_BODY_BYTES = 8_388_608
DEFAULT_RESPONSE_BODY_BYTES = 1_048_576
MAX_REQUEST_HEADERS = 100
MAX_REQUEST_HEADER_BYTES = 32_768
MAX_RESPONSE_HEADERS = 200
MAX_RESPONSE_HEADER_BYTES = 65_536
MAX_REDIRECTS = 5
MAX_TOTAL_TIMEOUT_SECONDS = 60.0

HTTPS_PORT = 443
MAX_PORT = 65_535
DEFAULT_TOTAL_TIMEOUT_SECONDS = 20.0
MAX_CREDENTIAL_QUERY_VALUE_LENGTH = 4_096
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_QUERY_NAME = re.compile(r"^[A-Za-z0-9_.~-]{1,128}$")
_FORBIDDEN_ALL_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-connection",
        "set-cookie",
        "transfer-encoding",
        "upgrade",
    }
)
_ORIGIN_BOUND_PUBLIC_HEADERS = frozenset(
    {"authorization", "cookie", "proxy-authorization"}
)


class HttpEgressErrorCode(StrEnum):
    """Transport-owned failures; consumers translate them to domain outcomes."""

    CONTRACT_INVALID = "contract_invalid"
    CREDENTIAL_ORIGIN_MISMATCH = "credential_origin_mismatch"
    CREDENTIAL_QUERY_INVALID = "credential_query_invalid"
    DESTINATION_NOT_ALLOWED = "destination_not_allowed"
    DESTINATION_NOT_PUBLIC = "destination_not_public"
    DNS_ANSWER_INVALID = "dns_answer_invalid"
    DNS_RESOLUTION_EMPTY = "dns_resolution_empty"
    DNS_RESOLUTION_FAILED = "dns_resolution_failed"
    FRAGMENT_NOT_ALLOWED = "fragment_not_allowed"
    HEADER_AUTHORITY_CONFLICT = "header_authority_conflict"
    HOST_INVALID = "host_invalid"
    HOST_MISSING = "host_missing"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    ORIGIN_INVALID = "origin_invalid"
    PATH_INVALID = "path_invalid"
    PATH_SEPARATOR_ENCODED = "path_separator_encoded"
    PATH_TRAVERSAL = "path_traversal"
    PORT_NOT_ALLOWED = "port_not_allowed"
    PUBLIC_HEADER_NOT_ALLOWED = "public_header_not_allowed"
    QUERY_AUTHORITY_CONFLICT = "query_authority_conflict"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"
    REDIRECT_LIMIT_INVALID = "redirect_limit_invalid"
    REDIRECT_LOCATION_INVALID = "redirect_location_invalid"
    REDIRECT_ROUTE_DUPLICATE = "redirect_route_duplicate"
    REQUEST_BODY_TOO_LARGE = "request_body_too_large"
    REQUEST_HEADER_INVALID = "request_header_invalid"
    REQUEST_HEADERS_TOO_LARGE = "request_headers_too_large"
    RESPONSE_BODY_TOO_LARGE = "response_body_too_large"
    RESPONSE_HEADERS_TOO_LARGE = "response_headers_too_large"
    RESPONSE_LIMIT_INVALID = "response_limit_invalid"
    SCHEME_NOT_ALLOWED = "scheme_not_allowed"
    TIMEOUT_INVALID = "timeout_invalid"
    TRANSPORT_FAILED = "transport_failed"
    URL_INVALID = "url_invalid"
    USERINFO_NOT_ALLOWED = "userinfo_not_allowed"


class HttpEgressPolicyError(ValueError):
    """A safe allowlisted category without destination or credential detail."""

    def __init__(self, code: HttpEgressErrorCode, message: str) -> None:
        if not isinstance(code, HttpEgressErrorCode):
            raise TypeError("HTTP egress error code must be a HttpEgressErrorCode.")
        self.code = code
        super().__init__(message)


class HttpMethod(StrEnum):
    """Methods executable by the shared egress boundary."""

    DELETE = "DELETE"
    GET = "GET"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"
    POST = "POST"
    PUT = "PUT"


class HttpTargetPhase(StrEnum):
    """Whether a target must match the primary route or may use redirect routes."""

    INITIAL = "initial"
    REDIRECT = "redirect"


class _HeaderAudience(StrEnum):
    PUBLIC = "public"
    ORIGIN_BOUND = "origin_bound"


class _HttpValue(BaseModel):
    """Immutable values with constructor errors compatible with egress callers.

    Pydantic validation APIs retain ValidationError semantics. Existing callers
    construct these values directly and catch the safe HttpEgressPolicyError.
    Never propagate raw validation inputs through that constructor boundary.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        hide_input_in_errors=True,
    )

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except ValidationError as error:
            for detail in error.errors(include_input=False, include_url=False):
                cause = detail.get("ctx", {}).get("error")
                if isinstance(cause, HttpEgressPolicyError):
                    raise cause from None
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.CONTRACT_INVALID,
                "HTTP egress contract is invalid.",
            ) from None


class HttpOrigin(_HttpValue):
    """Canonical HTTPS origin used for both routing and credential audience."""

    host: StrictStr
    port: StrictInt = HTTPS_PORT
    scheme: StrictStr = "https"

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if self.scheme != "https":
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.SCHEME_NOT_ALLOWED,
                "External HTTP transport requires HTTPS.",
            )
        host = _normalize_host(self.host)
        if not 1 <= self.port <= MAX_PORT:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.PORT_NOT_ALLOWED,
                "External HTTP destination port is invalid.",
            )
        object.__setattr__(self, "host", host)
        return self

    @classmethod
    def parse(cls, value: str) -> HttpOrigin:
        parsed = _split_url(value)
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.ORIGIN_INVALID,
                "Configured HTTP origin cannot include a path, query or fragment.",
            )
        return cls(
            scheme=parsed.scheme.lower(),
            host=_hostname(parsed),
            port=_port(parsed),
        )

    @property
    def authority(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.port == HTTPS_PORT else f"{host}:{self.port}"

    def __str__(self) -> str:
        return f"https://{self.authority}"


class HttpRoutePolicy(_HttpValue):
    """One declared origin and the path subtree authorized on it."""

    origin: HttpOrigin
    path_prefix: StrictStr = "/"

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        object.__setattr__(self, "path_prefix", _validated_path(self.path_prefix))
        return self

    def allows_path(self, path: str) -> bool:
        candidate = _validated_path(path)
        prefix = self.path_prefix
        if prefix == "/" or candidate == prefix:
            return True
        boundary = prefix if prefix.endswith("/") else f"{prefix}/"
        return candidate.startswith(boundary)


class HttpDestinationPolicy(_HttpValue):
    """Initial route plus explicit redirect reach and hop bound."""

    primary: HttpRoutePolicy
    redirect_routes: tuple[HttpRoutePolicy, ...] = ()
    max_redirects: StrictInt = 0

    @model_validator(mode="after")
    def validate_redirects(self) -> Self:
        if not 0 <= self.max_redirects <= MAX_REDIRECTS:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.REDIRECT_LIMIT_INVALID,
                f"Redirect limit must be between 0 and {MAX_REDIRECTS}.",
            )
        origins = [route.origin for route in self.redirect_routes]
        if len(origins) != len(set(origins)):
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.REDIRECT_ROUTE_DUPLICATE,
                "Redirect routes must have unique origins.",
            )
        return self

    def require_target(self, url: str, *, phase: HttpTargetPhase) -> HttpOrigin:
        if not isinstance(phase, HttpTargetPhase):
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.CONTRACT_INVALID,
                "HTTP target phase is invalid.",
            )
        origin, path = parse_https_target(url)
        if origin == self.primary.origin and self.primary.allows_path(path):
            return origin
        if phase is HttpTargetPhase.REDIRECT:
            for route in self.redirect_routes:
                if origin == route.origin and route.allows_path(path):
                    return origin
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.DESTINATION_NOT_ALLOWED,
            "HTTP destination is outside the configured operation authority.",
        )


class OriginBoundHeaders(_HttpValue):
    """Credentials/idempotency headers that may reach one exact origin only."""

    origin: HttpOrigin
    values: Mapping[StrictStr, StrictStr] = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        values = _validated_headers(self.values, audience=_HeaderAudience.ORIGIN_BOUND)
        object.__setattr__(self, "values", MappingProxyType(values))
        return self


class OriginBoundQuery(_HttpValue):
    """Credential query values injected only while sending to one exact origin."""

    origin: HttpOrigin
    values: Mapping[StrictStr, StrictStr] = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        values: dict[str, str] = {}
        for raw_name, raw_value in self.values.items():
            name = str(raw_name).strip()
            value = str(raw_value)
            if (
                not _QUERY_NAME.fullmatch(name)
                or not value
                or len(value) > MAX_CREDENTIAL_QUERY_VALUE_LENGTH
            ):
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.CREDENTIAL_QUERY_INVALID,
                    "Origin-bound HTTP query credential is invalid.",
                )
            if "\r" in value or "\n" in value:
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.CREDENTIAL_QUERY_INVALID,
                    "Origin-bound HTTP query credential is invalid.",
                )
            values[name] = value
        if not values:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.CREDENTIAL_QUERY_INVALID,
                "Origin-bound HTTP query credentials cannot be empty.",
            )
        object.__setattr__(self, "values", MappingProxyType(values))
        return self


class HttpEgressRequest(_HttpValue):
    """One already constructed request with bounded in-memory inputs."""

    method: HttpMethod
    url: StrictStr = Field(repr=False, exclude=True)
    policy: HttpDestinationPolicy
    headers: Mapping[StrictStr, StrictStr] = Field(
        default_factory=dict, repr=False, exclude=True
    )
    origin_headers: OriginBoundHeaders | None = Field(
        default=None, repr=False, exclude=True
    )
    origin_query: OriginBoundQuery | None = Field(
        default=None, repr=False, exclude=True
    )
    body: StrictBytes = Field(default=b"", repr=False, exclude=True)
    response_body_limit: StrictInt = DEFAULT_RESPONSE_BODY_BYTES
    total_timeout_seconds: StrictFloat = DEFAULT_TOTAL_TIMEOUT_SECONDS

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, value: object) -> HttpMethod:
        if isinstance(value, str):
            try:
                return HttpMethod(value.strip().upper())
            except ValueError:
                pass
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.METHOD_NOT_ALLOWED,
            "HTTP method is not supported by the egress boundary.",
        )

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if len(self.body) > MAX_REQUEST_BODY_BYTES:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.REQUEST_BODY_TOO_LARGE,
                "HTTP request body exceeds the egress limit.",
            )
        if not 1 <= self.response_body_limit <= MAX_RESPONSE_BODY_BYTES:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.RESPONSE_LIMIT_INVALID,
                "HTTP response body limit is outside the supported range.",
            )
        if not 0 < self.total_timeout_seconds <= MAX_TOTAL_TIMEOUT_SECONDS:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.TIMEOUT_INVALID,
                "HTTP total timeout is outside the supported range.",
            )
        initial_origin = self.policy.require_target(
            self.url, phase=HttpTargetPhase.INITIAL
        )
        headers = _validated_headers(self.headers, audience=_HeaderAudience.PUBLIC)
        if self.origin_headers is not None:
            if self.origin_headers.origin != initial_origin:
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.CREDENTIAL_ORIGIN_MISMATCH,
                    "Origin-bound HTTP headers do not match the initial destination.",
                )
            overlap = {name.lower() for name in headers} & {
                name.lower() for name in self.origin_headers.values
            }
            if overlap:
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.HEADER_AUTHORITY_CONFLICT,
                    "HTTP header cannot be both public and origin-bound.",
                )
        if self.origin_query is not None:
            if self.origin_query.origin != initial_origin:
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.CREDENTIAL_ORIGIN_MISMATCH,
                    "Origin-bound HTTP query does not match the initial destination.",
                )
            public_names = {
                name
                for name, _value in parse_qsl(
                    urlsplit(self.url).query,
                    keep_blank_values=True,
                )
            }
            if public_names & set(self.origin_query.values):
                raise HttpEgressPolicyError(
                    HttpEgressErrorCode.QUERY_AUTHORITY_CONFLICT,
                    "HTTP query value cannot be both public and origin-bound.",
                )
        object.__setattr__(self, "headers", MappingProxyType(headers))
        return self


class HttpEgressResponse(_HttpValue):
    """Bounded transport result; raw headers and body stay out of snapshots."""

    status_code: StrictInt = Field(ge=100, le=599)
    final_origin: HttpOrigin
    headers: tuple[tuple[StrictStr, StrictStr], ...] = Field(repr=False, exclude=True)
    body: StrictBytes = Field(repr=False, exclude=True)
    redirect_count: StrictInt = Field(default=0, ge=0, le=MAX_REDIRECTS)

    def header_values(self, name: str) -> tuple[str, ...]:
        expected = name.lower()
        return tuple(value for key, value in self.headers if key.lower() == expected)


def parse_https_target(value: str) -> tuple[HttpOrigin, str]:
    """Parse and normalize a complete target without resolving DNS."""
    parsed = _split_url(value)
    if parsed.username is not None or parsed.password is not None:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.USERINFO_NOT_ALLOWED,
            "HTTP destination user-info is not allowed.",
        )
    if parsed.fragment:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.FRAGMENT_NOT_ALLOWED,
            "HTTP destination fragments are not allowed.",
        )
    origin = HttpOrigin(
        scheme=parsed.scheme.lower(),
        host=_hostname(parsed),
        port=_port(parsed),
    )
    return origin, _validated_path(parsed.path or "/")


def _split_url(value: str) -> SplitResult:
    try:
        parsed = urlsplit(value)
        parsed.port
    except (TypeError, ValueError) as error:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.URL_INVALID,
            "HTTP destination URL is invalid.",
        ) from error
    if not parsed.scheme or not parsed.netloc:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.URL_INVALID,
            "HTTP destination requires an absolute URL.",
        )
    return parsed


def _hostname(parsed: SplitResult) -> str:
    if parsed.hostname is None:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.HOST_MISSING,
            "HTTP destination requires a hostname.",
        )
    return _normalize_host(parsed.hostname)


def _normalize_host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    if not host or "%" in host:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.HOST_INVALID,
            "HTTP destination hostname is invalid.",
        )
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.HOST_INVALID,
            "HTTP destination hostname is invalid.",
        ) from error


def _port(parsed: SplitResult) -> int:
    return HTTPS_PORT if parsed.port is None else parsed.port


def _validated_path(value: str) -> str:
    if not value.startswith("/") or "\\" in value:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.PATH_INVALID,
            "HTTP destination path is invalid.",
        )
    lowered = value.lower()
    if "%2f" in lowered or "%5c" in lowered:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.PATH_SEPARATOR_ENCODED,
            "Encoded path separators are not allowed.",
        )
    decoded = unquote(value)
    if any(segment in {".", ".."} for segment in decoded.split("/")):
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.PATH_TRAVERSAL,
            "HTTP destination path traversal is not allowed.",
        )
    return value


def _validated_headers(
    values: Mapping[str, str],
    *,
    audience: _HeaderAudience,
) -> dict[str, str]:
    if len(values) > MAX_REQUEST_HEADERS:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.REQUEST_HEADERS_TOO_LARGE,
            "HTTP request has too many headers.",
        )
    result: dict[str, str] = {}
    total = 0
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip()
        value = str(raw_value)
        lowered = name.lower()
        if not _HEADER_NAME.fullmatch(name):
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.REQUEST_HEADER_INVALID,
                "HTTP request header name is invalid.",
            )
        if "\r" in value or "\n" in value:
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.REQUEST_HEADER_INVALID,
                "HTTP request header value is invalid.",
            )
        if lowered in _FORBIDDEN_ALL_HEADERS or (
            audience is _HeaderAudience.PUBLIC
            and lowered in _ORIGIN_BOUND_PUBLIC_HEADERS
        ):
            raise HttpEgressPolicyError(
                HttpEgressErrorCode.PUBLIC_HEADER_NOT_ALLOWED,
                "Sensitive or hop-by-hop HTTP header must not be public.",
            )
        total += len(name.encode("utf-8")) + len(value.encode("utf-8"))
        result[name] = value
    if total > MAX_REQUEST_HEADER_BYTES:
        raise HttpEgressPolicyError(
            HttpEgressErrorCode.REQUEST_HEADERS_TOO_LARGE,
            "HTTP request headers exceed the egress limit.",
        )
    return result


__all__ = [
    "DEFAULT_RESPONSE_BODY_BYTES",
    "HttpDestinationPolicy",
    "HttpEgressErrorCode",
    "HttpEgressPolicyError",
    "HttpEgressRequest",
    "HttpEgressResponse",
    "HttpMethod",
    "HttpOrigin",
    "HttpRoutePolicy",
    "HttpTargetPhase",
    "MAX_REDIRECTS",
    "MAX_REQUEST_BODY_BYTES",
    "MAX_RESPONSE_BODY_BYTES",
    "OriginBoundHeaders",
    "OriginBoundQuery",
    "parse_https_target",
]
