"""OAuth authorization for organization-owned SOR connectors."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import uuid_utils

from eylo.common.database import start_transaction
from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpRoutePolicy,
    parse_https_target,
)
from eylo.modules.connections.domain import (
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.repositories.oauth_state import OAuthStateRepository
from eylo.modules.connections.schemas.external import ExternalConnectionCreateSchema
from eylo.modules.connections.schemas.oauth import OAuthStateCreateSchema
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.pipelines.external_connections.credentials import (
    encrypt_connection_credentials,
)
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sor.runtime.action_events import file_sor_connection_event
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.oauth_endpoints import (
    SorOAuthEndpointError,
    resolve_oauth_authorization_url,
    resolve_oauth_token_url,
)
from eylo.sor.runtime.oauth_payload import (
    apply_oauth_client_auth,
    encode_oauth_token_request,
)
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.connector_services import SorConnectorService
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorChangeMode,
    SorChangeStrategy,
    SorOAuthSpec,
    SorSourceAccess,
    SorSourceState,
    SorSyncRunKind,
)
from eylo.sor.shared.models import SorConnectorModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_connector_client_secret,
)
from eylo.sor.shared.services import SorConfigurationError, SorSourceService
from eylo.sor.shared.webhook_urls import public_webhook_api_base_url

SOR_OAUTH_CALLBACK_PATH = "/sor/oauth/callback"
STATE_TTL_MINUTES = 10
logger = logging.getLogger(__name__)


class SorOAuthError(Exception):
    """A safe OAuth refusal with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SorOAuthTransport:
    """Structural port for recorded OAuth transport proofs."""

    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


@dataclass(frozen=True, slots=True)
class SorAuthorizationRedirect:
    authorization_url: str
    callback_url: str
    state: str


@dataclass(frozen=True, slots=True)
class SorAuthorizationResult:
    connection_id: UUID
    vendor_key: str


@dataclass(frozen=True, slots=True)
class _AuthorizationContext:
    organization_id: UUID
    connector_id: UUID
    connector_revision: int
    connection_id: UUID
    expected_connection_revision: int
    vendor_key: str
    client_id: str
    client_secret: str
    redirect_uri: str
    code_verifier: str | None
    requested_scopes: tuple[str, ...]
    oauth: SorOAuthSpec
    change_mode: SorChangeMode
    fixed_origin: str | None
    preset_instance_origin: str | None


def default_sor_callback_url() -> str:
    """Return the exact callback URL an operator registers with the vendor."""
    from eylo.common.config import settings

    base_url = settings.API_BASE_URL
    if not isinstance(base_url, str) or not base_url.strip():
        raise SorOAuthError(
            "oauth_callback_unconfigured",
            "The SOR OAuth callback base URL is not configured.",
        )
    return f"{base_url.rstrip('/')}{SOR_OAUTH_CALLBACK_PATH}"


