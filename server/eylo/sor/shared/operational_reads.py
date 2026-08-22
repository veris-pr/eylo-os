"""Bounded operator projection for SOR sync and relationship health."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import SorRelationIntentState
from .models import (
    SorRelationIntentModel,
    SorSyncGenerationModel,
    SorSyncRunModel,
)
from .repositories import SorRepository
from .schemas import (
    SorRelationshipHealthResponse,
    SorSourceOperationsResponse,
    SorSyncGenerationResponse,
    SorSyncRunResponse,
)
from .services import SorNotFoundError


class SorOperationalReadService:
    """Read one tenant-scoped source's recent DAGs and relationship backlog."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def source_operations(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        generation_limit: int = 10,
    ) -> SorSourceOperationsResponse:
        """Return bounded operational state without exposing checkpoints or payloads."""
        if isinstance(generation_limit, bool) or not 1 <= generation_limit <= 50:
            raise ValueError("Generation limit must be between 1 and 50.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")

        relationship_rows = (
            await self.session.execute(
                select(
                    SorRelationIntentModel.state,
                    func.count(SorRelationIntentModel.id),
                )
                .where(
                    SorRelationIntentModel.organization_id == organization_id,
                    SorRelationIntentModel.source_id == source_id,
                    SorRelationIntentModel.deleted.is_(False),
                )
                .group_by(SorRelationIntentModel.state)
            )
        ).all()
        relationship_counts = {state: int(count) for state, count in relationship_rows}

        generations = list(
            (
                await self.session.scalars(
                    select(SorSyncGenerationModel)
                    .where(
                        SorSyncGenerationModel.organization_id == organization_id,
                        SorSyncGenerationModel.source_id == source_id,
                        SorSyncGenerationModel.deleted.is_(False),
                    )
                    .order_by(
                        SorSyncGenerationModel.created_at.desc(),
                        SorSyncGenerationModel.id.desc(),
                    )
                    .limit(generation_limit)
                )
            ).all()
        )
        generation_ids = tuple(row.id for row in generations)
        runs = (
            list(
                (
                    await self.session.scalars(
                        select(SorSyncRunModel)
                        .where(
                            SorSyncRunModel.organization_id == organization_id,
                            SorSyncRunModel.source_id == source_id,
                            SorSyncRunModel.generation_id.in_(generation_ids),
                            SorSyncRunModel.deleted.is_(False),
                        )
                        .order_by(
                            SorSyncRunModel.created_at.asc(),
                            SorSyncRunModel.id.asc(),
                        )
                    )
                ).all()
            )
            if generation_ids
            else []
        )
        runs_by_generation: dict[UUID, list[SorSyncRunResponse]] = {
            generation_id: [] for generation_id in generation_ids
        }
        for run in runs:
            runs_by_generation[run.generation_id].append(
                SorSyncRunResponse.model_validate(run)
            )

        return SorSourceOperationsResponse(
            source_id=source_id,
            relationships=SorRelationshipHealthResponse(
                pending=relationship_counts.get(SorRelationIntentState.PENDING, 0),
                resolved=relationship_counts.get(SorRelationIntentState.RESOLVED, 0),
                tombstoned=relationship_counts.get(
                    SorRelationIntentState.TOMBSTONED,
                    0,
                ),
            ),
            generations=tuple(
                SorSyncGenerationResponse(
                    id=generation.id,
                    organization_id=generation.organization_id,
                    source_id=generation.source_id,
                    kind=generation.kind,
                    state=generation.state,
                    started_at=generation.started_at,
                    finished_at=generation.finished_at,
                    safe_error_code=generation.safe_error_code,
                    safe_error_summary=generation.safe_error_summary,
                    created_at=generation.created_at,
                    updated_at=generation.updated_at,
                    runs=tuple(runs_by_generation[generation.id]),
                )
                for generation in generations
            ),
        )


__all__ = ["SorOperationalReadService"]
