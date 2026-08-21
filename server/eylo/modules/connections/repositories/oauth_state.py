"""Repository for OAuth state management."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, select

from eylo.common.repositories import BaseORMRepository as EyloBaseRepository
from eylo.common.repositories import map_schema_to_model
from eylo.modules.connections.models import OAuthStateModel
from eylo.modules.connections.schemas.oauth import OAuthStateCreateSchema


@dataclass(frozen=True, slots=True)
class ExpiredOAuthState:
    """Unconsumed state whose initiated connection must also be revoked."""

    id: UUID
    organization_id: UUID
    external_connection_id: UUID


class OAuthStateRepository(EyloBaseRepository[OAuthStateModel]):
    """Repository for OAuth state tracking."""

    @property
    def model(self):
        """Model property."""
        return OAuthStateModel

    async def create_state(self, data: OAuthStateCreateSchema) -> OAuthStateModel:
        """Create OAuth state record.

        Args:
            data: OAuth state creation schema

        Returns:
            Created OAuthStateModel

        """
        oauth_state = map_schema_to_model(OAuthStateModel, data)
        return await self.save_(oauth_state)

    async def get_by_state(self, state: str) -> Optional[OAuthStateModel]:
        """Get OAuth state by state token.

        Args:
            state: State token

        Returns:
            OAuthStateModel if found, None otherwise

        """
        db = self.db_session
        stmt = select(OAuthStateModel).where(
            OAuthStateModel.state == state,
            # A consumed state must never resolve again. `delete_` is a soft
            # delete, so without this filter a spent state token still returns
            # a row and its authorization code stays replayable.
            OAuthStateModel.deleted.is_(False),
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def consume_by_state(self, state: str) -> Optional[OAuthStateModel]:
        """Lock and spend one OAuth state token exactly once.

        The caller must commit this transaction before contacting the provider.
        A concurrent callback waits on the row lock, then observes the soft
        delete and cannot exchange the same authorization code twice.
        """
        stmt = (
            select(OAuthStateModel)
            .where(
                OAuthStateModel.state == state,
                OAuthStateModel.deleted.is_(False),
            )
            .with_for_update()
        )
        oauth_state = await self.db_session.scalar(stmt)
        if oauth_state is None:
            return None
        await self.delete_(oauth_state)
        return oauth_state

    async def delete_expired_states(
        self, current_time: datetime
    ) -> List[ExpiredOAuthState]:
        """Delete OAuth states that have expired.

        Deletes OAuth state records where:
        - expires_at is before current_time
        - Returns list of deleted state IDs

        Args:
            current_time: Delete states expired before this time

        Returns:
            List of deleted OAuth state IDs

        """
        active_result = await self.db_session.execute(
            select(
                OAuthStateModel.id,
                OAuthStateModel.organization_id,
                OAuthStateModel.external_connection_id,
            ).where(
                OAuthStateModel.expires_at < current_time,
                OAuthStateModel.deleted.is_(False),
            )
        )
        active_states = [ExpiredOAuthState(*row) for row in active_result.all()]

        await self.db_session.execute(
            delete(OAuthStateModel).where(OAuthStateModel.expires_at < current_time)
        )
        await self.db_session.flush()
        return active_states


__all__ = ["ExpiredOAuthState", "OAuthStateRepository"]