async def begin_sor_authorization(
    *,
    organization_id: UUID,
    connector_id: UUID,
    selected_objects: tuple[str, ...],
    access: SorSourceAccess,
    instance_origin: str | None = None,
    registry: SorRegistry | None = None,
) -> SorAuthorizationRedirect:
    """Create one state-bound connection attempt and return its consent URL."""
    active_registry = registry or get_sor_registry()
    callback_url = default_sor_callback_url()
    state_token = secrets.token_urlsafe(32)

    async with start_transaction() as session:
        view = await SorConnectorService(
            session,
            registry=active_registry,
        ).get(
            organization_id=organization_id,
            connector_id=connector_id,
            for_update=True,
        )
        connector = view.connector
        manifest = active_registry.get_manifest(
            profile=connector.profile,
            vendor_key=connector.vendor_key,
        )
        oauth = _require_oauth(manifest)
        _require_app_webhook_authorization_ready(
            connector=connector,
            manifest=manifest,
        )
        requested_instance_origin = _authorization_instance_origin(
            oauth=oauth,
            value=instance_origin,
        )
        objects = _selected_objects(manifest, selected_objects)
        requested_scopes = _requested_scopes(
            manifest=manifest,
            selected_objects=objects,
            access=access,
        )
        connection = view.connection
        if connection is None:
            connection_id = uuid.UUID(str(uuid_utils.uuid7()))
            connection = await ExternalConnectionService(session).create(
                ExternalConnectionCreateSchema(
                    id=connection_id,
                    organization_id=organization_id,
                    owner_kind=ConnectionOwnerKind.ORGANIZATION,
                    vendor_key=connector.vendor_key,
                    auth_kind=connector.auth_kind,
                    instance_origin=(
                        requested_instance_origin
                        if manifest.requires_instance_origin
                        else manifest.fixed_origin
                    ),
                    status=ExternalConnectionStatus.INITIATED,
                )
            )
            connector.external_connection_id = connection.id
            await session.flush()
        elif oauth.operator_instance_origin:
            if connection.instance_origin != requested_instance_origin:
                raise SorOAuthError(
                    "oauth_instance_origin_changed",
                    "This saved connection belongs to another provider site. "
                    "Create a new connection for this site.",
                )

        verifier, challenge = _pkce_pair() if oauth.pkce else (None, None)
        await OAuthStateRepository(session).create_state(
            OAuthStateCreateSchema(
                state=state_token,
                organization_id=organization_id,
                external_connection_id=connection.id,
                redirect_uri=callback_url,
                code_verifier=verifier,
                requested_scopes=list(requested_scopes),
                expected_connection_revision=connection.revision,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=STATE_TTL_MINUTES),
            )
        )
        client_id = connector.oauth_client_id

    return _authorization_redirect(
        callback_url=callback_url,
        challenge=challenge,
        client_id=client_id,
        fixed_origin=manifest.fixed_origin,
        oauth=oauth,
        requested_instance_origin=requested_instance_origin,
        requested_scopes=requested_scopes,
        state_token=state_token,
    )


