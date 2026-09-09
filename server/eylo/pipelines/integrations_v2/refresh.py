"""Renew Integration V2 OAuth credentials without holding DB locks over HTTP."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from pydantic import JsonValue

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
from .registry import CuratedRegistry, load_vendors

logger = logging.getLogger(__name__)

REFRESH_WINDOW_MINUTES = 10
MAX_REFRESH_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """Connection IDs renewed, failed, or superseded during one cycle."""

    refreshed: tuple[UUID, ...]
    failed: tuple[UUID, ...]
    skipped: tuple[UUID, ...] = ()

    @property
    def considered(self) -> int:
        return len(self.refreshed) + len(self.failed) + len(self.skipped)


@dataclass(frozen=True, slots=True)
class _RenewedCredential:
    connection: ExternalConnectionInDb
    credentials: dict[str, JsonValue]
    expires_at: datetime | None


class _RefreshSkipped(Exception):
    """Another authority changed the connection before this cycle could act."""


class _RefreshError(Exception):
    """A coded renewal failure with safe Integration identity metadata."""

    def __init__(
        self,
        code: str,
        *,
        exhausted: bool = False,
        vendor: str | None = None,
        installation_id: UUID | None = None,
    ) -> None:
        self.code = code
        self.exhausted = exhausted
        self.vendor = vendor
        self.installation_id = installation_id
        super().__init__(code)


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
        except _RefreshError as error:
            logger.warning(
                "[CuratedRefresh] connection=%s not renewed code=%s",
                connection_id,
                error.code,
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
) -> _RenewedCredential:
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
        raise _RefreshError("installation_removed", exhausted=True)

    vendor_name = installation.vendor
    vendor = registry.vendor(vendor_name)
    error_metadata = {
        "vendor": vendor_name,
        "installation_id": installation.id,
    }
    if vendor is None or vendor.oauth is None:
        raise _RefreshError(
            "vendor_no_longer_carried",
            exhausted=True,
            **error_metadata,
        )
    if not installation.oauth_client_id or not installation.oauth_client_secret:
        raise _RefreshError("oauth_app_missing", exhausted=True, **error_metadata)
    if connection.credentials is None:
        raise _RefreshError(
            "credentials_unavailable",
            exhausted=True,
            **error_metadata,
        )
    try:
        credentials = decrypt_connection_credentials(
            connection.credentials,
            organization_id=connection.organization_id,
            connection_id=connection.id,
            revision=connection.revision,
        )
    except SecretCipherError as error:
        raise _RefreshError(
            "credentials_unreadable",
            exhausted=True,
            **error_metadata,
        ) from error
    refresh_token = credentials.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise _RefreshError(
            "refresh_token_unavailable",
            exhausted=True,
            **error_metadata,
        )

    token_url = vendor.oauth.token_url.replace(
        "{tenant}", installation.oauth_tenant or ""
    )
    try:
        client_secret = decrypt_client_secret(installation.oauth_client_secret)
    except SecretCipherError as error:
        raise _RefreshError(
            "oauth_app_unreadable",
            exhausted=True,
            **error_metadata,
        ) from error

    try:
        payload = await _post_refresh(
            token_url=token_url,
            client_id=installation.oauth_client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            transport=transport,
        )
    except _RefreshError as error:
        raise _RefreshError(
            error.code,
            exhausted=error.exhausted,
            **error_metadata,
        ) from error

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _RefreshError("no_access_token_returned", **error_metadata)

    renewed_credentials = dict(credentials)
    renewed_credentials["access_token"] = access_token
    for optional in ("refresh_token", "token_type", "scope"):
        value = payload.get(optional)
        if isinstance(value, str) and value:
            renewed_credentials[optional] = value

    expires_at = None
    if isinstance(payload.get("expires_in"), int):
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(payload["expires_in"])
        )
    return _RenewedCredential(
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
) -> dict[str, object]:
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
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
            response_body_limit=262_144,
            total_timeout_seconds=20.0,
        )
        response = await (transport or SafeHttpTransport()).send(request)
    except (HttpEgressPolicyError, TimeoutError) as error:
        raise _RefreshError("token_endpoint_unreachable") from error

    if response.status_code == 400:
        raise _RefreshError("refresh_token_rejected", exhausted=True)
    if response.status_code != 200:
        raise _RefreshError(f"token_endpoint_http_{response.status_code}")
    try:
        payload = json.loads(response.body)
    except ValueError as error:
        raise _RefreshError("token_response_unreadable") from error
    if not isinstance(payload, dict):
        raise _RefreshError("token_response_unreadable")
    return payload


async def _record_failure(
    connection: ExternalConnectionInDb,
    error: _RefreshError,
) -> bool:
    attempts = connection.refresh_attempts + 1
    finished = error.exhausted or attempts >= MAX_REFRESH_ATTEMPTS
    try:
        async with start_transaction() as session:
            service = ExternalConnectionService(session)
            if finished:
                await service.require_reauthorization(
                    organization_id=connection.organization_id,
                    connection_id=connection.id,
                    expected_revision=connection.revision,
                    error_code=error.code,
                )
            else:
                await service.mark_degraded(
                    organization_id=connection.organization_id,
                    connection_id=connection.id,
                    expected_revision=connection.revision,
                    error_code=error.code,
                )
            if finished and error.installation_id is not None:
                register_ephemeral_event_post_txn(
                    ConnectionExpiredEvent(
                        connection_id=connection.id,
                        organization_id=connection.organization_id,
                        integration_id=error.installation_id,
                        vendor=error.vendor,
                        contact_id=connection.contact_id,
                        reason=(
                            "Curated credential could not be renewed: "
                            f"{error.code}."
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
