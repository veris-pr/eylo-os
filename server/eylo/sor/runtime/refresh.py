"""Renew SOR OAuth credentials without holding DB locks over vendor I/O."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol
from uuid import UUID

from eylo.common.database import async_session_factory
from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpEgressResponse,
    HttpRoutePolicy,
    parse_https_target,
)
from eylo.modules.connections.domain import (
    ExternalConnectionRevisionConflictError,
    ExternalConnectionStateError,
    ExternalConnectionStatus,
)
from eylo.modules.connections.models import ExternalConnectionModel
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.modules.provider_configs.crypto import SecretCipherError
from eylo.pipelines.external_connections.credentials import (
    decrypt_connection_credentials,
    encrypt_connection_credentials,
)
from eylo.sockets.http.transport import SafeHttpTransport
from eylo.sor.runtime.action_events import file_sor_connection_event
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.oauth import normalize_sor_instance_origin
from eylo.sor.runtime.oauth_endpoints import (
    SorOAuthEndpointError,
    resolve_oauth_token_url,
)
from eylo.sor.runtime.oauth_payload import (
    apply_oauth_client_auth,
    encode_oauth_token_request,
)
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorOAuthSpec,
    SorSourceState,
    SorSourceTransition,
)
from eylo.sor.shared.models import SorSourceModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_connector_client_secret,
)
from eylo.sor.shared.services import SorSourceService

logger = logging.getLogger(__name__)

REFRESH_WINDOW_SECONDS = 600.0
REFRESH_RETRY_COOLDOWN_SECONDS = 30.0
MAX_REFRESH_ATTEMPTS = 5


class SorRefreshDisposition(str, Enum):
    """Result of checking one source connection before adapter creation."""

    NOT_DUE = "NOT_DUE"
    REFRESHED = "REFRESHED"
    SUPERSEDED = "SUPERSEDED"


class SorConnectionRefreshError(Exception):
    """A safe credential-renewal failure for adapter acquisition."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        requires_reauthorization: bool,
        connection_id: UUID | None = None,
        expected_connection_revision: int | None = None,
        source_config_revision: int | None = None,
        vendor_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.requires_reauthorization = requires_reauthorization
        self.connection_id = connection_id
        self.expected_connection_revision = expected_connection_revision
        self.source_config_revision = source_config_revision
        self.vendor_key = vendor_key


class SorTokenTransport(Protocol):
    """Minimal token-endpoint port used by recorded transport proofs."""

    async def send(self, request: HttpEgressRequest) -> HttpEgressResponse: ...


@dataclass(frozen=True, slots=True)
class _RefreshSnapshot:
    organization_id: UUID
    source_id: UUID
    source_config_revision: int
    vendor_key: str
    connector_id: UUID
    connector_config_revision: int
    connection_id: UUID
    connection_revision: int
    connection_status: ExternalConnectionStatus
    credentials: dict[str, object]
    credentials_expires_at: datetime | None
    granted_scopes: tuple[str, ...]
    refresh_attempts: int
    last_refresh_failure_at: datetime | None
    client_id: str
    client_secret: str
    oauth: SorOAuthSpec
    fixed_origin: str | None
    instance_origin: str | None


@dataclass(frozen=True, slots=True)
class _Renewal:
    credentials: dict[str, object]
    expires_at: datetime | None
    granted_scopes: tuple[str, ...]
    instance_origin: str | None