async def begin_sor_source_reauthorization(
    *,
    organization_id: UUID,
    source_id: UUID,
    registry: SorRegistry | None = None,
) -> SorAuthorizationRedirect:
    """Restart OAuth for an activated source without changing its identity."""
    active_registry = registry or get_sor_registry()
    callback_url = default_sor_callback_url()
    state_token = secrets.token_urlsafe(32)

    async with start_transaction() as session:
        repository = SorRepository(session)
        source = await SorSourceService(
            session,
            registry=active_registry,
        ).get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state not in {
            SorSourceState.ACTIVE,
            SorSourceState.DEGRADED,
            SorSourceState.REAUTH_REQUIRED,
        }:
            raise SorOAuthError(
                "source_reauthorization_unavailable",
                "Only an activated source can restart provider authorization.",
            )
        if (
            source.active_schema_revision_id is None
            or source.active_mapping_revision_id is None
        ):
            raise SorOAuthError(
                "source_not_activated",
                "This source has not been activated. Continue source setup instead.",
            )

        connector = await repository.get_connector_for_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            for_update=True,
        )
        connection = await repository.get_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            vendor_key=source.vendor_key,
            for_update=True,
            include_deleted=True,
        )
        if (
            connector is None
            or connection is None
            or connector.profile is not source.profile
            or connector.vendor_key != source.vendor_key
        ):
            raise SorOAuthError(
                "source_connector_unavailable",
                "The source OAuth connector is unavailable.",
            )
        if connection.owner_kind is not ConnectionOwnerKind.ORGANIZATION:
            raise SorOAuthError(
                "source_connection_owner_invalid",
                "The source connection is not organization-owned.",
            )

        manifest = active_registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        oauth = _require_oauth(manifest)
        _require_app_webhook_authorization_ready(
            connector=connector,
            manifest=manifest,
        )
        previous_instance_origin = connection.instance_origin
        previous_granted_scopes = tuple(connection.granted_scopes or ())
        if connection.deleted or connection.status is ExternalConnectionStatus.REVOKED:
            replacement = await ExternalConnectionService(session).create(
                ExternalConnectionCreateSchema(
                    id=uuid.UUID(str(uuid_utils.uuid7())),
                    organization_id=organization_id,
                    owner_kind=ConnectionOwnerKind.ORGANIZATION,
                    vendor_key=source.vendor_key,
                    auth_kind=connector.auth_kind,
                    instance_origin=previous_instance_origin,
                    status=ExternalConnectionStatus.INITIATED,
                )
            )
            connector.external_connection_id = replacement.id
            source.external_connection_id = replacement.id
            source.config_revision += 1
            connection = replacement
            await session.flush()
        elif connection.status not in {
            ExternalConnectionStatus.INITIATED,
            ExternalConnectionStatus.ACTIVE,
            ExternalConnectionStatus.DEGRADED,
            ExternalConnectionStatus.REAUTH_REQUIRED,
        }:
            raise SorOAuthError(
                "source_connection_unavailable",
                "The source connection cannot be reauthorized.",
            )

        requested_instance_origin = _authorization_instance_origin(
            oauth=oauth,
            value=(
                previous_instance_origin if oauth.operator_instance_origin else None
            ),
        )
        objects = _selected_objects(
            manifest,
            tuple(str(value) for value in source.selected_objects),
        )
        grants = await repository.list_live_source_grants(
            organization_id=organization_id,
            source_id=source.id,
        )
        access = (
            SorSourceAccess.READ_WRITE
            if any(grant.access is SorSourceAccess.READ_WRITE for grant in grants)
            else SorSourceAccess.READ
        )
        requested_scopes = tuple(
            dict.fromkeys(
                [
                    *previous_granted_scopes,
                    *_requested_scopes(
                        manifest=manifest,
                        selected_objects=objects,
                        access=access,
                    ),
                ]
            )
        )
        verifier, challenge = _pkce_pair() if oauth.pkce else (None, None)
        await OAuthStateRepository(session).create_state(
            OAuthStateCreateSchema(
                state=state_token,
                organization_id=organization_id,
                external_connection_id=connection.id,
                redirect_uri=callback_url,
                code_verifier=verifier,
                requested_scopes=list(requested_scopes),
                expected_connection_revision=connection.revision,
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=STATE_TTL_MINUTES),
            )
        )
        client_id = connector.oauth_client_id

    return _authorization_redirect(
        callback_url=callback_url,
        challenge=challenge,
        client_id=client_id,
        fixed_origin=manifest.fixed_origin,
        oauth=oauth,
        requested_instance_origin=requested_instance_origin,
        requested_scopes=requested_scopes,
        state_token=state_token,
    )


def _authorization_redirect(
    *,
    callback_url: str,
    challenge: str | None,
    client_id: str,
    fixed_origin: str | None,
    oauth: SorOAuthSpec,
    requested_instance_origin: str | None,
    requested_scopes: tuple[str, ...],
    state_token: str,
) -> SorAuthorizationRedirect:
    """Build one consent URL from already persisted OAuth state."""
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": callback_url,
        "state": state_token,
    }
    if oauth.authorization_response_type is not None:
        params["response_type"] = oauth.authorization_response_type
    if oauth.send_authorization_scope:
        params["scope"] = oauth.scope_delimiter.join(requested_scopes)
    params.update(oauth.authorization_params)
    if challenge is not None:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    try:
        authorization_url = resolve_oauth_authorization_url(
            oauth,
            instance_origin=requested_instance_origin or fixed_origin,
        )
    except SorOAuthEndpointError as error:
        raise SorOAuthError(
            "oauth_endpoint_invalid",
            "The provider authorization endpoint is not configured safely.",
        ) from error
    return SorAuthorizationRedirect(
        authorization_url=f"{authorization_url}?{urlencode(params)}",
        callback_url=callback_url,
        state=state_token,
    )


