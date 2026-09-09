"""OAuth authorization for curated vendor installations.

The vendor registry owns endpoints, scopes, delimiters, extra
authorization parameters, and whether PKCE is required, so all of that comes
from the registry. The organization supplies only what is genuinely its own —
a client id, a client secret, and a tenant where the provider is per-tenant.

This keeps provider-owned protocol details out of organization configuration.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from urllib.parse import urlencode
from uuid import UUID

from pydantic import JsonValue

from eylo.common.database import start_transaction
from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpRoutePolicy,
    parse_https_target,
)
from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.connections import (
    ConnectionFailedEvent,
    ConnectionSuccessEvent,
)
from eylo.modules.connections.domain import ExternalConnectionStatus
from eylo.modules.connections.repositories.oauth_state import OAuthStateRepository
from eylo.modules.connections.schemas.oauth import OAuthStateCreateSchema
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.modules.integrations_v2.constants import OAUTH_CALLBACK_PATH
from eylo.modules.integrations_v2.domain.errors import (
    IntegrationsV2Error,
    VendorNotFoundError,
)
from eylo.modules.integrations_v2.schemas.indb import InstallationInDb
from eylo.modules.integrations_v2.services.installations import (
    CuratedIntegrationService,
)
from eylo.modules.provider_configs.crypto import get_secret_cipher
from eylo.sockets.http.transport import SafeHttpTransport

from .connections import (
    activate_curated_external_connection,
    create_curated_external_connection,
)
from .contracts import CuratedVendorSpec, VendorOAuthConfig
from .http_client import VendorTransport
from .oauth_contracts import (
    AuthorizationCodeRequest,
    AuthorizationCompletion,
    AuthorizationRedirect,
    AuthorizationRejection,
    CuratedOAuthCode,
    CuratedOAuthError,
)
from .oauth_tokens import OAuthTokenError, OAuthTokenErrorCode, OAuthTokenResponse
from .registry import CuratedRegistry, load_vendors

STATE_TTL_MINUTES = 10
_SECRET_LABEL = "curated_oauth_client_secret"
_TOKEN_RESPONSE_BODY_LIMIT = 262_144
_TOKEN_REQUEST_TIMEOUT_SECONDS = 20.0
_STATE_ENTROPY_BYTES = 32
_PKCE_ENTROPY_BYTES = 64
_PKCE_VERIFIER_MAX_LENGTH = 128
_PKCE_CHALLENGE_METHOD = "S256"
_AUTHORIZATION_RESPONSE_TYPE = "code"


def default_callback_url() -> str:
    """The one redirect URI every curated vendor's OAuth app registers."""
    from eylo.common.config import settings

    if settings.OAUTH_CALLBACK_URL:
        return settings.OAUTH_CALLBACK_URL
    if not settings.API_BASE_URL:
        raise CuratedOAuthError(
            CuratedOAuthCode.CALLBACK_NOT_CONFIGURED,
            "Configure the public API URL or OAuth callback URL.",
        )
    return f"{settings.API_BASE_URL.rstrip('/')}{OAUTH_CALLBACK_PATH}"


def encrypt_client_secret(secret: str) -> str:
    return get_secret_cipher().encrypt_field(secret, context_label=_SECRET_LABEL)


def decrypt_client_secret(envelope: str) -> str:
    return get_secret_cipher().decrypt_field(envelope, context_label=_SECRET_LABEL)


