"""Tenant-scoped ticketing detail projections for the operator audit console."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorRecordModel, SorSourceModel
from eylo.sor.shared.reads import SorReadNotFoundError, resolve_reference_labels
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.ticketing.models import TicketingCommentModel, TicketingIssueModel

TICKETING_ISSUE_COMMENT_LIMIT = 100


class TicketingIssueCommentAudit(BaseModel):
    """One bounded, normalized comment shown beside its canonical issue."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    record_id: UUID
    author_external_id: str | None
    author_name: str | None
    text: str
    created_at: datetime
    updated_at: datetime | None
    source_url: str | None


class TicketingIssueAuditContext(BaseModel):
    """Issue-owned audit data plus the source facts needed for capability copy."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    source: SkipJsonSchema[InstanceOf[SorSourceModel]] = Field(repr=False, exclude=True)
    comments_selected: bool
    comments_truncated: bool
    comments: tuple[TicketingIssueCommentAudit, ...]


class TicketingIssueAuditService:
    """Read issue discussion without widening tenant or source authority."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def read(
        self,
        *,
        organization_id: UUID,
        record_id: UUID,
    ) -> TicketingIssueAuditContext:
        issue_record = await self.session.scalar(
            select(SorRecordModel)
            .join(
                TicketingIssueModel,
                and_(
                    TicketingIssueModel.record_id == SorRecordModel.id,
                    TicketingIssueModel.source_id == SorRecordModel.source_id,
                    TicketingIssueModel.organization_id
                    == SorRecordModel.organization_id,
                ),
            )
            .where(
                SorRecordModel.id == record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.profile == SorProfile.TICKETING,
                SorRecordModel.canonical_entity_kind == "issue",
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
                TicketingIssueModel.deleted.is_(False),
            )
        )
        if issue_record is None:
            raise SorReadNotFoundError("Ticketing issue not found.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=issue_record.source_id,
        )
        if source is None:
            raise SorReadNotFoundError("Ticketing issue source not found.")
        streams = await self.repository.list_streams(
            organization_id=organization_id,
            source_id=source.id,
        )
        comments_selected = any(
            stream.canonical_entity_kind == "comment" for stream in streams
        )
        if not comments_selected:
            return TicketingIssueAuditContext(
                source=source,
                comments_selected=False,
                comments_truncated=False,
                comments=(),
            )

        rows = (
            await self.session.execute(
                select(TicketingCommentModel, SorRecordModel)
                .join(
                    SorRecordModel,
                    and_(
                        SorRecordModel.id == TicketingCommentModel.record_id,
                        SorRecordModel.source_id == TicketingCommentModel.source_id,
                        SorRecordModel.organization_id
                        == TicketingCommentModel.organization_id,
                    ),
                )
                .where(
                    TicketingCommentModel.organization_id == organization_id,
                    TicketingCommentModel.source_id == issue_record.source_id,
                    TicketingCommentModel.issue_external_id
                    == issue_record.vendor_external_id,
                    TicketingCommentModel.deleted.is_(False),
                    SorRecordModel.profile == SorProfile.TICKETING,
                    SorRecordModel.canonical_entity_kind == "comment",
                    SorRecordModel.tombstoned_at.is_(None),
                    SorRecordModel.deleted.is_(False),
                )
                .order_by(
                    TicketingCommentModel.source_created_at.desc(),
                    SorRecordModel.id.desc(),
                )
                .limit(TICKETING_ISSUE_COMMENT_LIMIT + 1)
            )
        ).all()
        truncated = len(rows) > TICKETING_ISSUE_COMMENT_LIMIT
        selected_rows = rows[:TICKETING_ISSUE_COMMENT_LIMIT]
        author_labels = await resolve_reference_labels(
            self.session,
            organization_id=organization_id,
            reference_keys=tuple(
                (issue_record.source_id, "user", comment.author_external_id)
                for comment, _record in selected_rows
                if comment.author_external_id is not None
            ),
        )
        comments = tuple(
            TicketingIssueCommentAudit(
                record_id=record.id,
                author_external_id=comment.author_external_id,
                author_name=(
                    author_labels.get(
                        (issue_record.source_id, "user", comment.author_external_id)
                    )
                    if comment.author_external_id is not None
                    else None
                ),
                text=comment.normalized_text,
                created_at=comment.source_created_at,
                updated_at=comment.source_updated_at,
                source_url=record.source_url,
            )
            for comment, record in reversed(selected_rows)
        )
        return TicketingIssueAuditContext(
            source=source,
            comments_selected=True,
            comments_truncated=truncated,
            comments=comments,
        )


__all__ = [
    "TicketingIssueAuditContext",
    "TicketingIssueAuditService",
    "TicketingIssueCommentAudit",
]