async def complete_sor_authorization_from_state(
    *,
    code: str,
    state: str,
    registry: SorRegistry | None = None,
    transport: SorOAuthTransport | None = None,
) -> SorAuthorizationResult:
    """Consume state, exchange the code once, then activate the exact connection."""
    active_registry = registry or get_sor_registry()
    context = await _consume_authorization_context(
        state=state,
        registry=active_registry,
    )
    try:
        tokens = await _exchange_code(
            code=code,
            context=context,
            transport=transport,
        )
        credentials, expires_at, granted_scopes, instance_origin = _token_grant(
            tokens=tokens,
            context=context,
        )
        connection_revision = await _activate_connection(
            context=context,
            credentials=credentials,
            expires_at=expires_at,
            granted_scopes=granted_scopes,
            instance_origin=instance_origin,
        )
    except Exception:
        await _revoke_initiated_connection(context)
        raise
    restored_source_ids = await _restore_reauthorized_sources(
        organization_id=context.organization_id,
        connection_id=context.connection_id,
        connection_revision=connection_revision,
        registry=active_registry,
    )
    for source_id in restored_source_ids:
        await _schedule_reauthorization_catch_up(
            organization_id=context.organization_id,
            source_id=source_id,
        )
    return SorAuthorizationResult(
        connection_id=context.connection_id,
        vendor_key=context.vendor_key,
    )


async def decline_sor_authorization(*, state: str) -> None:
    """Spend a declined authorization state and revoke only an initiated account."""
    try:
        context = await _consume_authorization_context(
            state=state,
            registry=get_sor_registry(),
            allow_expired=True,
        )
    except SorOAuthError:
        return
    await _revoke_initiated_connection(context)


async def _consume_authorization_context(
    *,
    state: str,
    registry: SorRegistry,
    allow_expired: bool = False,
) -> _AuthorizationContext:
    async with start_transaction() as session:
        states = OAuthStateRepository(session)
        candidate = await states.get_by_state(state)
        if candidate is None or candidate.redirect_uri != default_sor_callback_url():
            raise SorOAuthError(
                "oauth_state_invalid",
                "Authorization state is unknown or already used.",
            )
        stored = await states.consume_by_state(state)
        if stored is None:
            raise SorOAuthError(
                "oauth_state_invalid",
                "Authorization state is unknown or already used.",
            )
        repository = SorRepository(session)
        connector = await repository.get_connector_for_connection(
            organization_id=stored.organization_id,
            connection_id=stored.external_connection_id,
        )
        connection = await repository.get_connection(
            organization_id=stored.organization_id,
            connection_id=stored.external_connection_id,
            vendor_key=connector.vendor_key if connector is not None else "",
        )
        if connector is None or connection is None:
            raise SorOAuthError(
                "oauth_state_invalid",
                "Authorization state does not belong to a SOR connector.",
            )
        if (
            stored.expected_connection_revision is None
            or stored.expected_connection_revision != connection.revision
        ):
            raise SorOAuthError(
                "oauth_state_stale",
                "The connection changed after this authorization started.",
            )
        manifest = registry.get_manifest(
            profile=connector.profile,
            vendor_key=connector.vendor_key,
        )
        oauth = _require_oauth(manifest)
        try:
            client_secret = decrypt_connector_client_secret(
                connector.oauth_client_secret,
                organization_id=connector.organization_id,
                connector_id=connector.id,
                config_revision=connector.config_revision,
            )
        except SorSecretEnvelopeError as error:
            raise SorOAuthError(
                "oauth_app_unavailable",
                "The SOR connector credentials could not be opened.",
            ) from error
        expired = stored.is_expired()
        context = _AuthorizationContext(
            organization_id=connector.organization_id,
            connector_id=connector.id,
            connector_revision=connector.config_revision,
            connection_id=connection.id,
            expected_connection_revision=connection.revision,
            vendor_key=connector.vendor_key,
            client_id=connector.oauth_client_id,
            client_secret=client_secret,
            redirect_uri=stored.redirect_uri or default_sor_callback_url(),
            code_verifier=stored.code_verifier,
            requested_scopes=tuple(stored.requested_scopes or ()),
            oauth=oauth,
            change_mode=manifest.change_mode,
            fixed_origin=manifest.fixed_origin,
            preset_instance_origin=connection.instance_origin,
        )
    if expired and not allow_expired:
        await _revoke_initiated_connection(context)
        raise SorOAuthError(
            "oauth_state_expired",
            "Authorization state has expired.",
        )
    return context


