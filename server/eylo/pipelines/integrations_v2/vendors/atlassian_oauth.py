"""Bind curated Atlassian OAuth grants to an exact site and product gateway."""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from http import HTTPStatus
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from eylo.common.database import current_transaction
from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpMethod,
    HttpOrigin,
    HttpRoutePolicy,
    OriginBoundHeaders,
)
from eylo.sockets.http.transport import SafeHttpTransport

from ..http_client import VendorTransport
from ..oauth_contracts import CuratedOAuthCode, CuratedOAuthError

AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
API_ORIGIN = "https://api.atlassian.com"
AUTHORIZATION_PARAMS = (("audience", "api.atlassian.com"), ("prompt", "consent"))
OFFLINE_SCOPE = "offline_access"
SITE_BINDING_KEY = "atlassian_site"
_RESOURCES_PATH = "/oauth/token/accessible-resources"
_RESPONSE_LIMIT_BYTES = 262_144
_REQUEST_TIMEOUT_SECONDS = 20.0


class AtlassianProduct(StrEnum):
    JIRA = "jira"
    CONFLUENCE = "confluence"


def product_for_vendor(vendor: str) -> AtlassianProduct | None:
    """Only explicit curated registrations participate; SOR owns its own flow."""
    try:
        return AtlassianProduct(vendor)
    except ValueError:
        return None


class AccessibleResource(BaseModel):
    """Native access discovery record; unrelated display fields are ignored."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    id: UUID
    url: str
    scopes: list[str]

    @field_validator("url")
    @classmethod
    def canonical_origin(cls, value: str) -> str:
        return str(HttpOrigin.parse(value))


class AtlassianSiteBinding(BaseModel):
    """Encrypted connection metadata, not a caller-controlled destination."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    product: AtlassianProduct
    site_origin: str
    cloud_id: UUID
    scopes: tuple[str, ...]

    @field_validator("product", mode="before")
    @classmethod
    def parse_product(cls, value: object) -> AtlassianProduct:
        if not isinstance(value, str):
            raise ValueError("Atlassian product must be a named product.")
        return AtlassianProduct(value)

    @field_validator("cloud_id", mode="before")
    @classmethod
    def parse_cloud_id(cls, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError("Atlassian cloud ID must be a UUID.")
        return UUID(value)

    @field_validator("scopes", mode="before")
    @classmethod
    def parse_scopes(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("site_origin")
    @classmethod
    def canonical_origin(cls, value: str) -> str:
        return str(HttpOrigin.parse(value))

    def gateway_url(self, path_suffix: str) -> str:
        """The registry, never the token response, supplies the API path."""
        return f"{API_ORIGIN}/ex/{self.product.value}/{self.cloud_id}{path_suffix}"


_RESOURCES = TypeAdapter(list[AccessibleResource])


def require_site_binding(
    credentials: Mapping[str, object],
    *,
    product: AtlassianProduct,
    site_origin: str | None,
    required_scopes: Sequence[str] = (),
) -> AtlassianSiteBinding:
    """Refuse legacy, mismatched or insufficient grants without network I/O."""
    try:
        binding = AtlassianSiteBinding.model_validate(credentials.get(SITE_BINDING_KEY))
        expected_origin = str(HttpOrigin.parse(site_origin or ""))
    except (ValidationError, ValueError, HttpEgressPolicyError):
        raise CuratedOAuthError(
            CuratedOAuthCode.SITE_BINDING_INVALID,
            "Reconnect the configured Atlassian site.",
        ) from None
    required = set(required_scopes) - {OFFLINE_SCOPE}
    if (
        binding.product is not product
        or binding.site_origin != expected_origin
        or not required.issubset(binding.scopes)
    ):
        raise CuratedOAuthError(
            CuratedOAuthCode.SITE_BINDING_INVALID,
            "Reconnect the configured Atlassian site with the required scopes.",
        )
    return binding


async def discover_site_binding(
    *,
    product: AtlassianProduct,
    site_origin: str | None,
    access_token: str,
    required_scopes: Sequence[str],
    transport: VendorTransport | None,
) -> AtlassianSiteBinding:
    """Discover outside DB transactions; refuse absent or ambiguous site grants."""
    if current_transaction() is not None:
        raise CuratedOAuthError(
            CuratedOAuthCode.REQUEST_INVALID,
            "Atlassian discovery cannot run inside a DB transaction.",
        )
    try:
        expected_origin = str(HttpOrigin.parse(site_origin or ""))
        origin = HttpOrigin.parse(API_ORIGIN)
        request = HttpEgressRequest(
            method=HttpMethod.GET,
            url=f"{API_ORIGIN}{_RESOURCES_PATH}",
            policy=HttpDestinationPolicy(
                primary=HttpRoutePolicy(origin=origin, path_prefix=_RESOURCES_PATH),
                max_redirects=0,
            ),
            headers={"Accept": "application/json"},
            origin_headers=OriginBoundHeaders(
                origin=origin, values={"Authorization": f"Bearer {access_token}"}
            ),
            total_timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            response_body_limit=_RESPONSE_LIMIT_BYTES,
        )
        response = await (transport or SafeHttpTransport()).send(request)
    except (HttpEgressPolicyError, TimeoutError):
        raise CuratedOAuthError(
            CuratedOAuthCode.ENDPOINT_UNREACHABLE,
            "Atlassian site access could not be verified safely.",
        ) from None
    if response.status_code != HTTPStatus.OK:
        raise CuratedOAuthError(
            CuratedOAuthCode.SITE_ACCESS_REJECTED,
            "Atlassian did not confirm access to the configured site.",
        )
    try:
        resources = _RESOURCES.validate_json(response.body)
    except (ValidationError, HttpEgressPolicyError):
        raise CuratedOAuthError(
            CuratedOAuthCode.SITE_RESPONSE_INVALID,
            "Atlassian returned unreadable site access information.",
        ) from None
    required = set(required_scopes) - {OFFLINE_SCOPE}
    matches = [
        resource
        for resource in resources
        if resource.url == expected_origin and required.issubset(resource.scopes)
    ]
    if not required or len(matches) != 1:
        raise CuratedOAuthError(
            CuratedOAuthCode.SITE_ACCESS_REJECTED,
            "Authorize exactly the configured Atlassian site with the required scopes.",
        )
    resource = matches[0]
    return AtlassianSiteBinding(
        product=product,
        site_origin=resource.url,
        cloud_id=resource.id,
        scopes=tuple(sorted(set(resource.scopes))),
    )
