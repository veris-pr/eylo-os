"""Resolve one exact SOR source into a short-lived vendor adapter."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import async_session_factory
from eylo.modules.connections.domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.pipelines.external_connections.credentials import (
    decrypt_connection_credentials,
)
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.refresh import (
    SorConnectionRefreshError,
    SorRefreshDisposition,
    refresh_source_connection_if_needed,
)
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorAdapterFieldSelection,
    SorChangeMode,
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorLifecycleAdapter,
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValueError, require_json_object
from eylo.sor.shared.models import SorSourceModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_connector_client_secret,
    decrypt_connector_webhook_signing_secret,
    decrypt_source_webhook_signing_secret,
)

logger = logging.getLogger(__name__)


class SorAdapterUnavailableError(Exception):
    """A source cannot safely authorize a vendor operation right now."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        requires_reauthorization: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.requires_reauthorization = requires_reauthorization


@asynccontextmanager
async def acquire_source_adapter(
    *,
    organization_id: UUID,
    source_id: UUID,
    invocation_budget_seconds: float = 30.0,
    selected_objects: Sequence[str] | None = None,
    registry: SorRegistry | None = None,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
) -> AsyncIterator[SorLifecycleAdapter]:
    """Recheck current source authority, decrypt at the edge, and always close."""
    if invocation_budget_seconds <= 0:
        raise ValueError("invocation_budget_seconds must be positive.")

    active_registry = registry or get_sor_registry()
    try:
        await refresh_source_connection_if_needed(
            organization_id=organization_id,
            source_id=source_id,
            minimum_validity_seconds=invocation_budget_seconds,
            registry=active_registry,
            session_factory=session_factory,
        )
    except SorConnectionRefreshError as error:
        raise SorAdapterUnavailableError(
            error.code,
            str(error),
            requires_reauthorization=error.requires_reauthorization,
        ) from error

    async with session_factory() as session:
        adapter = await _resolve_source_adapter(
            session,
            organization_id=organization_id,
            source_id=source_id,
            invocation_budget_seconds=invocation_budget_seconds,
            selected_objects=selected_objects,
            registry=active_registry,
        )
    try:
        yield adapter
    except BaseException as error:
        try:
            await adapter.close()
        except Exception as close_error:
            logger.error(
                "SOR adapter cleanup failed after operation failure "
                "organization_id=%s source_id=%s error_type=%s",
                organization_id,
                source_id,
                type(close_error).__name__,
            )
        replacement = await _refresh_after_vendor_authorization_failure(
            error=error,
            organization_id=organization_id,
            source_id=source_id,
            invocation_budget_seconds=invocation_budget_seconds,
            registry=active_registry,
            session_factory=session_factory,
        )
        if replacement is not None:
            raise replacement from error
        raise
    else:
        await adapter.close()


async def _refresh_after_vendor_authorization_failure(
    *,
    error: BaseException,
    organization_id: UUID,
    source_id: UUID,
    invocation_budget_seconds: float,
    registry: SorRegistry,
    session_factory: Callable[[], AsyncSession],
) -> SorVendorOperationError | None:
    """Renew a rejected access token so durable retry uses fresh authority."""
    if not isinstance(error, SorVendorOperationError):
        return None
    if not error.refreshable_authorization:
        return None
    try:
        outcome = await refresh_source_connection_if_needed(
            organization_id=organization_id,
            source_id=source_id,
            minimum_validity_seconds=invocation_budget_seconds,
            force=True,
            registry=registry,
            session_factory=session_factory,
        )
    except SorConnectionRefreshError as refresh_error:
        if refresh_error.requires_reauthorization:
            return None
        return SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_REFRESH_DEFERRED,
            "The source credential refresh is temporarily unavailable.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    except Exception as refresh_error:
        logger.error(
            "SOR access-token refresh failed unexpectedly "
            "organization_id=%s source_id=%s error_type=%s",
            organization_id,
            source_id,
            type(refresh_error).__name__,
        )
        return None
    if outcome is SorRefreshDisposition.NOT_DUE:
        return None
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_AUTHORIZATION_REFRESHED,
        "The source credential was refreshed; retry the operation.",
        recovery=SorRecoveryPolicy.RETRY,
    )