async def _exchange_code(
    *,
    code: str,
    context: _AuthorizationContext,
    transport: SorOAuthTransport | None,
) -> dict[str, object]:
    normalized_code = code.strip()
    if not normalized_code or len(normalized_code) > 8192:
        raise SorOAuthError(
            "oauth_code_invalid",
            "The provider returned an invalid authorization code.",
        )
    form = {"code": normalized_code}
    if context.oauth.token_grant_type is not None:
        form["grant_type"] = context.oauth.token_grant_type
    if context.oauth.send_token_redirect_uri:
        form["redirect_uri"] = context.redirect_uri
    if context.code_verifier is not None:
        form["code_verifier"] = context.code_verifier
    form, auth_headers = apply_oauth_client_auth(
        context.oauth,
        form,
        client_id=context.client_id,
        client_secret=context.client_secret,
    )
    content_type, body = encode_oauth_token_request(context.oauth, form)
    try:
        token_url = resolve_oauth_token_url(
            context.oauth,
            instance_origin=context.preset_instance_origin or context.fixed_origin,
        )
        origin, path = parse_https_target(token_url)
        response = await (transport or SafeHttpTransport()).send(
            HttpEgressRequest(
                method="POST",
                url=token_url,
                policy=HttpDestinationPolicy(
                    primary=HttpRoutePolicy(origin=origin, path_prefix=path),
                    max_redirects=0,
                ),
                headers={
                    "Accept": "application/json",
                    "Content-Type": content_type,
                    **auth_headers,
                },
                body=body,
                response_body_limit=262_144,
                total_timeout_seconds=20.0,
            )
        )
    except (HttpEgressPolicyError, SorOAuthEndpointError, TimeoutError) as error:
        raise SorOAuthError(
            "oauth_endpoint_unreachable",
            "The provider token endpoint could not be reached safely.",
        ) from error
    if response.status_code != 200:
        raise SorOAuthError(
            "oauth_exchange_rejected",
            "The provider rejected the authorization code exchange.",
        )
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, ValueError) as error:
        raise SorOAuthError(
            "oauth_token_invalid",
            "The provider returned an unreadable token response.",
        ) from error
    if not isinstance(payload, dict):
        raise SorOAuthError(
            "oauth_token_invalid",
            "The provider returned an unreadable token response.",
        )
    return payload


def _token_grant(
    *,
    tokens: dict[str, object],
    context: _AuthorizationContext,
) -> tuple[dict[str, object], datetime | None, list[str], str | None]:
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise SorOAuthError(
            "oauth_token_invalid",
            "The provider returned no access token.",
        )
    credentials: dict[str, object] = {"access_token": access_token}
    for key in ("refresh_token", "token_type"):
        value = tokens.get(key)
        if isinstance(value, str) and value:
            credentials[key] = value

    granted_scopes = _granted_scopes(tokens=tokens, context=context)
    missing_scopes = set(context.requested_scopes) - set(granted_scopes)
    if missing_scopes:
        raise SorOAuthError(
            "oauth_scope_missing",
            "The provider did not grant every required SOR permission.",
        )

    expires_at = None
    expires_in = tokens.get("expires_in")
    if isinstance(expires_in, int) and not isinstance(expires_in, bool):
        if expires_in <= 0:
            raise SorOAuthError(
                "oauth_token_invalid",
                "The provider returned an invalid token lifetime.",
            )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    instance_origin = context.preset_instance_origin or context.fixed_origin
    if context.oauth.instance_origin_field is not None:
        raw_origin = tokens.get(context.oauth.instance_origin_field)
        if not isinstance(raw_origin, str):
            raise SorOAuthError(
                "oauth_instance_origin_missing",
                "The provider returned no account API origin.",
            )
        instance_origin = normalize_sor_instance_origin(
            raw_origin,
            allowed_suffixes=context.oauth.instance_host_suffixes,
            allowed_origins=tuple(
                option.api_origin for option in context.oauth.instance_origin_options
            ),
        )
    elif context.oauth.operator_instance_origin and instance_origin is None:
        raise SorOAuthError(
            "oauth_instance_origin_missing",
            "The configured provider site is unavailable.",
        )
    return credentials, expires_at, granted_scopes, instance_origin


