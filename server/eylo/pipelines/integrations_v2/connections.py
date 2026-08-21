"""Compose Integration V2 installations with source-neutral connections."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

import uuid_utils

from eylo.modules.connections.domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.schemas.external import (
    ExternalConnectionCreateSchema,
    ExternalConnectionInDb,
)
from eylo.modules.connections.services.external import ExternalConnectionService
from eylo.modules.integrations_v2.schemas.indb import InstallationInDb
from eylo.modules.integrations_v2.services.installations import (
    CuratedIntegrationService,
)
from eylo.pipelines.external_connections.credentials import (
    encrypt_connection_credentials,
)


async def create_curated_external_connection(
    *,
    installation: InstallationInDb,
    contact_id: UUID | None,
    credentials: Mapping[str, object] | None,
    credentials_expires_at: datetime | None,
    granted_scopes: Sequence[str],
    status: ExternalConnectionStatus,
    connections: ExternalConnectionService | None = None,
    integrations: CuratedIntegrationService | None = None,
) -> ExternalConnectionInDb:
    """Create and link one account atomically inside the caller's transaction."""
    connection_id = uuid.UUID(str(uuid_utils.uuid7()))
    encrypted_credentials = (
        encrypt_connection_credentials(
            credentials,
            organization_id=installation.organization_id,
            connection_id=connection_id,
            revision=1,
        )
        if credentials is not None
        else None
    )
    connection = await (connections or ExternalConnectionService()).create(
        ExternalConnectionCreateSchema(
            id=connection_id,
            organization_id=installation.organization_id,
            contact_id=contact_id,
            owner_kind=(
                ConnectionOwnerKind.CONTACT
                if contact_id is not None
                else ConnectionOwnerKind.ORGANIZATION
            ),
            vendor_key=installation.vendor,
            auth_kind=ConnectionAuthKind(_enum_value(installation.auth_kind)),
            instance_origin=installation.instance_url,
            granted_scopes=list(granted_scopes),
            credentials=encrypted_credentials,
            credentials_expires_at=credentials_expires_at,
            status=status,
        )
    )
    await (integrations or CuratedIntegrationService()).link_external_connection(
        organization_id=installation.organization_id,
        installation_id=installation.id,
        connection_id=connection.id,
        vendor=installation.vendor,
    )
    return connection


async def activate_curated_external_connection(
    *,
    connection: ExternalConnectionInDb,
    credentials: Mapping[str, object],
    credentials_expires_at: datetime | None,
    granted_scopes: Sequence[str],
    service: ExternalConnectionService | None = None,
) -> ExternalConnectionInDb:
    """Encrypt the first grant at the next revision, then activate its row."""
    next_revision = connection.revision + 1
    encrypted = encrypt_connection_credentials(
        credentials,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        revision=next_revision,
    )
    return await (service or ExternalConnectionService()).activate(
        organization_id=connection.organization_id,
        connection_id=connection.id,
        expected_revision=connection.revision,
        encrypted_credentials=encrypted,
        credentials_expires_at=credentials_expires_at,
        granted_scopes=list(granted_scopes),
    )


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


__all__ = [
    "activate_curated_external_connection",
    "create_curated_external_connection",
]