async def _resolve_source_adapter(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_id: UUID,
    invocation_budget_seconds: float,
    selected_objects: Sequence[str] | None,
    registry: SorRegistry,
) -> SorLifecycleAdapter:
    repository = SorRepository(session)
    source = await repository.get_source(
        organization_id=organization_id,
        source_id=source_id,
    )
    if source is None:
        raise SorAdapterUnavailableError("SOURCE_NOT_FOUND", "SOR source not found.")

    try:
        manifest = registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
    except KeyError as error:
        raise SorAdapterUnavailableError(
            "ADAPTER_UNAVAILABLE",
            "The source adapter is not available in this deployment.",
        ) from error

    connection = await repository.get_connection(
        organization_id=organization_id,
        connection_id=source.external_connection_id,
        vendor_key=source.vendor_key,
    )
    if connection is None:
        raise SorAdapterUnavailableError(
            "CONNECTION_UNAVAILABLE",
            "The source connection is unavailable.",
            requires_reauthorization=True,
        )
    if connection.owner_kind is not ConnectionOwnerKind.ORGANIZATION:
        raise SorAdapterUnavailableError(
            "CONNECTION_OWNER_MISMATCH",
            "The source connection is not organization-owned.",
            requires_reauthorization=True,
        )
    if connection.status is not ExternalConnectionStatus.ACTIVE:
        raise SorAdapterUnavailableError(
            "CONNECTION_NOT_ACTIVE",
            "The source connection requires attention.",
            requires_reauthorization=True,
        )
    auth_kind = _normalize_auth_kind(connection.auth_kind)
    if auth_kind not in manifest.auth_kinds:
        raise SorAdapterUnavailableError(
            "CONNECTION_AUTH_MISMATCH",
            "The source connection authentication no longer matches its adapter.",
            requires_reauthorization=True,
        )
    if _expires_within(
        connection.credentials_expires_at,
        invocation_budget_seconds,
    ):
        raise SorAdapterUnavailableError(
            "CONNECTION_EXPIRES_DURING_OPERATION",
            "The source credential expires inside the operation budget.",
            requires_reauthorization=True,
        )
    if manifest.requires_instance_origin and not connection.instance_origin:
        raise SorAdapterUnavailableError(
            "INSTANCE_ORIGIN_REQUIRED",
            "The source connection has no verified instance origin.",
            requires_reauthorization=True,
        )
    if (
        manifest.fixed_origin
        and not manifest.requires_instance_origin
        and connection.instance_origin
        not in {
            None,
            manifest.fixed_origin,
        }
    ):
        raise SorAdapterUnavailableError(
            "INSTANCE_ORIGIN_MISMATCH",
            "The source connection origin no longer matches its adapter.",
            requires_reauthorization=True,
        )

    effective_objects = _effective_selected_objects(
        source=source,
        manifest=manifest,
        selected_objects=selected_objects,
    )
    required_scopes = {
        scope
        for object_key in effective_objects
        for scope in manifest.required_scopes.get(str(object_key), ())
    }
    if not required_scopes.issubset(set(connection.granted_scopes or [])):
        raise SorAdapterUnavailableError(
            "CONNECTION_SCOPE_MISSING",
            "The source connection requires additional authorization scopes.",
            requires_reauthorization=True,
        )

    credentials = _resolve_credentials(
        auth_kind=auth_kind,
        envelope=connection.credentials,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        revision=connection.revision,
    )
    field_selections = await _field_selections(
        repository,
        organization_id=organization_id,
        source_id=source.id,
        mapping_revision_id=source.active_mapping_revision_id,
    )
    webhook_auth_secret = await _webhook_app_secret(
        repository,
        source=source,
        manifest=manifest,
    )
    context = SorAdapterContext(
        organization_id=organization_id,
        source_id=source.id,
        external_connection_id=connection.id,
        vendor_key=source.vendor_key,
        auth_kind=auth_kind,
        instance_origin=connection.instance_origin or manifest.fixed_origin,
        granted_scopes=frozenset(connection.granted_scopes or ()),
        selected_objects=effective_objects,
        mapping_revision_id=source.active_mapping_revision_id,
        fields=field_selections,
        credentials=MappingProxyType(credentials),
        webhook_signing_secret=await _webhook_signing_secret(
            repository,
            source=source,
            manifest=manifest,
            connection_revision=connection.revision,
        ),
        webhook_auth_secret=webhook_auth_secret,
        webhook_subscription_id=source.webhook_subscription_id,
        configuration=require_json_object(source.configuration or {}),
    )
    return registry.create_adapter(
        profile=source.profile,
        vendor_key=source.vendor_key,
        context=context,
    )


