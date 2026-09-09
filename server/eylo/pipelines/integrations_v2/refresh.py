"""Renew Integration V2 OAuth credentials without holding DB locks over HTTP."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from urllib.parse import urlencode
from uuid import UUID

from eylo.common.database import (
    register_ephemeral_event_post_txn,
    start_transaction,
)
from eylo.common.http_egress import (
    HttpDestinationPolicy,
    HttpEgressPolicyError,
    HttpEgressRequest,
    HttpRoutePolicy,
    parse_https_target,
)
from eylo.events.schema.py_events.connections import ConnectionExpiredEvent
from eylo.modules.connections.domain import (
    ExternalConnectionNotFoundError,
    ExternalConnectionRevisionConflictError,
    ExternalConnectionStateError,
    ExternalConnectionStatus,
)
from eylo.modules.connections.schemas.external import ExternalConnectionInDb
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.modules.integrations_v2.services.installations import (
    CuratedIntegrationService,
)
from eylo.modules.provider_configs.crypto import SecretCipherError
from eylo.pipelines.external_connections.credentials import (
    decrypt_connection_credentials,
    encrypt_connection_credentials,
)
from eylo.sockets.http.transport import SafeHttpTransport

from .http_client import VendorTransport
from .oauth import decrypt_client_secret
from .oauth_tokens import OAuthTokenError, OAuthTokenErrorCode, OAuthTokenResponse
from .refresh_contracts import (
    RefreshDisposition,
    RefreshError,
    RefreshErrorCode,
    RefreshOutcome,
    RefreshTokenRequest,
    RenewedCredential,
)
from .registry import CuratedRegistry, load_vendors

logger = logging.getLogger(__name__)

REFRESH_WINDOW_MINUTES = 10
MAX_REFRESH_ATTEMPTS = 5
_TOKEN_RESPONSE_BODY_LIMIT = 262_144
_TOKEN_REQUEST_TIMEOUT_SECONDS = 20.0


class _RefreshSkipped(Exception):
    """Another authority changed the connection before this cycle could act."""


async def refresh_expiring_curated_connections(
    *,
    registry: CuratedRegistry | None = None,
    transport: VendorTransport | None = None,
    window_minutes: int = REFRESH_WINDOW_MINUTES,
) -> RefreshOutcome:
    """Renew due Integration credentials using read, HTTP, then guarded write."""
    registry = registry or load_vendors()
    threshold = datetime.now(timezone.utc) + timedelta(minutes=window_minutes)
    async with start_transaction(ro=True) as session:
        candidates = await CuratedIntegrationService(
            session
        ).list_expiring_external_connections(expires_before=threshold)

    refreshed: list[UUID] = []
    failed: list[UUID] = []
    skipped: list[UUID] = []

    for candidate in candidates:
        connection_id = candidate.id
        try:
            renewed = await _refresh_one(
                candidate=candidate,
                registry=registry,
                transport=transport,
            )
            encrypted = encrypt_connection_credentials(
                renewed.credentials,
                organization_id=renewed.connection.organization_id,
                connection_id=renewed.connection.id,
                revision=renewed.connection.revision + 1,
            )
            async with start_transaction() as session:
                await ExternalConnectionService(session).renew_credentials(
                    organization_id=renewed.connection.organization_id,
                    connection_id=renewed.connection.id,
                    expected_revision=renewed.connection.revision,
                    encrypted_credentials=encrypted,
                    credentials_expires_at=renewed.expires_at,
                    granted_scopes=renewed.connection.granted_scopes,
                )
        except _RefreshSkipped:
            skipped.append(connection_id)
            continue
        except (
            ExternalConnectionNotFoundError,
            ExternalConnectionRevisionConflictError,
            ExternalConnectionStateError,
        ):
            skipped.append(connection_id)
            continue
        except RefreshError as error:
            logger.warning(
                "[CuratedRefresh] connection=%s not renewed code=%s",
                connection_id,
                error.failure.persisted_code,
            )
            recorded = await _record_failure(candidate, error)
            (failed if recorded else skipped).append(connection_id)
            continue

        refreshed.append(connection_id)

    return RefreshOutcome(
        refreshed=tuple(refreshed),
        failed=tuple(failed),
        skipped=tuple(skipped),
    )


async def _refresh_one(
    *,
    candidate: ExternalConnectionInDb,
    registry: CuratedRegistry,
    transport: VendorTransport | None,
) -> RenewedCredential:
    async with start_transaction(ro=True) as session:
        connection = await ExternalConnectionService(session).get(
            organization_id=candidate.organization_id,
            connection_id=candidate.id,
        )
        installation = await CuratedIntegrationService(
            session
        ).resolve_installation_for_connection(
            organization_id=candidate.organization_id,
            connection_id=candidate.id,
        )

    if (
        connection is None
        or connection.revision != candidate.revision
        or connection.status
        not in {ExternalConnectionStatus.ACTIVE, ExternalConnectionStatus.DEGRADED}
    ):
        raise _RefreshSkipped
    if installation is None:
        raise RefreshError(
            RefreshErrorCode.INSTALLATION_REMOVED,
            disposition=RefreshDisposition.REAUTHORIZE,
        )

    vendor_name = installation.vendor
    vendor = registry.vendor(vendor_name)
    if vendor is None or vendor.oauth is None:
        raise RefreshError(
            RefreshErrorCode.VENDOR_NO_LONGER_CARRIED,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        )
    if not installation.oauth_client_id or not installation.oauth_client_secret:
        raise RefreshError(
            RefreshErrorCode.OAUTH_APP_MISSING,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        )
    if connection.credentials is None:
        raise RefreshError(
            RefreshErrorCode.CREDENTIALS_UNAVAILABLE,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        )
    try:
        credentials = decrypt_connection_credentials(
            connection.credentials,
            organization_id=connection.organization_id,
            connection_id=connection.id,
            revision=connection.revision,
        )
    except SecretCipherError as error:
        raise RefreshError(
            RefreshErrorCode.CREDENTIALS_UNREADABLE,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        ) from error
    refresh_token = credentials.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RefreshError(
            RefreshErrorCode.REFRESH_TOKEN_UNAVAILABLE,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        )

    token_url = vendor.oauth.token_url.replace(
        "{tenant}", installation.oauth_tenant or ""
    )
    try:
        client_secret = decrypt_client_secret(installation.oauth_client_secret)
    except SecretCipherError as error:
        raise RefreshError(
            RefreshErrorCode.OAUTH_APP_UNREADABLE,
            disposition=RefreshDisposition.REAUTHORIZE,
            vendor=vendor_name,
            installation_id=installation.id,
        ) from error

    try:
        payload = await _post_refresh(
            token_url=token_url,
            client_id=installation.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            transport=transport,
        )
        expires_at = payload.expires_at(datetime.now(timezone.utc))
    except OAuthTokenError:
        raise RefreshError(
            RefreshErrorCode.TOKEN_RESPONSE_UNREADABLE,
            vendor=vendor_name,
            installation_id=installation.id,
        ) from None
    except RefreshError as error:
        raise RefreshError(
            error.failure.code,
            disposition=error.failure.disposition,
            vendor=vendor_name,
            installation_id=installation.id,
            http_status=error.failure.http_status,
        ) from error

    renewed_credentials = dict(credentials)
    renewed_credentials["access_token"] = payload.access_token
    if payload.refresh_token:
        renewed_credentials["refresh_token"] = payload.refresh_token
    if payload.token_type:
        renewed_credentials["token_type"] = payload.token_type
    if payload.scope:
        renewed_credentials["scope"] = payload.scope
    return RenewedCredential(
        connection=connection,
        credentials=renewed_credentials,
        expires_at=expires_at,
    )


async def _post_refresh(
    *,
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    transport: VendorTransport | None,
) -> OAuthTokenResponse:
    form = RefreshTokenRequest(
        client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
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
        raise RefreshError(RefreshErrorCode.TOKEN_ENDPOINT_UNREACHABLE) from error

    if response.status_code == HTTPStatus.BAD_REQUEST:
        raise RefreshError(
            RefreshErrorCode.REFRESH_TOKEN_REJECTED,
            disposition=RefreshDisposition.REAUTHORIZE,
        )
    if response.status_code != HTTPStatus.OK:
        raise RefreshError(
            RefreshErrorCode.TOKEN_ENDPOINT_HTTP, http_status=response.status_code
        )
    try:
        return OAuthTokenResponse.from_body(response.body)
    except OAuthTokenError as error:
        code = (
            RefreshErrorCode.NO_ACCESS_TOKEN_RETURNED
            if error.code is OAuthTokenErrorCode.MISSING_ACCESS_TOKEN
            else RefreshErrorCode.TOKEN_RESPONSE_UNREADABLE
        )
        raise RefreshError(code) from None


async def _record_failure(
    connection: ExternalConnectionInDb,
    error: RefreshError,
) -> bool:
    attempts = connection.refresh_attempts + 1
    failure = error.failure
    finished = (
        failure.disposition is RefreshDisposition.REAUTHORIZE
        or attempts >= MAX_REFRESH_ATTEMPTS
    )
    try:
        async with start_transaction() as session:
            service = ExternalConnectionService(session)
            if finished:
                await service.require_reauthorization(
                    organization_id=connection.organization_id,
                    connection_id=connection.id,
                    expected_revision=connection.revision,
                    error_code=failure.persisted_code,
                )
            else:
                await service.mark_degraded(
                    organization_id=connection.organization_id,
                    connection_id=connection.id,
                    expected_revision=connection.revision,
                    error_code=failure.persisted_code,
                )
            if finished and failure.installation_id is not None:
                register_ephemeral_event_post_txn(
                    ConnectionExpiredEvent(
                        connection_id=connection.id,
                        organization_id=connection.organization_id,
                        integration_id=failure.installation_id,
                        vendor=failure.vendor,
                        contact_id=connection.contact_id,
                        reason=(
                            "Curated credential could not be renewed: "
                            f"{failure.persisted_code}."
                        ),
                    )
                )
    except (
        ExternalConnectionNotFoundError,
        ExternalConnectionRevisionConflictError,
        ExternalConnectionStateError,
    ):
        return False
    return True


__all__ = [
    "MAX_REFRESH_ATTEMPTS",
    "REFRESH_WINDOW_MINUTES",
    "RefreshOutcome",
    "refresh_expiring_curated_connections",
]
