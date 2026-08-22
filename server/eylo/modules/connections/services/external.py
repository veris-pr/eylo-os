"""Application service for source-neutral external account lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import get_transaction
from eylo.modules.contacts.schemas.indb import ContactRef
from eylo.modules.contacts.service import ContactService

from ..domain import (
    ConnectionAuthKind,
    ExternalConnectionNotFoundError,
    ExternalConnectionRevisionConflictError,
    ExternalConnectionStateError,
    ExternalConnectionStatus,
)
from ..models import ExternalConnectionModel
from ..repositories.external import ExternalConnectionRepository
from ..schemas.external import ExternalConnectionCreateSchema, ExternalConnectionInDb


class ExternalConnectionService:
    """Own connection creation, credential revision, revocation, and state changes."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db or get_transaction()
        self._connections = ExternalConnectionRepository(self._db)

    async def create(
        self,
        data: ExternalConnectionCreateSchema,
    ) -> ExternalConnectionInDb:
        if data.contact_id is not None:
            await ContactService(self._db).require_active(
                ContactRef(
                    organization_id=data.organization_id,
                    contact_id=data.contact_id,
                ),
                for_update=True,
            )
        row = ExternalConnectionModel(**data.model_dump())
        return ExternalConnectionInDb.model_validate(await self._connections.add(row))

    async def get(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ExternalConnectionInDb | None:
        row = await self._connections.get(
            organization_id=organization_id,
            connection_id=connection_id,
        )
        return ExternalConnectionInDb.model_validate(row) if row is not None else None

    async def list_for_organization(
        self,
        *,
        organization_id: UUID,
    ) -> list[ExternalConnectionInDb]:
        rows = await self._connections.list_for_organization(
            organization_id=organization_id
        )
        return [ExternalConnectionInDb.model_validate(row) for row in rows]

    async def activate(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        expected_revision: int,
        encrypted_credentials: str | None,
        credentials_expires_at: datetime | None,
        granted_scopes: list[str],
        instance_origin: str | None = None,
    ) -> ExternalConnectionInDb:
        row = await self._required_for_update(organization_id, connection_id)
        self._require_revision(row, expected_revision)
        if row.status not in {
            ExternalConnectionStatus.INITIATED,
            ExternalConnectionStatus.REAUTH_REQUIRED,
        }:
            raise ExternalConnectionStateError(
                "Only initiated or reauthorization-required connections can activate."
            )
        if row.auth_kind != ConnectionAuthKind.NO_AUTH and not encrypted_credentials:
            raise ExternalConnectionStateError(
                "Authenticated connections require encrypted credentials."
            )
        row.revision += 1
        row.credentials = encrypted_credentials
        row.credentials_expires_at = credentials_expires_at
        row.granted_scopes = list(granted_scopes)
        if instance_origin is not None:
            row.instance_origin = instance_origin
        row.status = ExternalConnectionStatus.ACTIVE
        row.refresh_attempts = 0
        row.last_error_code = None
        await self._db.flush()
        return ExternalConnectionInDb.model_validate(row)

    async def renew_credentials(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        expected_revision: int,
        encrypted_credentials: str,
        credentials_expires_at: datetime | None,
        granted_scopes: list[str],
        instance_origin: str | None = None,
    ) -> ExternalConnectionInDb:
        row = await self._required_for_update(organization_id, connection_id)
        self._require_revision(row, expected_revision)
        if row.status not in {
            ExternalConnectionStatus.ACTIVE,
            ExternalConnectionStatus.DEGRADED,
        }:
            raise ExternalConnectionStateError(
                "Only active or degraded connections can renew credentials."
            )
        row.revision += 1
        row.credentials = encrypted_credentials
        row.credentials_expires_at = credentials_expires_at
        row.granted_scopes = list(granted_scopes)
        if instance_origin is not None:
            row.instance_origin = instance_origin
        row.status = ExternalConnectionStatus.ACTIVE
        row.last_refresh_success_at = datetime.now(timezone.utc)
        row.refresh_attempts = 0
        row.last_error_code = None
        await self._db.flush()
        return ExternalConnectionInDb.model_validate(row)

    async def mark_degraded(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        expected_revision: int,
        error_code: str,
    ) -> ExternalConnectionInDb:
        row = await self._required_for_update(organization_id, connection_id)
        self._require_revision(row, expected_revision)
        if row.status is ExternalConnectionStatus.REVOKED:
            raise ExternalConnectionStateError("Revoked connections cannot degrade.")
        row.status = ExternalConnectionStatus.DEGRADED
        row.refresh_attempts += 1
        row.last_refresh_failure_at = datetime.now(timezone.utc)
        row.last_error_code = error_code
        await self._db.flush()
        return ExternalConnectionInDb.model_validate(row)

    async def require_reauthorization(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        expected_revision: int,
        error_code: str,
    ) -> ExternalConnectionInDb:
        row = await self._required_for_update(organization_id, connection_id)
        self._require_revision(row, expected_revision)
        if row.status is ExternalConnectionStatus.REVOKED:
            raise ExternalConnectionStateError(
                "Revoked connections cannot require reauthorization."
            )
        row.status = ExternalConnectionStatus.REAUTH_REQUIRED
        row.refresh_attempts += 1
        row.last_refresh_failure_at = datetime.now(timezone.utc)
        row.last_error_code = error_code
        await self._db.flush()
        return ExternalConnectionInDb.model_validate(row)

    async def revoke(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> bool:
        """Revoke one connection and discard the internal state snapshot."""
        return (
            await self.revoke_with_snapshot(
                organization_id=organization_id,
                connection_id=connection_id,
            )
            is not None
        )

    async def revoke_with_snapshot(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ExternalConnectionInDb | None:
        """Revoke one connection while returning its locked final identity."""
        row = await self._connections.get(
            organization_id=organization_id,
            connection_id=connection_id,
            for_update=True,
        )
        if row is None:
            return None
        row.status = ExternalConnectionStatus.REVOKED
        row.credentials = None
        row.credentials_expires_at = None
        row.deleted = True
        await self._db.flush()
        return ExternalConnectionInDb.model_validate(row)

    async def revoke_expired_authorization_attempt(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        expected_revision: int | None,
    ) -> bool:
        """Discard only the still-initiated connection owned by an expired state."""
        if expected_revision is None:
            return False
        row = await self._connections.get(
            organization_id=organization_id,
            connection_id=connection_id,
            for_update=True,
        )
        if (
            row is None
            or row.status is not ExternalConnectionStatus.INITIATED
            or row.revision != expected_revision
        ):
            return False
        row.status = ExternalConnectionStatus.REVOKED
        row.credentials = None
        row.credentials_expires_at = None
        row.deleted = True
        await self._db.flush()
        return True

    async def cleanup_old_revoked_contact_connections(
        self,
        *,
        retention_days: int,
    ) -> list[UUID]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        return await self._connections.delete_old_revoked_contact_connections(
            updated_before=cutoff
        )

    async def _required_for_update(
        self,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ExternalConnectionModel:
        row = await self._connections.get(
            organization_id=organization_id,
            connection_id=connection_id,
            for_update=True,
        )
        if row is None:
            raise ExternalConnectionNotFoundError("External connection not found.")
        return row

    @staticmethod
    def _require_revision(row: ExternalConnectionModel, expected_revision: int) -> None:
        if row.revision != expected_revision:
            raise ExternalConnectionRevisionConflictError(
                "External connection revision changed."
            )


__all__ = ["ExternalConnectionService"]