def _effective_selected_objects(
    *,
    source: SorSourceModel,
    manifest: SorAdapterCapabilityManifest,
    selected_objects: Sequence[str] | None,
) -> tuple[str, ...]:
    """Resolve a bounded discovery override without changing source authority."""
    current = tuple(str(value) for value in source.selected_objects)
    if selected_objects is None:
        return current
    normalized = tuple(dict.fromkeys(value.strip() for value in selected_objects))
    if not normalized or any(not value or len(value) > 160 for value in normalized):
        raise SorAdapterUnavailableError(
            "SOURCE_SELECTION_INVALID",
            "The requested source object selection is invalid.",
        )
    manifest_objects = {stream.key for stream in manifest.streams}
    allowed = manifest_objects | set(current)
    unknown = set(normalized) - allowed
    if unknown:
        raise SorAdapterUnavailableError(
            "SOURCE_SELECTION_UNSUPPORTED",
            "The adapter does not support the requested source objects.",
        )
    return normalized


async def _webhook_signing_secret(
    repository: SorRepository,
    *,
    source: SorSourceModel,
    manifest: SorAdapterCapabilityManifest,
    connection_revision: int,
) -> str | None:
    """Decrypt a configured webhook secret only at the adapter composition edge."""
    if (
        manifest.change_mode is SorChangeMode.APP_WEBHOOK
        and source.vendor_key == "linear"
    ):
        connector = await repository.get_connector_for_connection(
            organization_id=source.organization_id,
            connection_id=source.external_connection_id,
        )
        if connector is None or connector.webhook_signing_secret is None:
            raise SorAdapterUnavailableError(
                "WEBHOOK_APP_UNAVAILABLE",
                "The connector-owned webhook secret is unavailable.",
                requires_reauthorization=True,
            )
        if connector.webhook_authorized_connection_revision != connection_revision:
            raise SorAdapterUnavailableError(
                "WEBHOOK_APP_REINSTALL_REQUIRED",
                "The provider application must be reinstalled after webhook setup.",
                requires_reauthorization=True,
            )
        try:
            return decrypt_connector_webhook_signing_secret(
                connector.webhook_signing_secret,
                organization_id=connector.organization_id,
                connector_id=connector.id,
                secret_revision=connector.webhook_signing_secret_revision,
            )
        except SorSecretEnvelopeError as error:
            raise SorAdapterUnavailableError(
                "WEBHOOK_SECRET_INVALID",
                "The connector webhook signing secret could not be authenticated.",
            ) from error

    envelope = source.webhook_signing_secret
    if envelope is None:
        if source.webhook_signing_secret_revision != 0:
            raise SorAdapterUnavailableError(
                "WEBHOOK_SECRET_INVALID",
                "The source webhook signing secret is inconsistent.",
            )
        return None
    try:
        return decrypt_source_webhook_signing_secret(
            envelope,
            organization_id=source.organization_id,
            source_id=source.id,
            secret_revision=source.webhook_signing_secret_revision,
        )
    except SorSecretEnvelopeError as error:
        raise SorAdapterUnavailableError(
            "WEBHOOK_SECRET_INVALID",
            "The source webhook signing secret could not be authenticated.",
        ) from error


