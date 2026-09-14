"""Compose API-key SOR credentials with source creation and verification."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from uuid import UUID

import uuid_utils
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.connections.domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.schemas.external import ExternalConnectionCreateSchema
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.pipelines.external_connections.credentials import (
    encrypt_connection_credentials,
)
from eylo.sor.runtime.action_events import (
    SorConnectionEventType,
    file_sor_connection_event,
)
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import SorAdapterContext, SorProfile
from eylo.sor.shared.json_values import SorJsonValue, require_json_object
from eylo.sor.shared.models import SorSourceModel
from eylo.sor.shared.services import SorConfigurationError, SorSourceService

_VERIFY_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)


class _VerifiedApiKeySourceCandidate(BaseModel):
    """Transient proof binding verified authority to its persistence inputs."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        validate_default=True,
    )

    organization_id: UUID
    profile: SorProfile
    vendor_key: str
    api_key: str = Field(repr=False, exclude=True)
    instance_origin: str | None = None
    selected_objects: tuple[str, ...] = ()
    configuration: Mapping[str, SorJsonValue] = Field(default_factory=dict)

    @field_validator("configuration")
    @classmethod
    def _seal_configuration(
        cls, value: Mapping[str, SorJsonValue]
    ) -> Mapping[str, SorJsonValue]:
        return MappingProxyType(dict(value))

    @field_serializer("configuration")
    def _configuration_snapshot(
        self, value: Mapping[str, SorJsonValue]
    ) -> dict[str, JsonValue]:
        return dict(value)


async def verify_api_key_source_candidate(
    *,
    organization_id: UUID,
    profile: SorProfile,
    vendor_key: str,
    api_key: str,
    instance_origin: str | None,
    selected_objects: Sequence[str],
    configuration: Mapping[str, object] | None = None,
    registry: SorRegistry | None = None,
) -> _VerifiedApiKeySourceCandidate:
    """Verify one transient credential without persisting or returning its value."""
    active_registry = registry or get_sor_registry()
    normalized_vendor = vendor_key.strip().lower()
    normalized_key = _api_key(api_key)
    validated_configuration = require_json_object(configuration or {})
    try:
        manifest = active_registry.get_manifest(
            profile=profile,
            vendor_key=normalized_vendor,
        )
    except KeyError as error:
        raise SorConfigurationError(
            f"{profile.value}/{normalized_vendor} is not executable."
        ) from error
    if ConnectionAuthKind.API_KEY not in manifest.auth_kinds:
        raise SorConfigurationError(
            "This SOR adapter does not support API-key authentication."
        )

    candidate_id = uuid.UUID(str(uuid_utils.uuid7()))
    try:
        adapter = active_registry.create_adapter(
            profile=profile,
            vendor_key=normalized_vendor,
            context=SorAdapterContext(
                organization_id=organization_id,
                source_id=uuid.UUID(str(uuid_utils.uuid7())),
                external_connection_id=candidate_id,
                vendor_key=normalized_vendor,
                auth_kind=ConnectionAuthKind.API_KEY,
                instance_origin=instance_origin,
                granted_scopes=frozenset(),
                selected_objects=tuple(selected_objects),
                mapping_revision_id=None,
                fields=(),
                credentials=MappingProxyType({"api_key": normalized_key}),
                configuration=validated_configuration,
            ),
        )
    except (KeyError, ValueError) as error:
        raise SorConfigurationError(str(error)) from error
    try:
        async with asyncio.timeout(_VERIFY_TIMEOUT_SECONDS):
            await adapter.verify_connection()
    except BaseException:
        try:
            await adapter.close()
        except Exception as close_error:
            logger.error(
                "SOR API-key candidate cleanup failed vendor=%s error_type=%s",
                normalized_vendor,
                type(close_error).__name__,
            )
        raise
    else:
        await adapter.close()
        return _VerifiedApiKeySourceCandidate(
            organization_id=organization_id,
            profile=profile,
            vendor_key=normalized_vendor,
            api_key=normalized_key,
            instance_origin=instance_origin,
            selected_objects=tuple(selected_objects),
            configuration=validated_configuration,
        )


async def create_api_key_source(
    session: AsyncSession,
    *,
    candidate: _VerifiedApiKeySourceCandidate,
    onboarding_attempt_id: UUID,
    name: str,
    freshness_target_seconds: int,
    required_sync_interval_seconds: int,
    registry: SorRegistry | None = None,
) -> SorSourceModel:
    """Create or return one API-key source for an onboarding attempt."""
    active_registry = registry or get_sor_registry()
    try:
        manifest = active_registry.get_manifest(
            profile=candidate.profile,
            vendor_key=candidate.vendor_key,
        )
    except KeyError as error:
        raise SorConfigurationError(
            f"{candidate.profile.value}/{candidate.vendor_key} is not executable."
        ) from error
    if ConnectionAuthKind.API_KEY not in manifest.auth_kinds:
        raise SorConfigurationError(
            "This SOR adapter does not support API-key authentication."
        )

    sources = SorSourceService(session, registry=active_registry)
    instance_origin = candidate.instance_origin or manifest.fixed_origin
    existing = await sources.reuse_onboarding_attempt(
        organization_id=candidate.organization_id,
        onboarding_attempt_id=onboarding_attempt_id,
        name=name,
        profile=candidate.profile,
        vendor_key=candidate.vendor_key,
        configuration=candidate.configuration,
        selected_objects=candidate.selected_objects,
        freshness_target_seconds=freshness_target_seconds,
        required_sync_interval_seconds=required_sync_interval_seconds,
        expected_instance_origin=instance_origin,
    )
    if existing is not None:
        return existing

    connection_id = uuid.UUID(str(uuid_utils.uuid7()))
    encrypted = encrypt_connection_credentials(
        {"api_key": candidate.api_key},
        organization_id=candidate.organization_id,
        connection_id=connection_id,
        revision=1,
    )
    connection = await ExternalConnectionService(session).create(
        ExternalConnectionCreateSchema(
            id=connection_id,
            organization_id=candidate.organization_id,
            owner_kind=ConnectionOwnerKind.ORGANIZATION,
            vendor_key=candidate.vendor_key,
            auth_kind=ConnectionAuthKind.API_KEY,
            instance_origin=instance_origin,
            granted_scopes=[],
            credentials=encrypted,
            status=ExternalConnectionStatus.ACTIVE,
        )
    )
    source = await sources.create(
        organization_id=candidate.organization_id,
        onboarding_attempt_id=onboarding_attempt_id,
        name=name,
        profile=candidate.profile,
        vendor_key=candidate.vendor_key,
        external_connection_id=connection.id,
        configuration=candidate.configuration,
        selected_objects=candidate.selected_objects,
        freshness_target_seconds=freshness_target_seconds,
        required_sync_interval_seconds=required_sync_interval_seconds,
    )
    await file_sor_connection_event(
        session,
        organization_id=candidate.organization_id,
        connection_id=connection.id,
        connection_revision=connection.revision,
        event_sequence=f"connected:{connection.revision}",
        event_type=SorConnectionEventType.CONNECTED,
        occurred_at=connection.created_at,
        profile=candidate.profile,
        vendor_key=candidate.vendor_key,
        source_id=source.id,
    )
    return source


def _api_key(value: str) -> str:
    if not value or not value.strip() or value != value.strip() or len(value) > 4096:
        raise SorConfigurationError(
            "API key must contain 1 to 4096 characters without surrounding spaces."
        )
    return value


__all__ = ["create_api_key_source", "verify_api_key_source_candidate"]
