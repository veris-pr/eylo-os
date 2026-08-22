"""Canonical same-source relationship intent, resolution, and retry policy."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import SorRelationIntentDraft, SorRelationIntentState
from .models import (
    SorRecordRelationModel,
    SorRelationIntentModel,
)
from .repositories import SorRepository
from .services import SorProjectionError

_PENDING_RETRY_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class SorRelationshipResolutionStats:
    """Bounded product counters for one relationship-resolution pass."""

    checked: int = 0
    resolved: int = 0
    pending: int = 0
    tombstoned: int = 0


class SorRelationshipService:
    """Persist first, then resolve exact endpoint identities without vendor I/O."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = SorRepository(session)

    async def replace_origin_intents(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        origin_record_id: UUID,
        intents: Sequence[SorRelationIntentDraft],
    ) -> SorRelationshipResolutionStats:
        """Replace one record's current relationships and resolve what is present."""
        origin = await self.records.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=origin_record_id,
            for_update=True,
        )
        if origin is None:
            raise SorProjectionError("Relationship origin record not found.")
        unique = {intent.external_relation_id for intent in intents}
        if len(unique) != len(intents):
            raise SorProjectionError("Relationship intents repeat an external identity.")

        current = list(
            (
                await self.session.scalars(
                    select(SorRelationIntentModel)
                    .where(
                        SorRelationIntentModel.organization_id == organization_id,
                        SorRelationIntentModel.source_id == source_id,
                        SorRelationIntentModel.origin_record_id == origin_record_id,
                        SorRelationIntentModel.deleted.is_(False),
                    )
                    .with_for_update()
                )
            ).all()
        )
        by_external_id = {row.external_relation_id: row for row in current}
        stats = SorRelationshipResolutionStats()
        for draft in intents:
            _validate_intent(draft)
            row = by_external_id.get(draft.external_relation_id)
            if row is None:
                row = await self._get_by_external_id(
                    organization_id=organization_id,
                    source_id=source_id,
                    external_relation_id=draft.external_relation_id,
                )
            if row is None:
                await self.session.execute(
                    pg_insert(SorRelationIntentModel)
                    .values(
                        organization_id=organization_id,
                        source_id=source_id,
                        origin_record_id=origin_record_id,
                        **_intent_values(draft),
                        state=SorRelationIntentState.PENDING,
                    )
                    .on_conflict_do_nothing()
                )
                row = await self._get_by_external_id(
                    organization_id=organization_id,
                    source_id=source_id,
                    external_relation_id=draft.external_relation_id,
                )
                if row is None:
                    raise SorProjectionError(
                        "Relationship intent could not be persisted."
                    )
            if row.origin_record_id != origin_record_id:
                raise SorProjectionError(
                    "Relationship identity is already owned by another record."
                )
            _assign_intent(row, draft)
            row.state = SorRelationIntentState.PENDING
            row.tombstoned_at = None
            stats = _add_stats(stats, await self._resolve(row))

        removed = [row for row in current if row.external_relation_id not in unique]
        for row in removed:
            await self._tombstone(row)
            stats = _add_stats(
                stats,
                SorRelationshipResolutionStats(checked=1, tombstoned=1),
            )
        await self.session.flush()
        return stats

    async def resolve_for_endpoint(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        vendor_external_id: str,
        exclude_origin_record_id: UUID | None = None,
        limit: int = 1_000,
    ) -> SorRelationshipResolutionStats:
        """Retry intents touched by one endpoint arrival, update, or tombstone."""
        _validate_limit(limit)
        query = select(SorRelationIntentModel).where(
            SorRelationIntentModel.organization_id == organization_id,
            SorRelationIntentModel.source_id == source_id,
            SorRelationIntentModel.state.in_(
                (
                    SorRelationIntentState.PENDING,
                    SorRelationIntentState.RESOLVED,
                )
            ),
            SorRelationIntentModel.deleted.is_(False),
            or_(
                (
                    SorRelationIntentModel.from_vendor_object_key
                    == vendor_object_key
                )
                & (
                    SorRelationIntentModel.from_vendor_external_id
                    == vendor_external_id
                ),
                (SorRelationIntentModel.to_vendor_object_key == vendor_object_key)
                & (
                    SorRelationIntentModel.to_vendor_external_id
                    == vendor_external_id
                ),
            ),
        )
        if exclude_origin_record_id is not None:
            query = query.where(
                SorRelationIntentModel.origin_record_id != exclude_origin_record_id
            )
        rows = list(
            (
                await self.session.scalars(
                    query
                    .order_by(
                        SorRelationIntentModel.updated_at.asc(),
                        SorRelationIntentModel.id.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        return await self._resolve_rows(rows)

    async def resolve_pending_for_source(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        limit: int = 1_000,
    ) -> SorRelationshipResolutionStats:
        """Run the common post-sync retry pass without vendor-specific queries."""
        _validate_limit(limit)
        rows = list(
            (
                await self.session.scalars(
                    select(SorRelationIntentModel)
                    .where(
                        SorRelationIntentModel.organization_id == organization_id,
                        SorRelationIntentModel.source_id == source_id,
                        SorRelationIntentModel.state == SorRelationIntentState.PENDING,
                        SorRelationIntentModel.deleted.is_(False),
                    )
                    .order_by(
                        SorRelationIntentModel.updated_at.asc(),
                        SorRelationIntentModel.id.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        return await self._resolve_rows(rows)

    async def resolve_pending(
        self,
        *,
        limit: int = 1_000,
    ) -> SorRelationshipResolutionStats:
        """Retry a bounded, throttled batch for the trusted platform worker."""
        _validate_limit(limit)
        retry_before = datetime.now(timezone.utc) - _PENDING_RETRY_INTERVAL
        rows = list(
            (
                await self.session.scalars(
                    select(SorRelationIntentModel)
                    .where(
                        SorRelationIntentModel.state
                        == SorRelationIntentState.PENDING,
                        SorRelationIntentModel.deleted.is_(False),
                        or_(
                            SorRelationIntentModel.last_attempt_at.is_(None),
                            SorRelationIntentModel.last_attempt_at <= retry_before,
                        ),
                    )
                    .order_by(
                        SorRelationIntentModel.updated_at.asc(),
                        SorRelationIntentModel.id.asc(),
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        return await self._resolve_rows(rows)

    async def tombstone_origin_records(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_ids: Sequence[UUID],
    ) -> int:
        """Retire intents emitted by canonical records removed from the source."""
        if not record_ids:
            return 0
        rows = list(
            (
                await self.session.scalars(
                    select(SorRelationIntentModel)
                    .where(
                        SorRelationIntentModel.organization_id == organization_id,
                        SorRelationIntentModel.source_id == source_id,
                        SorRelationIntentModel.origin_record_id.in_(tuple(record_ids)),
                        SorRelationIntentModel.state
                        != SorRelationIntentState.TOMBSTONED,
                        SorRelationIntentModel.deleted.is_(False),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            await self._tombstone(row)
        await self.session.flush()
        return len(rows)

    async def _resolve_rows(
        self,
        rows: Sequence[SorRelationIntentModel],
    ) -> SorRelationshipResolutionStats:
        stats = SorRelationshipResolutionStats()
        for row in rows:
            stats = _add_stats(stats, await self._resolve(row))
        await self.session.flush()
        return stats

    async def _resolve(
        self,
        row: SorRelationIntentModel,
    ) -> SorRelationshipResolutionStats:
        row.resolution_attempts += 1
        row.last_attempt_at = datetime.now(timezone.utc)
        from_record = await self.records.get_record_by_identity(
            organization_id=row.organization_id,
            source_id=row.source_id,
            vendor_object_key=row.from_vendor_object_key,
            vendor_external_id=row.from_vendor_external_id,
        )
        to_record = await self.records.get_record_by_identity(
            organization_id=row.organization_id,
            source_id=row.source_id,
            vendor_object_key=row.to_vendor_object_key,
            vendor_external_id=row.to_vendor_external_id,
        )
        if (
            from_record is None
            or to_record is None
            or from_record.tombstoned_at is not None
            or to_record.tombstoned_at is not None
        ):
            row.state = SorRelationIntentState.PENDING
            row.last_error_code = "ENDPOINT_MISSING"
            await self._tombstone_edge(row)
            return SorRelationshipResolutionStats(checked=1, pending=1)

        now = datetime.now(timezone.utc)
        await self.session.execute(
            pg_insert(SorRecordRelationModel)
            .values(
                organization_id=row.organization_id,
                source_id=row.source_id,
                from_record_id=from_record.id,
                to_record_id=to_record.id,
                canonical_relation_kind=row.canonical_relation_kind,
                native_relation_kind=row.native_relation_kind,
                external_relation_id=row.external_relation_id,
                source_revision=row.source_revision,
                tombstoned_at=None,
            )
            .on_conflict_do_nothing()
        )
        edge = await self.session.scalar(
            select(SorRecordRelationModel)
            .where(
                SorRecordRelationModel.organization_id == row.organization_id,
                SorRecordRelationModel.source_id == row.source_id,
                SorRecordRelationModel.external_relation_id
                == row.external_relation_id,
                SorRecordRelationModel.deleted.is_(False),
            )
            .with_for_update()
        )
        if edge is None:
            edge = await self.session.scalar(
                select(SorRecordRelationModel)
                .where(
                    SorRecordRelationModel.organization_id == row.organization_id,
                    SorRecordRelationModel.source_id == row.source_id,
                    SorRecordRelationModel.from_record_id == from_record.id,
                    SorRecordRelationModel.to_record_id == to_record.id,
                    SorRecordRelationModel.canonical_relation_kind
                    == row.canonical_relation_kind,
                    SorRecordRelationModel.native_relation_kind
                    == row.native_relation_kind,
                    SorRecordRelationModel.deleted.is_(False),
                )
                .with_for_update()
            )
        if edge is None:
            raise SorProjectionError("Relationship edge could not be materialized.")
        edge.from_record_id = from_record.id
        edge.to_record_id = to_record.id
        edge.canonical_relation_kind = row.canonical_relation_kind
        edge.native_relation_kind = row.native_relation_kind
        edge.external_relation_id = row.external_relation_id
        edge.source_revision = row.source_revision
        edge.tombstoned_at = None
        edge.updated_at = now
        row.state = SorRelationIntentState.RESOLVED
        row.last_error_code = None
        row.tombstoned_at = None
        return SorRelationshipResolutionStats(checked=1, resolved=1)

    async def _tombstone(self, row: SorRelationIntentModel) -> None:
        row.state = SorRelationIntentState.TOMBSTONED
        row.tombstoned_at = datetime.now(timezone.utc)
        row.last_error_code = None
        await self._tombstone_edge(row)

    async def _tombstone_edge(self, row: SorRelationIntentModel) -> None:
        now = datetime.now(timezone.utc)
        await self.session.execute(
            update(SorRecordRelationModel)
            .where(
                SorRecordRelationModel.organization_id == row.organization_id,
                SorRecordRelationModel.source_id == row.source_id,
                SorRecordRelationModel.external_relation_id
                == row.external_relation_id,
                SorRecordRelationModel.tombstoned_at.is_(None),
                SorRecordRelationModel.deleted.is_(False),
            )
            .values(tombstoned_at=now, updated_at=now)
        )

    async def _get_by_external_id(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        external_relation_id: str,
    ) -> SorRelationIntentModel | None:
        return await self.session.scalar(
            select(SorRelationIntentModel)
            .where(
                SorRelationIntentModel.organization_id == organization_id,
                SorRelationIntentModel.source_id == source_id,
                SorRelationIntentModel.external_relation_id
                == external_relation_id,
                SorRelationIntentModel.deleted.is_(False),
            )
            .with_for_update()
        )


def relationship_external_id(*parts: object) -> str:
    """Build a bounded stable identity without exposing endpoint values in indexes."""
    identity = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"eylo:{digest}"


def _validate_intent(intent: SorRelationIntentDraft) -> None:
    bounds = (
        (intent.from_vendor_object_key, 160),
        (intent.from_vendor_external_id, 512),
        (intent.to_vendor_object_key, 160),
        (intent.to_vendor_external_id, 512),
        (intent.canonical_relation_kind, 96),
        (intent.native_relation_kind, 160),
        (intent.external_relation_id, 512),
    )
    if any(not value.strip() or len(value) > maximum for value, maximum in bounds):
        raise SorProjectionError("Relationship intent contains an invalid identity.")
    if (
        intent.from_vendor_object_key == intent.to_vendor_object_key
        and intent.from_vendor_external_id == intent.to_vendor_external_id
    ):
        raise SorProjectionError("Relationship intent endpoints must be different.")
    if intent.source_revision is not None and len(intent.source_revision) > 512:
        raise SorProjectionError("Relationship source revision is too large.")


def _intent_values(intent: SorRelationIntentDraft) -> dict[str, object]:
    return {
        "from_vendor_object_key": intent.from_vendor_object_key,
        "from_vendor_external_id": intent.from_vendor_external_id,
        "to_vendor_object_key": intent.to_vendor_object_key,
        "to_vendor_external_id": intent.to_vendor_external_id,
        "canonical_relation_kind": intent.canonical_relation_kind,
        "native_relation_kind": intent.native_relation_kind,
        "external_relation_id": intent.external_relation_id,
        "source_revision": intent.source_revision,
    }


def _assign_intent(
    row: SorRelationIntentModel,
    intent: SorRelationIntentDraft,
) -> None:
    for field, value in _intent_values(intent).items():
        setattr(row, field, value)


def _add_stats(
    left: SorRelationshipResolutionStats,
    right: SorRelationshipResolutionStats,
) -> SorRelationshipResolutionStats:
    return SorRelationshipResolutionStats(
        checked=left.checked + right.checked,
        resolved=left.resolved + right.resolved,
        pending=left.pending + right.pending,
        tombstoned=left.tombstoned + right.tombstoned,
    )


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 10_000:
        raise ValueError("Relationship resolution limit must be between 1 and 10000.")


__all__ = [
    "SorRelationshipResolutionStats",
    "SorRelationshipService",
    "relationship_external_id",
]