async def begin_authorization(
    *,
    installation: InstallationInDb,
    vendor: CuratedVendorSpec,
    contact_id: UUID | None = None,
    states: OAuthStateRepository | None = None,
) -> AuthorizationRedirect:
    """Build the provider consent URL for one installation."""
    oauth = _require_oauth(vendor, installation)
    redirect_uri = default_callback_url()
    state_token = secrets.token_urlsafe(_STATE_ENTROPY_BYTES)
    verifier, challenge = _pkce_pair() if oauth.pkce else (None, None)

    connection = await create_curated_external_connection(
        installation=installation,
        contact_id=contact_id,
        credentials=None,
        credentials_expires_at=None,
        granted_scopes=oauth.scopes,
        status=ExternalConnectionStatus.INITIATED,
    )

    await (states or OAuthStateRepository()).create_state(
        OAuthStateCreateSchema(
            state=state_token,
            organization_id=installation.organization_id,
            external_connection_id=connection.id,
            redirect_uri=redirect_uri,
            code_verifier=verifier,
            requested_scopes=list(oauth.scopes),
            expected_connection_revision=connection.revision,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=STATE_TTL_MINUTES),
        )
    )

    params: dict[str, str] = {
        "client_id": installation.oauth_client_id or "",
        "redirect_uri": redirect_uri,
        "state": state_token,
        "response_type": _AUTHORIZATION_RESPONSE_TYPE,
    }
    # A vendor with no scope model — Notion grants capabilities at consent
    # instead — must not be sent an empty `scope`, which some providers reject.
    if oauth.scopes:
        params["scope"] = oauth.scope_delimiter.join(oauth.scopes)
    if challenge is not None:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = _PKCE_CHALLENGE_METHOD
    for key, value in oauth.authorization_params:
        params.setdefault(key, value)

    return AuthorizationRedirect(
        authorization_url=(
            f"{_tenanted(oauth.authorization_url, installation)}?{urlencode(params)}"
        ),
        redirect_uri=redirect_uri,
        state=state_token,
    )


async def complete_authorization(
    *,
    code: str,
    state: str,
    installation: InstallationInDb,
    vendor: CuratedVendorSpec,
    states: OAuthStateRepository | None = None,
    connections: ExternalConnectionService | None = None,
    transport: VendorTransport | None = None,
) -> UUID:
    """Exchange the authorization code and store the resulting connection.

    The state row is consumed in its own committed transaction *before* the
    exchange is attempted. Doing it in the same transaction looked correct and
    was not: any later failure rolled the deletion back, leaving the state alive
    and the authorization code replayable. A one-time token has to be spent the
    moment it is presented, whatever happens next.
    """
    async with start_transaction():
        consumed = states or OAuthStateRepository()
        candidate = await consumed.get_by_state(state)
        if candidate is None or candidate.redirect_uri != default_callback_url():
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        stored = await consumed.consume_by_state(state)
        if stored is None:
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        connection_service = connections or ExternalConnectionService()
        connection = await connection_service.get(
            organization_id=installation.organization_id,
            connection_id=stored.external_connection_id,
        )
        linked_installation = (
            await CuratedIntegrationService().resolve_installation_for_connection(
                organization_id=installation.organization_id,
                connection_id=stored.external_connection_id,
            )
        )
        expired = stored.is_expired()
        redirect_uri = stored.redirect_uri or default_callback_url()
        code_verifier = stored.code_verifier
        organization_id = stored.organization_id
        expected_revision = stored.expected_connection_revision
    # Report linkage failures only after spending this one-time state commits.
    if (
        organization_id != installation.organization_id
        or connection is None
        or linked_installation is None
        or linked_installation.id != installation.id
    ):
        raise CuratedOAuthError(
            CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
        )
    if expired:
        async with start_transaction():
            await ExternalConnectionService().revoke_pending_authorization_attempt(
                organization_id=installation.organization_id,
                connection_id=connection.id,
                expected_revision=expected_revision,
            )
        raise CuratedOAuthError(
            CuratedOAuthCode.STATE_EXPIRED, "Authorization state has expired."
        )
    if connection.revision != expected_revision:
        raise CuratedOAuthError(
            CuratedOAuthCode.STATE_INVALID, "Authorization state is no longer current."
        )

    oauth = _require_oauth(vendor, installation)
    tokens = await _exchange(
        code=code,
        token_url=_tenanted(oauth.token_url, installation),
        installation=installation,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        transport=transport,
    )

    credentials: dict[str, JsonValue] = {"access_token": tokens.access_token}
    if tokens.refresh_token is not None:
        credentials["refresh_token"] = tokens.refresh_token
    if tokens.token_type is not None:
        credentials["token_type"] = tokens.token_type
    if tokens.scope is not None:
        credentials["scope"] = tokens.scope
    try:
        expires_at = tokens.expires_at(datetime.now(timezone.utc))
    except OAuthTokenError:
        raise CuratedOAuthError(
            CuratedOAuthCode.TOKEN_INVALID,
            "The provider returned an unreadable token response.",
        ) from None

    async with start_transaction():
        activated = await activate_curated_external_connection(
            connection=connection,
            credentials=credentials,
            credentials_expires_at=expires_at,
            granted_scopes=_granted_scopes(
                tokens=tokens,
                requested=oauth.scopes,
                delimiter=oauth.scope_delimiter,
            ),
            service=connections,
        )
        return activated.id