async def _activate_connection(
    *,
    context: _AuthorizationContext,
    credentials: dict[str, object],
    expires_at: datetime | None,
    granted_scopes: list[str],
    instance_origin: str | None,
) -> int:
    async with start_transaction() as session:
        repository = SorRepository(session)
        connector = await repository.get_connector(
            organization_id=context.organization_id,
            connector_id=context.connector_id,
            for_update=True,
        )
        connection = await repository.get_connection(
            organization_id=context.organization_id,
            connection_id=context.connection_id,
            vendor_key=context.vendor_key,
            for_update=True,
        )
        if (
            connector is None
            or connector.external_connection_id != context.connection_id
            or connector.config_revision != context.connector_revision
            or connection is None
            or connection.revision != context.expected_connection_revision
        ):
            raise SorOAuthError(
                "oauth_state_stale",
                "The SOR connector changed during authorization.",
            )
        next_revision = connection.revision + 1
        encrypted = encrypt_connection_credentials(
            credentials,
            organization_id=context.organization_id,
            connection_id=context.connection_id,
            revision=next_revision,
        )
        service = ExternalConnectionService(session)
        if connection.status in {
            ExternalConnectionStatus.INITIATED,
            ExternalConnectionStatus.REAUTH_REQUIRED,
        }:
            activated_connection = await service.activate(
                organization_id=context.organization_id,
                connection_id=context.connection_id,
                expected_revision=connection.revision,
                encrypted_credentials=encrypted,
                credentials_expires_at=expires_at,
                granted_scopes=granted_scopes,
                instance_origin=instance_origin,
            )
        elif connection.status in {
            ExternalConnectionStatus.ACTIVE,
            ExternalConnectionStatus.DEGRADED,
        }:
            activated_connection = await service.renew_credentials(
                organization_id=context.organization_id,
                connection_id=context.connection_id,
                expected_revision=connection.revision,
                encrypted_credentials=encrypted,
                credentials_expires_at=expires_at,
                granted_scopes=granted_scopes,
                instance_origin=instance_origin,
            )
        else:
            raise SorOAuthError(
                "oauth_connection_unavailable",
                "This external connection can no longer be authorized.",
            )
        await file_sor_connection_event(
            session,
            organization_id=context.organization_id,
            connection_id=context.connection_id,
            connection_revision=activated_connection.revision,
            event_sequence=f"connected:{activated_connection.revision}",
            event_type="sor.connection.connected",
            occurred_at=activated_connection.updated_at,
            profile=connector.profile,
            vendor_key=context.vendor_key,
            connector_id=connector.id,
        )
        await OAuthStateRepository(session).invalidate_for_connection_revision(
            organization_id=context.organization_id,
            external_connection_id=context.connection_id,
            expected_connection_revision=context.expected_connection_revision,
        )
        if (
            context.change_mode is SorChangeMode.APP_WEBHOOK
            and context.vendor_key == "linear"
        ):
            if connector.webhook_signing_secret is None:
                raise SorOAuthError(
                    "app_webhook_not_configured",
                    "Configure the OAuth app webhook before authorizing it.",
                )
            connector.webhook_authorized_connection_revision = (
                activated_connection.revision
            )
            await session.flush()
        return activated_connection.revision


def _require_app_webhook_authorization_ready(
    *,
    connector: SorConnectorModel,
    manifest: SorAdapterCapabilityManifest,
) -> None:
    """Refuse Linear consent until its app-owned webhook can be installed."""
    if (
        manifest.change_mode is not SorChangeMode.APP_WEBHOOK
        or connector.vendor_key != "linear"
    ):
        return
    if (
        connector.webhook_signing_secret is None
        or connector.webhook_endpoint_key is None
    ):
        raise SorOAuthError(
            "app_webhook_not_configured",
            "Configure the OAuth app webhook URL and signing secret before authorization.",
        )
    try:
        public_webhook_api_base_url()
    except SorConfigurationError as error:
        raise SorOAuthError(
            "app_webhook_endpoint_unavailable",
            "Configure a public HTTPS API_BASE_URL before authorization.",
        ) from error


