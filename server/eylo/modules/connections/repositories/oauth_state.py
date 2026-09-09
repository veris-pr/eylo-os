"""Repository for OAuth state management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from eylo.common.repositories import BaseORMRepository as EyloBaseRepository
from eylo.common.repositories import map_schema_to_model
from eylo.modules.connections.models import OAuthStateModel
from eylo.modules.connections.schemas.oauth import OAuthStateCreateSchema


class ExpiredOAuthState(BaseModel):
    """Expired attempt whose matching initiated connection may need cleanup."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    id: UUID
    organization_id: UUID
    external_connection_id: UUID
    expected_connection_revision: int | None = Field(ge=1)


class OAuthStateRepository(EyloBaseRepository[OAuthStateModel]):
    """Repository for OAuth state tracking."""

    @property
    def model(self) -> type[OAuthStateModel]:
        """Model property."""
        return OAuthStateModel

    async def create_state(self, data: OAuthStateCreateSchema) -> OAuthStateModel:
        """Create OAuth state record.

        Args:
            data: OAuth state creation schema

        Returns:
            Created OAuthStateModel

        """
        validated = OAuthStateCreateSchema.model_validate(data)
        oauth_state = map_schema_to_model(OAuthStateModel, validated)
        return await self.save_(oauth_state)

    async def get_by_state(self, state: str) -> OAuthStateModel | None:
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

    async def consume_by_state(self, state: str) -> OAuthStateModel | None:
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
    ) -> list[ExpiredOAuthState]:
        """Delete expired attempts and return exactly the removed ownership receipts.

        Include consumed states: a failed/cancelled exchange spends its state but
        may leave an initiated connection. The service's revision/status guard
        decides whether that connection still belongs to this abandoned attempt.
        """
        result = await self.db_session.execute(
            delete(OAuthStateModel)
            .where(OAuthStateModel.expires_at < current_time)
            .returning(
                OAuthStateModel.id,
                OAuthStateModel.organization_id,
                OAuthStateModel.external_connection_id,
                OAuthStateModel.expected_connection_revision,
            )
        )
        expired_states = [
            ExpiredOAuthState(
                id=state_id,
                organization_id=organization_id,
                external_connection_id=connection_id,
                expected_connection_revision=revision,
            )
            for state_id, organization_id, connection_id, revision in result.all()
        ]
        await self.db_session.flush()
        return expired_states

    async def invalidate_for_connection_revision(
        self,
        *,
        organization_id: UUID,
        external_connection_id: UUID,
        expected_connection_revision: int,
    ) -> int:
        """Spend sibling attempts after one callback advances the connection."""
        rows = list(
            (
                await self.db_session.scalars(
                    select(OAuthStateModel).where(
                        OAuthStateModel.organization_id == organization_id,
                        OAuthStateModel.external_connection_id
                        == external_connection_id,
                        OAuthStateModel.expected_connection_revision
                        == expected_connection_revision,
                        OAuthStateModel.deleted.is_(False),
                    )
                )
            ).all()
        )
        for row in rows:
            await self.delete_(row)
        await self.db_session.flush()
        return len(rows)

    async def delete_for_connection(
        self,
        *,
        organization_id: UUID,
        external_connection_id: UUID,
    ) -> int:
        """Hard-delete every transient OAuth state owned by one connection."""
        result = await self.db_session.scalars(
            delete(OAuthStateModel)
            .where(
                OAuthStateModel.organization_id == organization_id,
                OAuthStateModel.external_connection_id == external_connection_id,
            )
            .returning(OAuthStateModel.id)
        )
        await self.db_session.flush()
        return len(result.all())


__all__ = ["ExpiredOAuthState", "OAuthStateRepository"]