async def complete_authorization_from_state(
    *,
    code: str,
    state: str,
    registry: CuratedRegistry | None = None,
    states: OAuthStateRepository | None = None,
) -> AuthorizationCompletion:
    """Complete an authorization knowing only the code and the state.

    This is the entry point a provider redirect can actually reach. The end
    user arriving here is a contact authorizing access on their own behalf —
    they have no session in the operator console and no organization in the
    URL — so the state row is the only thing that identifies the flow, which is
    exactly the property OAuth state is for.

    Returns the new connection id and the vendor it authorizes.
    """
    repository = states or OAuthStateRepository()
    async with start_transaction():
        stored = await repository.get_by_state(state)
        if stored is None:
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        if stored.redirect_uri != default_callback_url():
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        connection = await ExternalConnectionService().get(
            organization_id=stored.organization_id,
            connection_id=stored.external_connection_id,
        )
        installation = (
            await CuratedIntegrationService().resolve_installation_for_connection(
                organization_id=stored.organization_id,
                connection_id=stored.external_connection_id,
            )
        )
        if connection is None or installation is None:
            # Consume the state: it can never complete, and leaving it alive
            # only keeps an authorization code replayable.
            await repository.consume_by_state(state)
        organization_id = stored.organization_id

    if connection is None or installation is None:
        raise CuratedOAuthError(
            CuratedOAuthCode.INSTALLATION_REMOVED,
            "The vendor installation this authorization belongs to is gone.",
        )
    contact_id = connection.contact_id

    vendor = (registry or load_vendors()).vendor(installation.vendor)
    if vendor is None:
        async with start_transaction():
            await repository.consume_by_state(state)
        raise VendorNotFoundError(
            CuratedOAuthCode.VENDOR_NOT_REGISTERED,
            f"This deployment no longer carries '{installation.vendor}'.",
        )

    # Notify the widget and the end user's conversation about the outcome.
    try:
        connection_id = await complete_authorization(
            code=code,
            state=state,
            installation=installation,
            vendor=vendor,
            states=repository,
        )
    except IntegrationsV2Error as failure:
        if contact_id is not None:
            emit_ephemeral(
                ConnectionFailedEvent(
                    contact_id=contact_id,
                    organization_id=organization_id,
                    integration_name=vendor.display_name,
                    error=str(failure),
                    integration_id=installation.id,
                    vendor=installation.vendor,
                )
            )
        raise
    if contact_id is not None:
        emit_ephemeral(
            ConnectionSuccessEvent(
                connection_id=connection_id,
                contact_id=contact_id,
                organization_id=organization_id,
                integration_name=vendor.display_name,
                integration_id=installation.id,
                vendor=installation.vendor,
            )
        )
    return AuthorizationCompletion(
        connection_id=connection_id, vendor=installation.vendor
    )


async def reject_authorization_from_state(
    *,
    state: str,
    reason: AuthorizationRejection,
    states: OAuthStateRepository | None = None,
) -> None:
    """Commit callback rejection before notifying the contact; never call a vendor.

    Only the matching initiated revision can be revoked. A newer or active
    connection survives an old declined/empty callback.
    """
    if not isinstance(reason, AuthorizationRejection):
        raise TypeError("Callback rejection requires an AuthorizationRejection.")
    async with start_transaction():
        repository = states or OAuthStateRepository()
        candidate = await repository.get_by_state(state)
        if candidate is None or candidate.redirect_uri != default_callback_url():
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        stored = await repository.consume_by_state(state)
        if stored is None:
            raise CuratedOAuthError(
                CuratedOAuthCode.STATE_INVALID, "Authorization state is unknown."
            )
        service = ExternalConnectionService()
        connection = await service.get(
            organization_id=stored.organization_id,
            connection_id=stored.external_connection_id,
        )
        installation = (
            await CuratedIntegrationService().resolve_installation_for_connection(
                organization_id=stored.organization_id,
                connection_id=stored.external_connection_id,
            )
        )
        await service.revoke_pending_authorization_attempt(
            organization_id=stored.organization_id,
            connection_id=stored.external_connection_id,
            expected_revision=stored.expected_connection_revision,
        )
    if (
        connection is not None
        and connection.contact_id is not None
        and installation is not None
    ):
        vendor = load_vendors().vendor(installation.vendor)
        if vendor is not None:
            emit_ephemeral(
                ConnectionFailedEvent(
                    contact_id=connection.contact_id,
                    organization_id=connection.organization_id,
                    integration_name=vendor.display_name,
                    error=reason.message,
                    integration_id=installation.id,
                    vendor=installation.vendor,
                )
            )


