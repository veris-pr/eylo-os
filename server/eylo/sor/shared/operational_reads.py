"""Bounded operator projection for SOR sync and relationship health."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select
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

_CURSOR_VERSION = 1


class SorOperationalReadQueryError(Exception):
    """Raised when an operational-read cursor is invalid for the source."""


class _GenerationCursor(BaseModel):
    """Source-scoped position for stable synchronization history pagination."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    source_id: UUID
    created_at: datetime
    generation_id: UUID


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
        generation_cursor: str | None = None,
        generation_limit: int = 1,
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
        cursor = _decode_generation_cursor(generation_cursor, source_id=source_id)

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

        generation_predicates = [
            SorSyncGenerationModel.organization_id == organization_id,
            SorSyncGenerationModel.source_id == source_id,
            SorSyncGenerationModel.deleted.is_(False),
        ]
        if cursor is not None:
            generation_predicates.append(
                or_(
                    SorSyncGenerationModel.created_at < cursor.created_at,
                    and_(
                        SorSyncGenerationModel.created_at == cursor.created_at,
                        SorSyncGenerationModel.id < cursor.generation_id,
                    ),
                )
            )
        generation_rows = list(
            (
                await self.session.scalars(
                    select(SorSyncGenerationModel)
                    .where(*generation_predicates)
                    .order_by(
                        SorSyncGenerationModel.created_at.desc(),
                        SorSyncGenerationModel.id.desc(),
                    )
                    .limit(generation_limit + 1)
                )
            ).all()
        )
        has_more = len(generation_rows) > generation_limit
        generations = generation_rows[:generation_limit]
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
            next_cursor=(
                _encode_generation_cursor(generations[-1])
                if has_more and generations
                else None
            ),
            has_more=has_more,
        )


def _encode_generation_cursor(generation: SorSyncGenerationModel) -> str:
    payload = json.dumps(
        {
            "v": _CURSOR_VERSION,
            "source_id": str(generation.source_id),
            "created_at": generation.created_at.isoformat(),
            "generation_id": str(generation.id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_generation_cursor(
    value: str | None,
    *,
    source_id: UUID,
) -> _GenerationCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        cursor = _GenerationCursor(
            source_id=UUID(payload["source_id"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            generation_id=UUID(payload["generation_id"]),
        )
    except (
        binascii.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise SorOperationalReadQueryError(
            "Synchronization history cursor is invalid."
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"v", "source_id", "created_at", "generation_id"}
        or payload["v"] != _CURSOR_VERSION
        or cursor.source_id != source_id
        or cursor.created_at.tzinfo is None
    ):
        raise SorOperationalReadQueryError(
            "Synchronization history cursor does not match this source."
        )
    return cursor


__all__ = ["SorOperationalReadQueryError", "SorOperationalReadService"]