class _RefreshFailure(Exception):
    def __init__(self, code: str, *, exhausted: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.exhausted = exhausted


async def refresh_source_connection_if_needed(
    *,
    organization_id: UUID,
    source_id: UUID,
    minimum_validity_seconds: float,
    force: bool = False,
    registry: SorRegistry | None = None,
    transport: SorTokenTransport | None = None,
    session_factory=async_session_factory,
) -> SorRefreshDisposition:
    """Refresh one due source credential through read, HTTP, guarded write."""
    if minimum_validity_seconds <= 0:
        raise ValueError("minimum_validity_seconds must be positive.")
    active_registry = registry or get_sor_registry()
    try:
        snapshot = await _load_snapshot(
            organization_id=organization_id,
            source_id=source_id,
            minimum_validity_seconds=minimum_validity_seconds,
            force=force,
            registry=active_registry,
            session_factory=session_factory,
        )
    except SorConnectionRefreshError as error:
        if error.requires_reauthorization:
            await _record_unrefreshable_connection(
                organization_id=organization_id,
                source_id=source_id,
                error_code=error.code,
                connection_id=error.connection_id,
                expected_connection_revision=error.expected_connection_revision,
                source_config_revision=error.source_config_revision,
                vendor_key=error.vendor_key,
                session_factory=session_factory,
            )
        raise
    if snapshot is None:
        return SorRefreshDisposition.NOT_DUE
    if _inside_retry_cooldown(snapshot, force=force):
        raise SorConnectionRefreshError(
            "CONNECTION_REFRESH_RETRY_PENDING",
            "The source connection is waiting before its next refresh attempt.",
            requires_reauthorization=False,
        )

    try:
        renewal = await _renew(snapshot=snapshot, transport=transport)
    except _RefreshFailure as error:
        requires_reauthorization = await _record_failure(
            snapshot=snapshot,
            failure=error,
            session_factory=session_factory,
        )
        raise SorConnectionRefreshError(
            error.code,
            (
                "The source connection requires authorization."
                if requires_reauthorization
                else "The source connection could not be refreshed yet."
            ),
            requires_reauthorization=requires_reauthorization,
        ) from error

    persisted = await _persist_renewal(
        snapshot=snapshot,
        renewal=renewal,
        session_factory=session_factory,
    )
    return (
        SorRefreshDisposition.REFRESHED
        if persisted
        else SorRefreshDisposition.SUPERSEDED
    )


async def _load_snapshot(
    *,
    organization_id: UUID,
    source_id: UUID,
    minimum_validity_seconds: float,
    force: bool,
    registry: SorRegistry,
    session_factory,
) -> _RefreshSnapshot | None:
    async with session_factory() as session:
        repository = SorRepository(session)
        source = await repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            return None
        connection = await repository.get_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            vendor_key=source.vendor_key,
        )
        if connection is None or connection.status not in {
            ExternalConnectionStatus.ACTIVE,
            ExternalConnectionStatus.DEGRADED,
        }:
            return None
        if not _refresh_due(
            status=connection.status,
            expires_at=connection.credentials_expires_at,
            minimum_validity_seconds=minimum_validity_seconds,
            force=force,
        ):
            return None
        connector = await repository.get_connector_for_connection(
            organization_id=organization_id,
            connection_id=connection.id,
        )
        if connector is None or connector.vendor_key != source.vendor_key:
            raise _preflight_error(
                "CONNECTION_CONNECTOR_MISSING",
                "The source connection requires authorization.",
                source=source,
                connection=connection,
            )
        try:
            manifest = registry.get_manifest(
                profile=source.profile,
                vendor_key=source.vendor_key,
            )
        except KeyError as error:
            raise SorConnectionRefreshError(
                "CONNECTION_ADAPTER_UNAVAILABLE",
                "The source connection adapter is unavailable.",
                requires_reauthorization=False,
            ) from error
        if manifest.oauth is None:
            raise _preflight_error(
                "CONNECTION_REFRESH_UNSUPPORTED",
                "The source connection cannot be refreshed.",
                source=source,
                connection=connection,
            )
        try:
            client_secret = decrypt_connector_client_secret(
                connector.oauth_client_secret,
                organization_id=organization_id,
                connector_id=connector.id,
                config_revision=connector.config_revision,
            )
            if connection.credentials is None:
                raise _RefreshFailure("credentials_unavailable", exhausted=True)
            credentials = decrypt_connection_credentials(
                connection.credentials,
                organization_id=organization_id,
                connection_id=connection.id,
                revision=connection.revision,
            )
        except (SorSecretEnvelopeError, SecretCipherError) as error:
            raise _preflight_error(
                "CONNECTION_CREDENTIALS_UNREADABLE",
                "The source connection requires authorization.",
                source=source,
                connection=connection,
            ) from error
        except _RefreshFailure as error:
            raise _preflight_error(
                error.code,
                "The source connection requires authorization.",
                source=source,
                connection=connection,
            ) from error

        return _RefreshSnapshot(
            organization_id=organization_id,
            source_id=source.id,
            source_config_revision=source.config_revision,
            vendor_key=source.vendor_key,
            connector_id=connector.id,
            connector_config_revision=connector.config_revision,
            connection_id=connection.id,
            connection_revision=connection.revision,
            connection_status=connection.status,
            credentials=dict(credentials),
            credentials_expires_at=connection.credentials_expires_at,
            granted_scopes=tuple(connection.granted_scopes or ()),
            refresh_attempts=connection.refresh_attempts,
            last_refresh_failure_at=connection.last_refresh_failure_at,
            client_id=connector.oauth_client_id,
            client_secret=client_secret,
            oauth=manifest.oauth,
            fixed_origin=manifest.fixed_origin,
            instance_origin=connection.instance_origin,
        )


