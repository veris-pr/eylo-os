"""Typed canonical projection tables for the ticketing profile."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel
from eylo.sor.ticketing.contracts import TicketingEntityKind


class TicketingIssueModel(SorProfileRecordModel):
    """Queryable canonical issue fields independent of Jira, Linear, or GitHub."""

    __tablename__ = "sor_ticketing_issues"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.ISSUE,
        ),
        CheckConstraint(
            "source_description IS NULL OR "
            "octet_length(source_description::text) <= 1048576",
            name="ck_sor_ticketing_issues_source_description",
        ),
        CheckConstraint(
            "cardinality(label_external_ids) <= 256",
            name="ck_sor_ticketing_issues_labels",
        ),
        Index(
            "ix_sor_ticketing_issues_source_status",
            "source_id",
            "normalized_status",
        ),
        Index(
            "ix_sor_ticketing_issues_source_project",
            "source_id",
            "project_external_id",
        ),
        Index(
            "ix_sor_ticketing_issues_source_team",
            "source_id",
            "team_external_id",
        ),
    )

    key: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_description: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    issue_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    native_status: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_status: Mapped[str | None] = mapped_column(String(96), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(96), nullable=True)
    project_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    team_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    assignee_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reporter_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    estimate: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    label_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    parent_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cycle_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TicketingProjectModel(SorProfileRecordModel):
    """Canonical project, team, or repository used to scope issues."""

    __tablename__ = "sor_ticketing_projects"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.PROJECT,
        ),
        Index("ix_sor_ticketing_projects_source_name", "source_id", "name"),
    )

    key: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketingWorkflowStateModel(SorProfileRecordModel):
    """Source-native workflow state plus Eylo's bounded category."""

    __tablename__ = "sor_ticketing_workflow_states"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.WORKFLOW_STATE,
        ),
        Index(
            "ix_sor_ticketing_workflow_states_source_category",
            "source_id",
            "normalized_category",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    native_category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_category: Mapped[str | None] = mapped_column(String(96), nullable=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TicketingUserModel(SorProfileRecordModel):
    """Queryable source user fields used by issue and comment references."""

    __tablename__ = "sor_ticketing_users"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.USER,
        ),
        Index("ix_sor_ticketing_users_source_name", "source_id", "name"),
        Index(
            "ix_sor_ticketing_users_source_email",
            "source_id",
            "primary_email",
        ),
        Index(
            "ix_sor_ticketing_users_source_active",
            "source_id",
            "active",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_email: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False)
    assignable: Mapped[bool | None] = mapped_column(nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class TicketingLabelModel(SorProfileRecordModel):
    """Queryable classification label independent of vendor identity shape."""

    __tablename__ = "sor_ticketing_labels"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.LABEL,
        ),
        Index("ix_sor_ticketing_labels_source_name", "source_id", "name"),
        Index(
            "ix_sor_ticketing_labels_source_project",
            "source_id",
            "project_external_id",
        ),
        Index(
            "ix_sor_ticketing_labels_source_parent",
            "source_id",
            "parent_external_id",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(160), nullable=True)
    project_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parent_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_group: Mapped[bool] = mapped_column(nullable=False)


class TicketingCycleModel(SorProfileRecordModel):
    """Queryable sprint, cycle, or milestone fields used by issue references."""

    __tablename__ = "sor_ticketing_cycles"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.CYCLE,
        ),
        Index("ix_sor_ticketing_cycles_source_name", "source_id", "name"),
        Index(
            "ix_sor_ticketing_cycles_source_project",
            "source_id",
            "project_external_id",
        ),
        Index(
            "ix_sor_ticketing_cycles_source_dates",
            "source_id",
            "starts_at",
            "ends_at",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool | None] = mapped_column(nullable=True)


class TicketingCommentModel(SorProfileRecordModel):
    """Chronological normalized issue comment with bounded source structure."""

    __tablename__ = "sor_ticketing_comments"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.COMMENT,
        ),
        CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_ticketing_comments_source_body",
        ),
        Index(
            "ix_sor_ticketing_comments_source_issue_created",
            "source_id",
            "issue_external_id",
            "source_created_at",
        ),
    )

    issue_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    author_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_body: Mapped[dict | list | str | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TicketingIssueRelationModel(SorProfileRecordModel):
    """Typed issue endpoints retained even before both records are projected."""

    __tablename__ = "sor_ticketing_issue_relations"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.TICKETING,
            entity_kind=TicketingEntityKind.RELATION,
        ),
        CheckConstraint(
            "from_issue_external_id <> to_issue_external_id",
            name="ck_sor_ticketing_issue_relations_distinct_issues",
        ),
        CheckConstraint(
            "canonical_relation_kind IN "
            "('PARENT', 'CHILD', 'BLOCKS', 'BLOCKED_BY', "
            "'RELATED', 'DUPLICATE')",
            name="ck_sor_ticketing_issue_relations_kind",
        ),
        Index(
            "ix_sor_ticketing_issue_relations_source_from",
            "source_id",
            "issue_vendor_object_key",
            "from_issue_external_id",
        ),
        Index(
            "ix_sor_ticketing_issue_relations_source_to",
            "source_id",
            "issue_vendor_object_key",
            "to_issue_external_id",
        ),
        Index(
            "ix_sor_ticketing_issue_relations_source_kind",
            "source_id",
            "canonical_relation_kind",
        ),
    )

    issue_vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    from_issue_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    to_issue_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_relation_kind: Mapped[str] = mapped_column(String(96), nullable=False)
    native_relation_kind: Mapped[str] = mapped_column(String(160), nullable=False)


__all__ = [
    "TicketingCommentModel",
    "TicketingCycleModel",
    "TicketingIssueRelationModel",
    "TicketingIssueModel",
    "TicketingLabelModel",
    "TicketingProjectModel",
    "TicketingUserModel",
    "TicketingWorkflowStateModel",
]
