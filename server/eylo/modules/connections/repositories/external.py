"""Persistence queries for source-neutral external connections."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import get_transaction

from ..domain import ConnectionOwnerKind, ExternalConnectionStatus
from ..models import ExternalConnectionModel


class ExternalConnectionRepository:
    """Load and persist external account rows without deciding lifecycle policy."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db or get_transaction()

    async def add(self, row: ExternalConnectionModel) -> ExternalConnectionModel:
        self._db.add(row)
        await self._db.flush()
        return row

    async def get(
        self,
        *,
        organization_id: UUID,
        connection_id: UUID,
        for_update: bool = False,
    ) -> ExternalConnectionModel | None:
        statement = select(ExternalConnectionModel).where(
            ExternalConnectionModel.id == connection_id,
            ExternalConnectionModel.organization_id == organization_id,
            ExternalConnectionModel.deleted.is_(False),
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._db.scalar(statement)

    async def list_for_organization(
        self,
        *,
        organization_id: UUID,
    ) -> Sequence[ExternalConnectionModel]:
        result = await self._db.scalars(
            select(ExternalConnectionModel)
            .where(
                ExternalConnectionModel.organization_id == organization_id,
                ExternalConnectionModel.deleted.is_(False),
            )
            .order_by(
                ExternalConnectionModel.updated_at.desc(),
                ExternalConnectionModel.id.desc(),
            )
        )
        return result.all()

    async def delete_old_revoked_contact_connections(
        self,
        *,
        updated_before: datetime,
    ) -> list[UUID]:
        """Physically remove old contact credentials after their audit retention."""
        result = await self._db.execute(
            delete(ExternalConnectionModel)
            .where(
                ExternalConnectionModel.owner_kind == ConnectionOwnerKind.CONTACT,
                ExternalConnectionModel.status == ExternalConnectionStatus.REVOKED,
                ExternalConnectionModel.deleted.is_(True),
                ExternalConnectionModel.updated_at < updated_before,
            )
            .returning(ExternalConnectionModel.id)
        )
        return list(result.scalars().all())


__all__ = ["ExternalConnectionRepository"]