async def _restore_reauthorized_sources(
    *,
    organization_id: UUID,
    connection_id: UUID,
    connection_revision: int,
    registry: SorRegistry,
) -> tuple[UUID, ...]:
    """Resume every source waiting on the renewed connection, independently."""
    async with start_transaction(ro=True) as session:
        source_ids = tuple(
            source.id
            for source in await SorRepository(session).list_sources_for_connection(
                organization_id=organization_id,
                connection_id=connection_id,
            )
            if source.state is SorSourceState.REAUTH_REQUIRED
        )

    restored: list[UUID] = []
    for source_id in source_ids:
        try:
            async with start_transaction() as session:
                await SorSourceService(
                    session,
                    registry=registry,
                ).complete_reauthorization(
                    organization_id=organization_id,
                    source_id=source_id,
                    expected_connection_revision=connection_revision,
                )
            restored.append(source_id)
        except Exception as error:  # noqa: BLE001 - one source cannot block others
            logger.error(
                "SOR connection renewed but source resume failed "
                "organization_id=%s connection_id=%s source_id=%s error_type=%s",
                organization_id,
                connection_id,
                source_id,
                type(error).__name__,
            )
    return tuple(restored)


async def _schedule_reauthorization_catch_up(
    *,
    organization_id: UUID,
    source_id: UUID,
) -> None:
    """Best-effort file one full-source catch-up after authority is restored."""
    from eylo.sor.runtime.sync import spawn_sor_sync_run
    from eylo.sor.shared.sync_services import SorSyncRunService

    try:
        async with start_transaction() as session:
            streams = await SorRepository(session).list_streams(
                organization_id=organization_id,
                source_id=source_id,
            )
            if not streams:
                return
            kind = (
                SorSyncRunKind.RECONCILIATION
                if any(
                    stream.strategy is SorChangeStrategy.FULL_RECONCILE
                    for stream in streams
                )
                else SorSyncRunKind.INCREMENTAL
            )
            plan = await SorSyncRunService(session).create_generation(
                organization_id=organization_id,
                source_id=source_id,
                stream_ids=tuple(stream.id for stream in streams),
                kind=kind,
            )
            ready_run_ids = plan.ready_run_ids
    except Exception as error:  # noqa: BLE001 - scheduler recovery can retry later
        logger.error(
            "SOR source resumed but catch-up filing failed "
            "organization_id=%s source_id=%s error_type=%s",
            organization_id,
            source_id,
            type(error).__name__,
        )
        return

    for run_id in ready_run_ids:
        try:
            await spawn_sor_sync_run(
                organization_id=organization_id,
                run_id=run_id,
            )
        except Exception as error:  # noqa: BLE001 - recovery scans committed rows
            logger.error(
                "SOR reauthorization catch-up committed; spawn remains pending "
                "run_id=%s error_type=%s",
                run_id,
                type(error).__name__,
            )


async def _revoke_initiated_connection(context: _AuthorizationContext) -> None:
    async with start_transaction() as session:
        repository = SorRepository(session)
        connector = await repository.get_connector(
            organization_id=context.organization_id,
            connector_id=context.connector_id,
        )
        connection = await repository.get_connection(
            organization_id=context.organization_id,
            connection_id=context.connection_id,
            vendor_key=context.vendor_key,
            for_update=True,
        )
        if (
            connector is not None
            and connection is not None
            and connection.revision == context.expected_connection_revision
            and connection.status is ExternalConnectionStatus.INITIATED
        ):
            revoked = await ExternalConnectionService(session).revoke(
                organization_id=context.organization_id,
                connection_id=context.connection_id,
            )
            if revoked:
                await file_sor_connection_event(
                    session,
                    organization_id=context.organization_id,
                    connection_id=connection.id,
                    connection_revision=connection.revision,
                    event_sequence=f"revoked:{connection.revision}",
                    event_type="sor.connection.revoked",
                    occurred_at=connection.updated_at,
                    profile=connector.profile,
                    vendor_key=context.vendor_key,
                    connector_id=connector.id,
                )