async def _exchange(
    *,
    code: str,
    token_url: str,
    installation: InstallationInDb,
    redirect_uri: str,
    code_verifier: str | None,
    transport: VendorTransport | None,
) -> OAuthTokenResponse:
    if not installation.oauth_client_id or not installation.oauth_client_secret:
        raise CuratedOAuthError(
            CuratedOAuthCode.APP_MISSING,
            "This installation has no OAuth client credentials configured.",
        )
    form = AuthorizationCodeRequest(
        code=code,
        client_id=installation.oauth_client_id,
        client_secret=decrypt_client_secret(installation.oauth_client_secret),
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    ).to_form()

    try:
        origin, path = parse_https_target(token_url)
        request = HttpEgressRequest(
            method="POST",
            url=token_url,
            policy=HttpDestinationPolicy(
                primary=HttpRoutePolicy(origin=origin, path_prefix=path),
                max_redirects=0,
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=urlencode(form).encode("utf-8"),
            response_body_limit=_TOKEN_RESPONSE_BODY_LIMIT,
            total_timeout_seconds=_TOKEN_REQUEST_TIMEOUT_SECONDS,
        )
        response = await (transport or SafeHttpTransport()).send(request)
    except (HttpEgressPolicyError, TimeoutError) as error:
        raise CuratedOAuthError(
            CuratedOAuthCode.ENDPOINT_UNREACHABLE,
            "The provider token endpoint could not be reached safely.",
        ) from error

    if response.status_code != HTTPStatus.OK:
        raise CuratedOAuthError(
            CuratedOAuthCode.EXCHANGE_REJECTED,
            "The provider rejected the authorization code exchange.",
        )
    try:
        return OAuthTokenResponse.from_body(response.body)
    except OAuthTokenError as error:
        message = (
            "The provider returned no access token."
            if error.code is OAuthTokenErrorCode.MISSING_ACCESS_TOKEN
            else "The provider returned an unreadable token response."
        )
        raise CuratedOAuthError(CuratedOAuthCode.TOKEN_INVALID, message) from None


def _require_oauth(
    vendor: CuratedVendorSpec, installation: InstallationInDb
) -> VendorOAuthConfig:
    if vendor.oauth is None:
        raise VendorNotFoundError(
            CuratedOAuthCode.VENDOR_OAUTH_UNSUPPORTED,
            f"Vendor '{vendor.vendor}' does not support OAuth.",
        )
    if not installation.oauth_client_id or not installation.oauth_client_secret:
        raise CuratedOAuthError(
            CuratedOAuthCode.APP_MISSING,
            "This installation has no OAuth client credentials configured.",
        )
    return vendor.oauth


def _tenanted(url: str, installation: InstallationInDb) -> str:
    if "{tenant}" not in url:
        return url
    tenant = installation.oauth_tenant
    if not isinstance(tenant, str) or not _TENANT.fullmatch(tenant.strip()):
        raise CuratedOAuthError(
            CuratedOAuthCode.TENANT_INVALID,
            "This vendor requires a valid OAuth tenant.",
        )
    return url.replace("{tenant}", tenant.strip())


_TENANT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(_PKCE_ENTROPY_BYTES)[:_PKCE_VERIFIER_MAX_LENGTH]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _granted_scopes(
    *,
    tokens: OAuthTokenResponse,
    requested: tuple[str, ...],
    delimiter: str,
) -> list[str]:
    raw = tokens.scope
    if not isinstance(raw, str) or not raw.strip():
        return list(requested)
    separator = delimiter or " "
    return [scope.strip() for scope in raw.split(separator) if scope.strip()]


__all__ = [
    "AuthorizationRedirect",
    "complete_authorization_from_state",
    "default_callback_url",
    "CuratedOAuthError",
    "STATE_TTL_MINUTES",
    "begin_authorization",
    "complete_authorization",
    "decrypt_client_secret",
    "encrypt_client_secret",
]