async def _webhook_app_secret(
    repository: SorRepository,
    *,
    source: SorSourceModel,
    manifest: SorAdapterCapabilityManifest,
) -> str | None:
    """Open the OAuth app signing secret only for a managed webhook adapter."""
    if manifest.change_mode is not SorChangeMode.MANAGED_WEBHOOK:
        return None
    connector = await repository.get_connector_for_connection(
        organization_id=source.organization_id,
        connection_id=source.external_connection_id,
    )
    if connector is None:
        raise SorAdapterUnavailableError(
            "WEBHOOK_APP_UNAVAILABLE",
            "The source webhook application is unavailable.",
            requires_reauthorization=True,
        )
    try:
        secret = decrypt_connector_client_secret(
            connector.oauth_client_secret,
            organization_id=connector.organization_id,
            connector_id=connector.id,
            config_revision=connector.config_revision,
        )
    except SorSecretEnvelopeError as error:
        raise SorAdapterUnavailableError(
            "WEBHOOK_APP_UNAVAILABLE",
            "The source webhook application credentials could not be authenticated.",
            requires_reauthorization=True,
        ) from error
    return secret


async def _field_selections(
    repository: SorRepository,
    *,
    organization_id: UUID,
    source_id: UUID,
    mapping_revision_id: UUID | None,
) -> tuple[SorAdapterFieldSelection, ...]:
    if mapping_revision_id is None:
        return ()
    rows = await repository.list_field_mappings(
        organization_id=organization_id,
        source_id=source_id,
        mapping_revision_id=mapping_revision_id,
    )
    selections: list[SorAdapterFieldSelection] = []
    for row in rows:
        if (
            row.direction is SorFieldMappingDirection.IGNORE
            or row.state is not SorFieldMappingState.ACTIVE
        ):
            continue
        if row.canonical_target_path is not None:
            agent_key = row.canonical_target_path
        elif row.custom_field_definition_id is not None:
            agent_key = f"custom.{row.custom_field_definition_id}"
        else:
            raise SorAdapterUnavailableError(
                "MAPPING_INVALID",
                "The active source mapping contains a field without a target.",
            )
        selections.append(
            SorAdapterFieldSelection(
                vendor_object_key=row.vendor_object_key,
                vendor_field_key=row.vendor_field_key,
                agent_key=agent_key,
                writable=(
                    row.direction is SorFieldMappingDirection.READ_WRITE
                    and row.writable_capability
                ),
            )
        )
    return tuple(selections)


def _resolve_credentials(
    *,
    auth_kind: ConnectionAuthKind,
    envelope: str | None,
    organization_id: UUID,
    connection_id: UUID,
    revision: int,
) -> dict[str, JsonValue]:
    if auth_kind is ConnectionAuthKind.NO_AUTH:
        if envelope is not None:
            raise SorAdapterUnavailableError(
                "UNEXPECTED_CONNECTION_CREDENTIALS",
                "The unauthenticated source connection has unexpected credentials.",
            )
        return {}
    if envelope is None:
        raise SorAdapterUnavailableError(
            "CONNECTION_CREDENTIALS_MISSING",
            "The source connection credentials are unavailable.",
            requires_reauthorization=True,
        )
    try:
        credentials = decrypt_connection_credentials(
            envelope,
            organization_id=organization_id,
            connection_id=connection_id,
            revision=revision,
        )
    except Exception as error:
        raise SorAdapterUnavailableError(
            "CONNECTION_CREDENTIALS_INVALID",
            "The source connection credentials could not be authenticated.",
            requires_reauthorization=True,
        ) from error
    if not isinstance(credentials, Mapping):
        raise SorAdapterUnavailableError(
            "CONNECTION_CREDENTIALS_INVALID",
            "The source connection credentials are invalid.",
            requires_reauthorization=True,
        )
    try:
        return require_json_object(credentials)
    except (ValidationError, SorJsonValueError) as error:
        raise SorAdapterUnavailableError(
            "CONNECTION_CREDENTIALS_INVALID",
            "The source connection credentials are invalid.",
            requires_reauthorization=True,
        ) from error


def _normalize_auth_kind(value: ConnectionAuthKind | str) -> ConnectionAuthKind:
    """Restore the domain enum at the persistence-to-adapter boundary."""
    try:
        return ConnectionAuthKind(value)
    except ValueError as error:
        raise SorAdapterUnavailableError(
            "CONNECTION_AUTH_INVALID",
            "The source connection authentication kind is invalid.",
            requires_reauthorization=True,
        ) from error


def _expires_within(expires_at: datetime | None, budget_seconds: float) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=budget_seconds)


__all__ = ["SorAdapterUnavailableError", "acquire_source_adapter"]