def _require_oauth(manifest: SorAdapterCapabilityManifest) -> SorOAuthSpec:
    if manifest.oauth is None:
        raise SorOAuthError(
            "oauth_unsupported",
            "This SOR vendor does not support OAuth authorization.",
        )
    return manifest.oauth


def _authorization_instance_origin(
    *,
    oauth: SorOAuthSpec,
    value: str | None,
) -> str | None:
    """Validate an operator-owned site origin only for adapters that request it."""
    if not oauth.operator_instance_origin:
        if value is not None:
            raise SorOAuthError(
                "oauth_instance_origin_unexpected",
                "This provider does not accept an operator-supplied site origin.",
            )
        return None
    if value is None:
        raise SorOAuthError(
            "oauth_instance_origin_missing",
            "Enter the exact HTTPS site URL before authorization.",
        )
    return normalize_sor_instance_origin(
        value,
        allowed_suffixes=oauth.instance_host_suffixes,
        allowed_origins=tuple(
            option.api_origin for option in oauth.instance_origin_options
        ),
    )


def _selected_objects(
    manifest: SorAdapterCapabilityManifest,
    selected_objects: tuple[str, ...],
) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(value.strip() for value in selected_objects))
    if not selected or any(not value for value in selected):
        raise SorOAuthError(
            "oauth_selection_invalid",
            "Select at least one vendor object before authorization.",
        )
    available = {stream.key for stream in manifest.streams}
    unknown = set(selected) - available
    if unknown:
        raise SorOAuthError(
            "oauth_selection_invalid",
            "Authorization selected an unsupported vendor object.",
        )
    return selected


def _requested_scopes(
    *,
    manifest: SorAdapterCapabilityManifest,
    selected_objects: tuple[str, ...],
    access: SorSourceAccess,
) -> tuple[str, ...]:
    requested = list(manifest.oauth.base_scopes if manifest.oauth else ())
    for stream_key in selected_objects:
        requested.extend(manifest.required_scopes.get(stream_key, ()))
    if access is SorSourceAccess.READ_WRITE:
        selected = set(selected_objects)
        for tool_name in sorted(manifest.writable_tools):
            if selected.intersection(manifest.tool_streams[tool_name]):
                requested.extend(manifest.tool_required_scopes.get(tool_name, ()))
    return tuple(dict.fromkeys(requested))


def _granted_scopes(
    *,
    tokens: dict[str, object],
    context: _AuthorizationContext,
) -> list[str]:
    listed = tokens.get("scopes")
    if isinstance(listed, list) and all(isinstance(item, str) for item in listed):
        return list(dict.fromkeys(item.strip() for item in listed if item.strip()))
    raw = tokens.get("scope")
    if isinstance(raw, str) and raw.strip():
        delimiter = (
            context.oauth.scope_response_delimiter or context.oauth.scope_delimiter
        )
        return list(
            dict.fromkeys(item.strip() for item in raw.split(delimiter) if item.strip())
        )
    return list(context.requested_scopes)


def normalize_sor_instance_origin(
    value: str,
    *,
    allowed_suffixes: tuple[str, ...],
    allowed_origins: tuple[str, ...] = (),
) -> str:
    parsed = urlsplit(value.strip())
    host = parsed.hostname.lower() if parsed.hostname else ""
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SorOAuthError(
            "oauth_instance_origin_invalid",
            "The configured or provider-returned account origin is untrusted.",
        )
    origin = f"https://{host}"
    trusted = (
        origin in allowed_origins
        if allowed_origins
        else any(
            host == suffix or host.endswith(f".{suffix}")
            for suffix in allowed_suffixes
        )
    )
    if not trusted:
        raise SorOAuthError(
            "oauth_instance_origin_invalid",
            "The configured or provider-returned account origin is untrusted.",
        )
    return origin


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


__all__ = [
    "SOR_OAUTH_CALLBACK_PATH",
    "SorAuthorizationRedirect",
    "SorAuthorizationResult",
    "SorOAuthError",
    "begin_sor_authorization",
    "begin_sor_source_reauthorization",
    "complete_sor_authorization_from_state",
    "decline_sor_authorization",
    "default_sor_callback_url",
    "normalize_sor_instance_origin",
]