async def _renew(
    *,
    snapshot: _RefreshSnapshot,
    transport: SorTokenTransport | None,
) -> _Renewal:
    refresh_token = snapshot.credentials.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise _RefreshFailure("refresh_token_unavailable", exhausted=True)
    payload = await _post_refresh(
        oauth=snapshot.oauth,
        instance_origin=snapshot.instance_origin or snapshot.fixed_origin,
        client_id=snapshot.client_id,
        client_secret=snapshot.client_secret,
        refresh_token=refresh_token,
        transport=transport,
    )
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _RefreshFailure("token_response_missing_access_token")

    credentials = dict(snapshot.credentials)
    credentials["access_token"] = access_token
    for key in ("refresh_token", "token_type", "scope"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            credentials[key] = value

    granted_scopes = _renewed_scopes(payload, snapshot)
    if not set(snapshot.granted_scopes).issubset(granted_scopes):
        raise _RefreshFailure("refreshed_scope_missing", exhausted=True)

    instance_origin = (
        snapshot.instance_origin
        if snapshot.oauth.operator_instance_origin
        else snapshot.fixed_origin or snapshot.instance_origin
    )
    origin_field = snapshot.oauth.instance_origin_field
    if origin_field is not None and origin_field in payload:
        raw_origin = payload.get(origin_field)
        if not isinstance(raw_origin, str):
            raise _RefreshFailure("refreshed_instance_origin_invalid", exhausted=True)
        try:
            instance_origin = normalize_sor_instance_origin(
                raw_origin,
                allowed_suffixes=snapshot.oauth.instance_host_suffixes,
                allowed_origins=tuple(
                    option.api_origin
                    for option in snapshot.oauth.instance_origin_options
                ),
            )
        except Exception as error:
            raise _RefreshFailure(
                "refreshed_instance_origin_invalid",
                exhausted=True,
            ) from error

    return _Renewal(
        credentials=credentials,
        expires_at=_expires_at(payload),
        granted_scopes=tuple(granted_scopes),
        instance_origin=instance_origin,
    )


async def _post_refresh(
    *,
    oauth: SorOAuthSpec,
    instance_origin: str | None,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    transport: SorTokenTransport | None,
) -> dict[str, object]:
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    form, auth_headers = apply_oauth_client_auth(
        oauth,
        form,
        client_id=client_id,
        client_secret=client_secret,
    )
    content_type, body = encode_oauth_token_request(oauth, form)
    try:
        token_url = resolve_oauth_token_url(
            oauth,
            instance_origin=instance_origin,
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
        raise _RefreshFailure("token_endpoint_unreachable") from error
    if response.status_code != 200:
        payload = _optional_json_payload(response.body)
        provider_code = payload.get("error")
        exhausted = response.status_code in {400, 401, 403} or provider_code in {
            "invalid_client",
            "invalid_grant",
            "invalid_refresh_token",
        }
        if exhausted:
            raise _RefreshFailure("refresh_token_rejected", exhausted=True)
        if response.status_code == 429:
            raise _RefreshFailure("token_endpoint_rate_limited")
        raise _RefreshFailure("token_endpoint_unavailable")
    return _json_payload(response.body)


async def _persist_renewal(
    *,
    snapshot: _RefreshSnapshot,
    renewal: _Renewal,
    session_factory,
) -> bool:
    try:
        async with session_factory() as session, session.begin():
            repository = SorRepository(session)
            source = await repository.get_source(
                organization_id=snapshot.organization_id,
                source_id=snapshot.source_id,
                for_update=True,
            )
            connector = await repository.get_connector(
                organization_id=snapshot.organization_id,
                connector_id=snapshot.connector_id,
                for_update=True,
            )
            connection = await repository.get_connection(
                organization_id=snapshot.organization_id,
                connection_id=snapshot.connection_id,
                vendor_key=snapshot.vendor_key,
                for_update=True,
            )
            if (
                source is None
                or source.config_revision != snapshot.source_config_revision
                or source.external_connection_id != snapshot.connection_id
                or connector is None
                or connector.config_revision != snapshot.connector_config_revision
                or connector.external_connection_id != snapshot.connection_id
                or connection is None
                or connection.revision != snapshot.connection_revision
                or connection.status
                not in {
                    ExternalConnectionStatus.ACTIVE,
                    ExternalConnectionStatus.DEGRADED,
                }
            ):
                return False
            encrypted = encrypt_connection_credentials(
                renewal.credentials,
                organization_id=snapshot.organization_id,
                connection_id=snapshot.connection_id,
                revision=connection.revision + 1,
            )
            await ExternalConnectionService(session).renew_credentials(
                organization_id=snapshot.organization_id,
                connection_id=snapshot.connection_id,
                expected_revision=connection.revision,
                encrypted_credentials=encrypted,
                credentials_expires_at=renewal.expires_at,
                granted_scopes=list(renewal.granted_scopes),
                instance_origin=renewal.instance_origin,
            )
    except (
        ExternalConnectionRevisionConflictError,
        ExternalConnectionStateError,
    ):
        return False
    return True


async def _record_failure(
    *,
    snapshot: _RefreshSnapshot,
    failure: _RefreshFailure,
    session_factory,
) -> bool:
    requires_reauthorization = (
        failure.exhausted or snapshot.refresh_attempts + 1 >= MAX_REFRESH_ATTEMPTS
    )
    try:
        async with session_factory() as session, session.begin():
            repository = SorRepository(session)
            source = await repository.get_source(
                organization_id=snapshot.organization_id,
                source_id=snapshot.source_id,
                for_update=True,
            )
            connector = await repository.get_connector(
                organization_id=snapshot.organization_id,
                connector_id=snapshot.connector_id,
                for_update=True,
            )
            connection = await repository.get_connection(
                organization_id=snapshot.organization_id,
                connection_id=snapshot.connection_id,
                vendor_key=snapshot.vendor_key,
                for_update=True,
            )
            if (
                source is None
                or source.config_revision != snapshot.source_config_revision
                or source.external_connection_id != snapshot.connection_id
                or connector is None
                or connector.config_revision != snapshot.connector_config_revision
                or connector.external_connection_id != snapshot.connection_id
                or connection is None
                or connection.revision != snapshot.connection_revision
            ):
                return False
            service = ExternalConnectionService(session)
            if requires_reauthorization:
                reauthorization = await service.require_reauthorization(
                    organization_id=snapshot.organization_id,
                    connection_id=snapshot.connection_id,
                    expected_revision=connection.revision,
                    error_code=failure.code,
                )
                if source.state not in {
                    SorSourceState.DISABLED,
                    SorSourceState.REAUTH_REQUIRED,
                }:
                    await SorSourceService(session).transition(
                        organization_id=snapshot.organization_id,
                        source_id=snapshot.source_id,
                        transition=SorSourceTransition.REAUTHORIZATION_REQUIRED,
                        error_code=failure.code,
                        error_summary="The source connection requires authorization.",
                    )
                await file_sor_connection_event(
                    session,
                    organization_id=snapshot.organization_id,
                    connection_id=snapshot.connection_id,
                    connection_revision=reauthorization.revision,
                    event_sequence=(
                        f"reauth:{reauthorization.revision}:"
                        f"{reauthorization.refresh_attempts}"
                    ),
                    event_type="sor.connection.reauth_required",
                    occurred_at=reauthorization.updated_at,
                    profile=source.profile,
                    vendor_key=snapshot.vendor_key,
                    connector_id=connector.id,
                    source_id=source.id,
                    error_code=failure.code,
                )
            else:
                await service.mark_degraded(
                    organization_id=snapshot.organization_id,
                    connection_id=snapshot.connection_id,
                    expected_revision=connection.revision,
                    error_code=failure.code,
                )
    except (
        ExternalConnectionRevisionConflictError,
        ExternalConnectionStateError,
    ):
        return False
    return requires_reauthorization


async def _record_unrefreshable_connection(
    *,
    organization_id: UUID,
    source_id: UUID,
    error_code: str,
    connection_id: UUID | None,
    expected_connection_revision: int | None,
    source_config_revision: int | None,
    vendor_key: str | None,
    session_factory,
) -> None:
    """Persist a terminal preparation failure when its authority is still current."""
    if (
        connection_id is None
        or expected_connection_revision is None
        or source_config_revision is None
        or vendor_key is None
    ):
        return
    try:
        async with session_factory() as session, session.begin():
            repository = SorRepository(session)
            source = await repository.get_source(
                organization_id=organization_id,
                source_id=source_id,
                for_update=True,
            )
            if (
                source is None
                or source.config_revision != source_config_revision
                or source.external_connection_id != connection_id
                or source.vendor_key != vendor_key
            ):
                return
            connection = await repository.get_connection(
                organization_id=organization_id,
                connection_id=connection_id,
                vendor_key=vendor_key,
                for_update=True,
            )
            if (
                connection is None
                or connection.revision != expected_connection_revision
                or connection.status
                not in {
                    ExternalConnectionStatus.ACTIVE,
                    ExternalConnectionStatus.DEGRADED,
                }
            ):
                return
            reauthorization = await ExternalConnectionService(
                session
            ).require_reauthorization(
                organization_id=organization_id,
                connection_id=connection.id,
                expected_revision=connection.revision,
                error_code=error_code,
            )
            if source.state not in {
                SorSourceState.DISABLED,
                SorSourceState.REAUTH_REQUIRED,
            }:
                await SorSourceService(session).transition(
                    organization_id=organization_id,
                    source_id=source_id,
                    transition=SorSourceTransition.REAUTHORIZATION_REQUIRED,
                    error_code=error_code,
                    error_summary="The source connection requires authorization.",
                )
            await file_sor_connection_event(
                session,
                organization_id=organization_id,
                connection_id=connection.id,
                connection_revision=reauthorization.revision,
                event_sequence=(
                    f"reauth:{reauthorization.revision}:"
                    f"{reauthorization.refresh_attempts}"
                ),
                event_type="sor.connection.reauth_required",
                occurred_at=reauthorization.updated_at,
                profile=source.profile,
                vendor_key=vendor_key,
                source_id=source.id,
                error_code=error_code,
            )
    except (
        ExternalConnectionRevisionConflictError,
        ExternalConnectionStateError,
    ):
        logger.info(
            "SOR refresh preparation failure was superseded "
            "organization_id=%s source_id=%s",
            organization_id,
            source_id,
        )


def _refresh_due(
    *,
    status: ExternalConnectionStatus,
    expires_at: datetime | None,
    minimum_validity_seconds: float,
    force: bool,
) -> bool:
    if force or status is ExternalConnectionStatus.DEGRADED:
        return True
    if expires_at is None:
        return False
    expires_at = _aware(expires_at)
    window = max(minimum_validity_seconds, REFRESH_WINDOW_SECONDS)
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=window)


def _preflight_error(
    code: str,
    message: str,
    *,
    source: SorSourceModel,
    connection: ExternalConnectionModel,
) -> SorConnectionRefreshError:
    return SorConnectionRefreshError(
        code,
        message,
        requires_reauthorization=True,
        connection_id=connection.id,
        expected_connection_revision=connection.revision,
        source_config_revision=source.config_revision,
        vendor_key=source.vendor_key,
    )


def _inside_retry_cooldown(snapshot: _RefreshSnapshot, *, force: bool) -> bool:
    if force or snapshot.connection_status is not ExternalConnectionStatus.DEGRADED:
        return False
    failed_at = snapshot.last_refresh_failure_at
    if failed_at is None:
        return False
    return _aware(failed_at) + timedelta(
        seconds=REFRESH_RETRY_COOLDOWN_SECONDS
    ) > datetime.now(timezone.utc)


def _renewed_scopes(
    payload: dict[str, object],
    snapshot: _RefreshSnapshot,
) -> set[str]:
    listed = payload.get("scopes")
    if isinstance(listed, list) and all(isinstance(item, str) for item in listed):
        return {item.strip() for item in listed if item.strip()}
    raw = payload.get("scope")
    if isinstance(raw, str) and raw.strip():
        delimiter = (
            snapshot.oauth.scope_response_delimiter or snapshot.oauth.scope_delimiter
        )
        return {item.strip() for item in raw.split(delimiter) if item.strip()}
    return set(snapshot.granted_scopes)


def _expires_at(payload: dict[str, object]) -> datetime | None:
    expires_in = payload.get("expires_in")
    if expires_in is None:
        return None
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
    ):
        raise _RefreshFailure("token_lifetime_invalid")
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _json_payload(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as error:
        raise _RefreshFailure("token_response_unreadable") from error
    if not isinstance(payload, dict):
        raise _RefreshFailure("token_response_unreadable")
    return payload


def _optional_json_payload(body: bytes) -> dict[str, object]:
    try:
        return _json_payload(body)
    except _RefreshFailure:
        return {}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "MAX_REFRESH_ATTEMPTS",
    "REFRESH_RETRY_COOLDOWN_SECONDS",
    "REFRESH_WINDOW_SECONDS",
    "SorConnectionRefreshError",
    "SorRefreshDisposition",
    "refresh_source_connection_if_needed",
]
