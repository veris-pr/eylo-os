"""Resolve scoped credentials; refuse expired grants without inline refresh I/O."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf, field_serializer
from pydantic.json_schema import SkipJsonSchema

from eylo.common.database import current_transaction, start_transaction
from eylo.common.http_egress import (
    HttpEgressPolicyError,
    HttpOrigin,
    parse_https_target,
)
from eylo.modules.connections.schemas.external import ExternalConnectionInDb
from eylo.modules.integrations_v2.domain.enums import VendorAuthKind
from eylo.modules.integrations_v2.domain.errors import (
    CredentialUnavailableError,
    IntegrationErrorCode,
    VendorNotFoundError,
)
from eylo.modules.integrations_v2.schemas.indb import ToolExecutionGrant
from eylo.modules.integrations_v2.services.installations import (
    CuratedIntegrationService,
)
from eylo.pipelines.external_connections.credentials import (
    decrypt_connection_credentials,
)

from .contracts import CuratedVendorSpec, VendorAccount
from .credentials import VendorWireAuth, build_vendor_wire_auth
from .oauth_contracts import CuratedOAuthError
from .registry import CuratedRegistry, load_vendors
from .vendors.atlassian_oauth import product_for_vendor, require_site_binding
from .vendors.calendly.schemas import VENDOR_KEY as CALENDLY_VENDOR_KEY
from .vendors.calendly.schemas import effective_scopes as calendly_effective_scopes

NO_AUTH_CONNECTION_ID = "no-auth"
_REQUEST_BUDGET_SECONDS: Final = 20.0


class ResolvedVendorAuth(BaseModel):
    """Client-construction values; credentials stay live and out of snapshots."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    vendor: CuratedVendorSpec
    base_url: str
    origin: InstanceOf[HttpOrigin]
    auth: SkipJsonSchema[VendorWireAuth] = Field(repr=False, exclude=True)
    account: VendorAccount

    @field_serializer("origin")
    def serialize_origin(self, value: HttpOrigin) -> str:
        return str(value)


async def resolve_vendor_auth(
    *,
    grant: ToolExecutionGrant,
    contact_id: UUID | None = None,
    registry: CuratedRegistry | None = None,
    connections: CuratedIntegrationService | None = None,
    required_scopes: Sequence[str] = (),
    request_budget_seconds: float = _REQUEST_BUDGET_SECONDS,
) -> ResolvedVendorAuth:
    """Resolve the credential authorizing one curated tool call.

    Missing, expiring, or mismatched grants produce `auth_required`. Malformed
    credential material retains its distinct safe validation error code.
    An owned DB-only lookup closes before decryption and wire-auth construction;
    an injected service or ambient session is never committed or closed here.
    """
    vendor = (registry or load_vendors()).vendor(grant.vendor)
    if vendor is None:
        raise VendorNotFoundError(
            "vendor_not_registered",
            f"This deployment does not carry vendor '{grant.vendor}'.",
        )
    try:
        base_url = vendor.resolve_base_url(grant.instance_url)
        origin, _path = parse_https_target(base_url)
    except (ValueError, HttpEgressPolicyError) as error:
        raise VendorNotFoundError(
            "vendor_base_url_invalid",
            f"Vendor '{grant.vendor}' has no usable base URL for this install.",
        ) from error

    if grant.auth_kind is VendorAuthKind.NO_AUTH:
        return ResolvedVendorAuth(
            vendor=vendor,
            base_url=base_url,
            origin=origin,
            auth=VendorWireAuth(),
            account=VendorAccount(connection_id=NO_AUTH_CONNECTION_ID),
        )

    connection = await _active_connection(
        installation_id=grant.installation_id,
        organization_id=grant.organization_id,
        contact_id=contact_id,
        service=connections,
    )
    if connection is None:
        raise CredentialUnavailableError(
            IntegrationErrorCode.AUTH_REQUIRED,
            f"No active connection authorizes '{grant.vendor}' for this caller.",
        )
    if _expires_within(connection.credentials_expires_at, request_budget_seconds):
        raise CredentialUnavailableError(
            IntegrationErrorCode.AUTH_REQUIRED,
            f"The '{grant.vendor}' credential expires inside the request budget.",
        )
    if (
        connection.organization_id != grant.organization_id
        or connection.vendor_key != grant.vendor
        or connection.auth_kind.value != grant.auth_kind.value
        or connection.instance_origin != grant.instance_url
    ):
        raise CredentialUnavailableError(
            IntegrationErrorCode.AUTH_REQUIRED,
            f"The stored '{grant.vendor}' authorization no longer matches its install.",
        )
    granted_scopes = set(connection.granted_scopes)
    if grant.vendor == CALENDLY_VENDOR_KEY:
        granted_scopes = calendly_effective_scopes(granted_scopes)
    if grant.auth_kind is VendorAuthKind.OAUTH2 and not set(required_scopes).issubset(
        granted_scopes
    ):
        raise CredentialUnavailableError(
            IntegrationErrorCode.AUTH_REQUIRED,
            f"The '{grant.vendor}' authorization requires additional scopes.",
        )
    if connection.credentials is None:
        raise CredentialUnavailableError(
            IntegrationErrorCode.AUTH_REQUIRED,
            f"The '{grant.vendor}' credential is unavailable.",
        )
    credentials = decrypt_connection_credentials(
        connection.credentials,
        organization_id=grant.organization_id,
        connection_id=connection.id,
        revision=connection.revision,
    )

    product = product_for_vendor(grant.vendor)
    if grant.auth_kind is VendorAuthKind.OAUTH2 and product is not None:
        try:
            binding = require_site_binding(
                credentials,
                product=product,
                site_origin=grant.instance_url,
                required_scopes=required_scopes,
            )
        except CuratedOAuthError:
            raise CredentialUnavailableError(
                IntegrationErrorCode.AUTH_REQUIRED,
                "Reconnect the configured Atlassian site.",
            ) from None
        base_url = binding.gateway_url(_path)
        origin, _path = parse_https_target(base_url)

    auth = build_vendor_wire_auth(
        auth_kind=grant.auth_kind,
        credentials=credentials,
        origin=origin,
        api_key_placement=vendor.api_key_placement,
    )
    return ResolvedVendorAuth(
        vendor=vendor,
        base_url=base_url,
        origin=origin,
        auth=auth,
        account=VendorAccount(connection_id=str(connection.id)),
    )


async def _active_connection(
    *,
    installation_id: UUID,
    organization_id: UUID,
    contact_id: UUID | None,
    service: CuratedIntegrationService | None,
) -> ExternalConnectionInDb | None:
    if service is not None:
        return await service.get_active_external_connection(
            installation_id=installation_id,
            organization_id=organization_id,
            contact_id=contact_id,
        )
    session = current_transaction()
    scope = start_transaction(ro=True) if session is None else nullcontext(session)
    async with scope as db:
        return await CuratedIntegrationService(db).get_active_external_connection(
            installation_id=installation_id,
            organization_id=organization_id,
            contact_id=contact_id,
        )


def _expires_within(expires_at: datetime | None, budget_seconds: float) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    deadline = datetime.now(timezone.utc) + timedelta(seconds=budget_seconds)
    return expires_at <= deadline


__all__ = [
    "NO_AUTH_CONNECTION_ID",
    "ResolvedVendorAuth",
    "resolve_vendor_auth",
]
