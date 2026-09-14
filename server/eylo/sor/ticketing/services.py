"""Canonical ticketing projection policy independent of vendor payloads."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import (
    SorProfileRecordModel,
    SorRecordModel,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorProjectionError

from .contracts import (
    TicketingComment,
    TicketingCycle,
    TicketingEntityKind,
    TicketingIssue,
    TicketingIssueRelation,
    TicketingLabel,
    TicketingProject,
    TicketingRelationKind,
    TicketingUser,
    TicketingWorkflowState,
)
from .models import (
    TicketingCommentModel,
    TicketingCycleModel,
    TicketingIssueModel,
    TicketingIssueRelationModel,
    TicketingLabelModel,
    TicketingProjectModel,
    TicketingUserModel,
    TicketingWorkflowStateModel,
)

TicketingRecordModel = TypeVar("TicketingRecordModel", bound=SorProfileRecordModel)


class TicketingProjectionService:
    """Persist typed ticketing fields beside one shared source identity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = SorRepository(session)

    async def upsert_issue(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        issue: TicketingIssue,
    ) -> TicketingIssueModel:
        """Replace one issue extension only after exact record ownership checks."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.ISSUE,
            vendor_external_id=issue.external_id,
        )
        _validate_issue(issue)

        row = await self._get_extension(
            TicketingIssueModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "key": issue.key,
            "title": issue.title,
            "normalized_description": issue.normalized_description,
            "source_description": issue.source_description,
            "issue_type": issue.issue_type,
            "native_status": issue.native_status,
            "normalized_status": (
                issue.normalized_status.value
                if issue.normalized_status is not None
                else None
            ),
            "priority": issue.priority,
            "project_external_id": issue.project_external_id,
            "team_external_id": issue.team_external_id,
            "assignee_external_id": issue.assignee_external_id,
            "reporter_external_id": issue.reporter_external_id,
            "estimate": issue.estimate,
            "label_external_ids": list(issue.label_external_ids),
            "parent_external_id": issue.parent_external_id,
            "cycle_external_id": issue.cycle_external_id,
            "due_date": issue.due_date,
            "started_at": issue.started_at,
            "completed_at": issue.completed_at,
            "cancelled_at": issue.cancelled_at,
        }
        if row is None:
            row = TicketingIssueModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.ISSUE.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(
            record,
            issue.key,
            issue.title,
            issue.normalized_description,
            issue.native_status,
            issue.priority,
        )
        await self.session.flush()
        return row

    async def upsert_project(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        project: TicketingProject,
    ) -> TicketingProjectModel:
        """Persist a canonical ticketing project for one exact shared record."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.PROJECT,
            vendor_external_id=project.external_id,
        )
        _validate_project(project)
        row = await self._get_extension(
            TicketingProjectModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "key": project.key,
            "name": project.name,
            "description": project.description,
        }
        if row is None:
            row = TicketingProjectModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.PROJECT.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(record, project.key, project.name, project.description)
        await self.session.flush()
        return row

    async def upsert_workflow_state(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        workflow_state: TicketingWorkflowState,
    ) -> TicketingWorkflowStateModel:
        """Persist one native workflow state plus its normalized category."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.WORKFLOW_STATE,
            vendor_external_id=workflow_state.external_id,
        )
        _validate_workflow_state(workflow_state)
        row = await self._get_extension(
            TicketingWorkflowStateModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "name": workflow_state.name,
            "native_category": workflow_state.native_category,
            "normalized_category": (
                workflow_state.normalized_category.value
                if workflow_state.normalized_category is not None
                else None
            ),
            "display_order": workflow_state.order,
        }
        if row is None:
            row = TicketingWorkflowStateModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.WORKFLOW_STATE.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(
            record,
            workflow_state.name,
            workflow_state.native_category,
            workflow_state.normalized_category,
        )
        await self.session.flush()
        return row

    async def upsert_user(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        user: TicketingUser,
    ) -> TicketingUserModel:
        """Persist one source user without granting platform membership."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.USER,
            vendor_external_id=user.external_id,
        )
        _validate_user(user)
        row = await self._get_extension(
            TicketingUserModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "name": user.name,
            "display_name": user.display_name,
            "primary_email": user.primary_email,
            "active": user.active,
            "assignable": user.assignable,
            "avatar_url": user.avatar_url,
        }
        if row is None:
            row = TicketingUserModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.USER.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(record, user.name, user.display_name, user.primary_email)
        await self.session.flush()
        return row

    async def upsert_label(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        label: TicketingLabel,
    ) -> TicketingLabelModel:
        """Persist one source label with its source-side scope and hierarchy."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.LABEL,
            vendor_external_id=label.external_id,
        )
        _validate_label(label)
        row = await self._get_extension(
            TicketingLabelModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "name": label.name,
            "description": label.description,
            "color": label.color,
            "project_external_id": label.project_external_id,
            "parent_external_id": label.parent_external_id,
            "is_group": label.is_group,
        }
        if row is None:
            row = TicketingLabelModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.LABEL.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(record, label.name, label.description)
        await self.session.flush()
        return row

    async def upsert_cycle(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        cycle: TicketingCycle,
    ) -> TicketingCycleModel:
        """Persist one source cycle, sprint, or milestone."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.CYCLE,
            vendor_external_id=cycle.external_id,
        )
        _validate_cycle(cycle)
        row = await self._get_extension(
            TicketingCycleModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "name": cycle.name,
            "number": cycle.number,
            "project_external_id": cycle.project_external_id,
            "description": cycle.description,
            "starts_at": cycle.starts_at,
            "ends_at": cycle.ends_at,
            "completed_at": cycle.completed_at,
            "active": cycle.active,
        }
        if row is None:
            row = TicketingCycleModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.CYCLE.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(record, cycle.name, cycle.description)
        await self.session.flush()
        return row

    async def upsert_comment(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        comment: TicketingComment,
    ) -> TicketingCommentModel:
        """Persist one chronological issue comment without vendor write behavior."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.COMMENT,
            vendor_external_id=comment.external_id,
        )
        _validate_comment(comment)
        row = await self._get_extension(
            TicketingCommentModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "issue_external_id": comment.issue_external_id,
            "author_external_id": comment.author_external_id,
            "normalized_text": comment.normalized_text,
            "source_body": comment.source_body,
            "source_created_at": comment.created_at,
            "source_updated_at": comment.updated_at,
        }
        if row is None:
            row = TicketingCommentModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.COMMENT.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(record, comment.normalized_text, comment.author_external_id)
        await self.session.flush()
        return row

    async def upsert_relation(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        relation: TicketingIssueRelation,
    ) -> TicketingIssueRelationModel:
        """Persist one typed relation; the shared resolver owns its canonical edge."""
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=TicketingEntityKind.RELATION,
            vendor_external_id=relation.external_id,
        )
        _validate_relation(relation)
        row = await self._get_extension(
            TicketingIssueRelationModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
        )
        values: dict[str, object] = {
            "issue_vendor_object_key": relation.issue_vendor_object_key,
            "from_issue_external_id": relation.from_issue_external_id,
            "to_issue_external_id": relation.to_issue_external_id,
            "canonical_relation_kind": relation.canonical_kind.value,
            "native_relation_kind": relation.native_kind,
        }
        if row is None:
            row = TicketingIssueRelationModel(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.TICKETING,
                canonical_entity_kind=TicketingEntityKind.RELATION.value,
                **values,
            )
            self.session.add(row)
        else:
            _assign(row, values)
        _update_search(
            record,
            relation.from_issue_external_id,
            relation.to_issue_external_id,
            relation.canonical_kind.value,
            relation.native_kind,
        )
        await self.session.flush()
        return row

    async def _require_record(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: TicketingEntityKind,
        vendor_external_id: str,
    ) -> SorRecordModel:
        record = await self.records.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            for_update=True,
        )
        if record is None:
            raise SorProjectionError("Canonical source record not found.")
        if (
            record.profile is not SorProfile.TICKETING
            or record.canonical_entity_kind != entity_kind.value
            or record.vendor_external_id != vendor_external_id
        ):
            raise SorProjectionError(
                "Ticketing value does not match its canonical source identity."
            )
        return record

    async def _get_extension(
        self,
        model: type[TicketingRecordModel],
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
    ) -> TicketingRecordModel | None:
        return await self.session.scalar(
            select(model).where(
                model.organization_id == organization_id,
                model.source_id == source_id,
                model.record_id == record_id,
                model.deleted.is_(False),
            )
        )


def _validate_issue(issue: TicketingIssue) -> None:
    _validate_required(issue.external_id, maximum=512, field="issue external ID")
    _validate_optional(issue.key, maximum=320, field="issue key")
    _validate_required(issue.title, maximum=1_000_000, field="issue title")
    _validate_optional(
        issue.normalized_description,
        maximum=1_000_000,
        field="issue description",
    )
    _validate_optional(issue.issue_type, maximum=160, field="issue type")
    _validate_optional(issue.native_status, maximum=160, field="issue status")
    _validate_optional(
        issue.normalized_status,
        maximum=96,
        field="normalized issue status",
    )
    _validate_optional(issue.priority, maximum=96, field="issue priority")
    _validate_optional(
        issue.project_external_id,
        maximum=512,
        field="issue project ID",
    )
    _validate_optional(
        issue.team_external_id,
        maximum=512,
        field="issue team ID",
    )
    _validate_optional(
        issue.assignee_external_id,
        maximum=512,
        field="issue assignee ID",
    )
    _validate_optional(
        issue.reporter_external_id,
        maximum=512,
        field="issue reporter ID",
    )
    _validate_optional(
        issue.parent_external_id,
        maximum=512,
        field="issue parent ID",
    )
    if issue.parent_external_id == issue.external_id:
        raise SorProjectionError("Ticketing issue cannot be its own parent.")
    _validate_optional(
        issue.cycle_external_id,
        maximum=512,
        field="issue cycle ID",
    )
    if issue.estimate is not None and not issue.estimate.is_finite():
        raise SorProjectionError("Ticketing issue estimate must be finite.")
    for value, field_name in (
        (issue.started_at, "issue started timestamp"),
        (issue.completed_at, "issue completed timestamp"),
        (issue.cancelled_at, "issue cancelled timestamp"),
    ):
        if value is not None:
            _validate_aware(value, field=field_name)
    if len(issue.label_external_ids) > 256 or any(
        not value or len(value) > 512 for value in issue.label_external_ids
    ):
        raise SorProjectionError("Ticketing issue labels are invalid.")
    if len(set(issue.label_external_ids)) != len(issue.label_external_ids):
        raise SorProjectionError("Ticketing issue labels must be unique.")
    _validate_json(
        issue.source_description,
        field="issue source description",
    )


def _validate_project(project: TicketingProject) -> None:
    _validate_required(project.external_id, maximum=512, field="project external ID")
    _validate_optional(project.key, maximum=320, field="project key")
    _validate_required(project.name, maximum=1_000_000, field="project name")
    _validate_optional(
        project.description,
        maximum=1_000_000,
        field="project description",
    )


def _validate_workflow_state(workflow_state: TicketingWorkflowState) -> None:
    _validate_required(
        workflow_state.external_id,
        maximum=512,
        field="workflow state external ID",
    )
    _validate_required(
        workflow_state.name,
        maximum=1_000_000,
        field="workflow state name",
    )
    _validate_optional(
        workflow_state.native_category,
        maximum=160,
        field="workflow state native category",
    )
    _validate_optional(
        workflow_state.normalized_category,
        maximum=96,
        field="workflow state normalized category",
    )


def _validate_user(user: TicketingUser) -> None:
    _validate_required(user.external_id, maximum=512, field="user external ID")
    _validate_required(user.name, maximum=1_000_000, field="user name")
    _validate_optional(user.display_name, maximum=1_000_000, field="display name")
    _validate_optional(user.primary_email, maximum=1024, field="user email")
    _validate_optional(user.avatar_url, maximum=1_000_000, field="user avatar URL")
    _validate_optional(user.source_url, maximum=1_000_000, field="user source URL")
    if not isinstance(user.active, bool):
        raise SorProjectionError("Ticketing user active flag is invalid.")
    if user.assignable is not None and not isinstance(user.assignable, bool):
        raise SorProjectionError("Ticketing user assignable flag is invalid.")


def _validate_label(label: TicketingLabel) -> None:
    _validate_required(label.external_id, maximum=512, field="label external ID")
    _validate_required(label.name, maximum=1_000_000, field="label name")
    _validate_optional(label.description, maximum=1_000_000, field="label description")
    _validate_optional(label.color, maximum=160, field="label color")
    _validate_optional(
        label.project_external_id,
        maximum=512,
        field="label project ID",
    )
    _validate_optional(
        label.parent_external_id,
        maximum=512,
        field="label parent ID",
    )
    if label.parent_external_id == label.external_id:
        raise SorProjectionError("Ticketing label cannot be its own parent.")
    if not isinstance(label.is_group, bool):
        raise SorProjectionError("Ticketing label group flag is invalid.")


def _validate_cycle(cycle: TicketingCycle) -> None:
    _validate_required(cycle.external_id, maximum=512, field="cycle external ID")
    _validate_required(cycle.name, maximum=1_000_000, field="cycle name")
    _validate_optional(
        cycle.project_external_id,
        maximum=512,
        field="cycle project ID",
    )
    _validate_optional(cycle.description, maximum=1_000_000, field="cycle description")
    if cycle.number is not None and cycle.number < 0:
        raise SorProjectionError("Ticketing cycle number cannot be negative.")
    for value, field_name in (
        (cycle.starts_at, "cycle start timestamp"),
        (cycle.ends_at, "cycle end timestamp"),
        (cycle.completed_at, "cycle completion timestamp"),
    ):
        if value is not None:
            _validate_aware(value, field=field_name)
    if (
        cycle.starts_at is not None
        and cycle.ends_at is not None
        and cycle.starts_at > cycle.ends_at
    ):
        raise SorProjectionError("Ticketing cycle cannot end before it starts.")
    if (
        cycle.starts_at is not None
        and cycle.completed_at is not None
        and cycle.completed_at < cycle.starts_at
    ):
        raise SorProjectionError("Ticketing cycle cannot complete before it starts.")
    if cycle.active is not None and not isinstance(cycle.active, bool):
        raise SorProjectionError("Ticketing cycle active flag is invalid.")


def _validate_comment(comment: TicketingComment) -> None:
    _validate_required(comment.external_id, maximum=512, field="comment external ID")
    _validate_required(
        comment.issue_external_id,
        maximum=512,
        field="comment issue ID",
    )
    _validate_optional(
        comment.author_external_id,
        maximum=512,
        field="comment author ID",
    )
    _validate_required(
        comment.normalized_text,
        maximum=1_000_000,
        field="comment text",
    )
    _validate_aware(comment.created_at, field="comment created timestamp")
    if comment.updated_at is not None:
        _validate_aware(comment.updated_at, field="comment updated timestamp")
    _validate_json(comment.source_body, field="comment source body")


def _validate_relation(relation: TicketingIssueRelation) -> None:
    _validate_required(
        relation.external_id,
        maximum=512,
        field="relation external ID",
    )
    _validate_required(
        relation.issue_vendor_object_key,
        maximum=160,
        field="relation issue object key",
    )
    _validate_required(
        relation.from_issue_external_id,
        maximum=512,
        field="relation source issue ID",
    )
    _validate_required(
        relation.to_issue_external_id,
        maximum=512,
        field="relation target issue ID",
    )
    if relation.from_issue_external_id == relation.to_issue_external_id:
        raise SorProjectionError("Ticketing relation endpoints must be different.")
    if not isinstance(relation.canonical_kind, TicketingRelationKind):
        raise SorProjectionError("Ticketing relation kind is invalid.")
    _validate_required(
        relation.native_kind,
        maximum=160,
        field="relation native kind",
    )
    _validate_optional(
        relation.source_revision,
        maximum=512,
        field="relation source revision",
    )


def _validate_required(value: str, *, maximum: int, field: str) -> None:
    if not value or len(value) > maximum:
        raise SorProjectionError(f"Ticketing {field} is invalid.")


def _validate_optional(value: str | None, *, maximum: int, field: str) -> None:
    if value is not None and len(value) > maximum:
        raise SorProjectionError(f"Ticketing {field} is too large.")


def _validate_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SorProjectionError(f"Ticketing {field} must be timezone-aware.")


def _validate_json(value: object | None, *, field: str) -> None:
    if value is None:
        return
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SorProjectionError(
            f"Ticketing {field} is not JSON serializable."
        ) from error
    if len(encoded) > 1_048_576:
        raise SorProjectionError(f"Ticketing {field} is too large.")


def _assign(row: SorProfileRecordModel, values: dict[str, object]) -> None:
    for field, value in values.items():
        setattr(row, field, value)


def _update_search(record: SorRecordModel, *values: str | None) -> None:
    record.search_text = " ".join(value for value in values if value)[:1_000_000]
    record.search_vector = func.to_tsvector("simple", record.search_text)


__all__ = ["TicketingProjectionService"]
