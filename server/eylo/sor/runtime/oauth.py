"""OAuth authorization for organization-owned SOR connectors."""

from __future__ import annotations

import base64
import hashlib
import json
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
    SorOAuthSpec,
    SorSourceAccess,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_connector_client_secret,
)

SOR_OAUTH_CALLBACK_PATH = "/sor/oauth/callback"
STATE_TTL_MINUTES = 10


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
            instance_origin=requested_instance_origin or manifest.fixed_origin,
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
        await _activate_connection(
            context=context,
            credentials=credentials,
            expires_at=expires_at,
            granted_scopes=granted_scopes,
            instance_origin=instance_origin,
        )
    except Exception:
        await _revoke_initiated_connection(context)
        raise
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
) -> None:
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
    "complete_sor_authorization_from_state",
    "decline_sor_authorization",
    "default_sor_callback_url",
    "normalize_sor_instance_origin",
]
