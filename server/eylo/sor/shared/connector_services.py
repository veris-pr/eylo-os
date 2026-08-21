"""Domain policy for organization-owned SOR vendor connectors."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

import uuid_utils
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.modules.connections.models import ExternalConnectionModel
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorConnectorModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import encrypt_connector_client_secret
from eylo.sor.shared.services import SorConfigurationError, SorNotFoundError


@dataclass(frozen=True, slots=True)
class SorConnectorView:
    """One safe connector projection plus its current external account."""

    connector: SorConnectorModel
    connection: ExternalConnectionModel | None


class SorConnectorService:
    """Configure OAuth clients without exposing secret material to read paths."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.registry = registry or get_sor_registry()

    async def create(
        self,
        *,
        organization_id: UUID,
        configured_by: UUID,
        name: str,
        profile: SorProfile,
        vendor_key: str,
        auth_kind: ConnectionAuthKind,
        oauth_client_id: str,
        oauth_client_secret: str,
    ) -> SorConnectorView:
        """Persist an OAuth app configuration for one executable adapter."""
        normalized_name = name.strip()
        normalized_vendor = vendor_key.strip().lower()
        normalized_client_id = oauth_client_id.strip()
        if not 1 <= len(normalized_name) <= 160:
            raise SorConfigurationError(
                "Connector name must contain 1 to 160 characters."
            )
        if not 1 <= len(normalized_client_id) <= 512:
            raise SorConfigurationError(
                "OAuth client ID must contain 1 to 512 characters."
            )
        try:
            manifest = self.registry.get_manifest(
                profile=profile,
                vendor_key=normalized_vendor,
            )
        except KeyError as error:
            raise SorConfigurationError(
                f"{profile.value}/{normalized_vendor} cannot be configured yet."
            ) from error
        if auth_kind is not ConnectionAuthKind.OAUTH2:
            raise SorConfigurationError(
                "This SOR connector revision supports OAuth 2.0 only."
            )
        if auth_kind not in manifest.auth_kinds or manifest.oauth is None:
            raise SorConfigurationError(
                "This adapter does not provide an executable OAuth contract."
            )

        connector_id = uuid.UUID(str(uuid_utils.uuid7()))
        config_revision = 1
        encrypted_secret = encrypt_connector_client_secret(
            oauth_client_secret,
            organization_id=organization_id,
            connector_id=connector_id,
            config_revision=config_revision,
        )
        connector = SorConnectorModel(
            id=connector_id,
            organization_id=organization_id,
            name=normalized_name,
            profile=profile,
            vendor_key=normalized_vendor,
            auth_kind=auth_kind,
            oauth_client_id=normalized_client_id,
            oauth_client_secret=encrypted_secret,
            config_revision=config_revision,
            configured_by=configured_by,
        )
        self.session.add(connector)
        await self.session.flush()
        return SorConnectorView(connector=connector, connection=None)

    async def get(
        self,
        *,
        organization_id: UUID,
        connector_id: UUID,
        for_update: bool = False,
    ) -> SorConnectorView:
        connector = await self.repository.get_connector(
            organization_id=organization_id,
            connector_id=connector_id,
            for_update=for_update,
        )
        if connector is None:
            raise SorNotFoundError("SOR connector not found.")
        return await self._view(connector)

    async def list(self, *, organization_id: UUID) -> tuple[SorConnectorView, ...]:
        connectors = await self.repository.list_connectors(
            organization_id=organization_id
        )
        return tuple([await self._view(connector) for connector in connectors])

    async def _view(self, connector: SorConnectorModel) -> SorConnectorView:
        connection = None
        if connector.external_connection_id is not None:
            connection = await self.repository.get_connection(
                organization_id=connector.organization_id,
                connection_id=connector.external_connection_id,
                vendor_key=connector.vendor_key,
            )
        return SorConnectorView(connector=connector, connection=connection)


__all__ = ["SorConnectorService", "SorConnectorView"]
