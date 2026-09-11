"""Typed canonical issue records produced by ticketing adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from eylo.sor.shared.contracts import (
    SorCanonicalPayload,
    SorCanonicalRecord,
    SorCommandPayload,
    SorExternalRecord,
    SorLifecycleAdapter,
    SorMappedFieldsCommandPayload,
)
from eylo.sor.shared.json_values import SorJsonValue


class TicketingWorkState(str, Enum):
    """Bounded platform state for issues and workflow categories."""

    UNSTARTED = "UNSTARTED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "TicketingWorkState | None":
        if value is None:
            return None
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class TicketingEntityKind(StrEnum):
    """Stable canonical issue-tracking entity vocabulary."""

    ISSUE = "issue"
    PROJECT = "project"
    WORKFLOW_STATE = "workflow_state"
    USER = "user"
    LABEL = "label"
    CYCLE = "cycle"
    COMMENT = "comment"
    ATTACHMENT = "attachment"
    RELATION = "relation"


class TicketingToolName(StrEnum):
    """Stable model-visible issue-tracking tool names."""

    SEARCH = "issue_search"
    GET = "issue_get"
    GET_HISTORY = "issue_get_history"
    LIST_PROJECTS = "issue_list_projects"
    LIST_WORKFLOW_STATES = "issue_list_workflow_states"
    DESCRIBE_FIELDS = "issue_describe_fields"
    CREATE = "issue_create"
    UPDATE = "issue_update"
    TRANSITION = "issue_transition"
    ASSIGN = "issue_assign"
    COMMENT = "issue_comment"
    LINK = "issue_link"
    ADD_LABEL = "issue_add_label"
    REMOVE_LABEL = "issue_remove_label"


class TicketingIssue(SorCanonicalRecord):
    external_id: str
    key: str | None
    title: str
    normalized_description: str | None
    source_description: SorJsonValue = Field(repr=False, exclude=True)
    issue_type: str | None
    native_status: str | None
    normalized_status: TicketingWorkState | None
    priority: str | None
    project_external_id: str | None
    team_external_id: str | None
    assignee_external_id: str | None
    reporter_external_id: str | None
    estimate: Decimal | None
    label_external_ids: tuple[str, ...]
    parent_external_id: str | None
    cycle_external_id: str | None
    due_date: date | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class TicketingProject(SorCanonicalRecord):
    external_id: str
    key: str | None
    name: str
    description: str | None
    source_url: str | None


class TicketingWorkflowState(SorCanonicalRecord):
    external_id: str
    name: str
    native_category: str | None
    normalized_category: TicketingWorkState | None
    order: int | None


class TicketingUser(SorCanonicalRecord):
    """One source user that may own, report, or receive ticketing work."""

    external_id: str
    name: str
    display_name: str | None
    primary_email: str | None
    active: bool
    assignable: bool | None
    avatar_url: str | None
    source_url: str | None


class TicketingLabel(SorCanonicalRecord):
    """One source classification label with optional hierarchy and scope."""

    external_id: str
    name: str
    description: str | None
    color: str | None
    project_external_id: str | None
    parent_external_id: str | None
    is_group: bool


class TicketingCycle(SorCanonicalRecord):
    """One sprint, cycle, or milestone used to time-box ticketing work."""

    external_id: str
    name: str
    number: int | None
    project_external_id: str | None
    description: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    completed_at: datetime | None
    active: bool | None


class TicketingComment(SorCanonicalRecord):
    external_id: str
    issue_external_id: str
    author_external_id: str | None
    normalized_text: str
    source_body: SorJsonValue = Field(repr=False, exclude=True)
    created_at: datetime
    updated_at: datetime | None


class TicketingRelationKind(str, Enum):
    """Stable issue relationship vocabulary shared across ticketing vendors."""

    PARENT = "PARENT"
    CHILD = "CHILD"
    BLOCKS = "BLOCKS"
    BLOCKED_BY = "BLOCKED_BY"
    RELATED = "RELATED"
    DUPLICATE = "DUPLICATE"


class TicketingMappedFieldsCommandPayload(SorMappedFieldsCommandPayload):
    """Mapped issue fields for one create or update command."""


class TicketingTransitionCommandPayload(SorCommandPayload):
    """One exact workflow state selected for an issue transition."""

    workflow_state_external_id: str = Field(min_length=1, max_length=320)


class TicketingAssignCommandPayload(SorCommandPayload):
    """One source user assignment; null explicitly unassigns the issue."""

    assignee_external_id: str | None


class TicketingCommentCommandPayload(SorCommandPayload):
    """One plain-text issue comment."""

    text: str = Field(min_length=1, max_length=100_000)


class TicketingLinkCommandPayload(SorCommandPayload):
    """One typed relationship between the target and another issue."""

    related_issue_external_id: str = Field(min_length=1, max_length=320)
    relation_kind: TicketingRelationKind


class TicketingLabelCommandPayload(SorCommandPayload):
    """One exact source label to add or remove."""

    label_external_id: str = Field(min_length=1, max_length=320)


TICKETING_COMMAND_PAYLOAD_TYPES: Mapping[
    TicketingToolName, type[SorCommandPayload]
] = {
    TicketingToolName.CREATE: TicketingMappedFieldsCommandPayload,
    TicketingToolName.UPDATE: TicketingMappedFieldsCommandPayload,
    TicketingToolName.TRANSITION: TicketingTransitionCommandPayload,
    TicketingToolName.ASSIGN: TicketingAssignCommandPayload,
    TicketingToolName.COMMENT: TicketingCommentCommandPayload,
    TicketingToolName.LINK: TicketingLinkCommandPayload,
    TicketingToolName.ADD_LABEL: TicketingLabelCommandPayload,
    TicketingToolName.REMOVE_LABEL: TicketingLabelCommandPayload,
}


class TicketingIssuePayload(SorCanonicalPayload):
    """Mapped issue fields before source identity is attached."""

    key: str | None = None
    title: str
    normalized_description: str | None = None
    source_description: SorJsonValue = None
    issue_type: str | None = None
    native_status: str | None = None
    normalized_status: TicketingWorkState | None = None
    priority: str | None = None
    project_external_id: str | None = None
    team_external_id: str | None = None
    assignee_external_id: str | None = None
    reporter_external_id: str | None = None
    estimate: Decimal | None = None
    label_external_ids: tuple[str, ...] = ()
    parent_external_id: str | None = None
    cycle_external_id: str | None = None
    due_date: date | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


class TicketingProjectPayload(SorCanonicalPayload):
    key: str | None = None
    name: str
    description: str | None = None


class TicketingWorkflowStatePayload(SorCanonicalPayload):
    name: str
    native_category: str | None = None
    normalized_category: TicketingWorkState | None = None
    order: int | Decimal | None = None


class TicketingUserPayload(SorCanonicalPayload):
    name: str
    display_name: str | None = None
    primary_email: str | None = None
    active: bool
    assignable: bool | None = None
    avatar_url: str | None = None


class TicketingLabelPayload(SorCanonicalPayload):
    name: str
    description: str | None = None
    color: str | None = None
    project_external_id: str | None = None
    parent_external_id: str | None = None
    is_group: bool


class TicketingCyclePayload(SorCanonicalPayload):
    name: str | None = None
    number: int | None = None
    project_external_id: str | None = None
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    completed_at: datetime | None = None
    active: bool | None = None


class TicketingCommentPayload(SorCanonicalPayload):
    issue_external_id: str
    author_external_id: str | None = None
    normalized_text: str
    source_body: SorJsonValue = None
    created_at: datetime
    updated_at: datetime | None = None


class TicketingRelationPayload(SorCanonicalPayload):
    from_issue_external_id: str
    to_issue_external_id: str
    canonical_relation_kind: TicketingRelationKind
    native_relation_kind: str


TicketingPayload = (
    TicketingIssuePayload
    | TicketingProjectPayload
    | TicketingWorkflowStatePayload
    | TicketingUserPayload
    | TicketingLabelPayload
    | TicketingCyclePayload
    | TicketingCommentPayload
    | TicketingRelationPayload
)


TICKETING_PAYLOAD_TYPES: Mapping[TicketingEntityKind, type[SorCanonicalPayload]] = {
    TicketingEntityKind.ISSUE: TicketingIssuePayload,
    TicketingEntityKind.PROJECT: TicketingProjectPayload,
    TicketingEntityKind.WORKFLOW_STATE: TicketingWorkflowStatePayload,
    TicketingEntityKind.USER: TicketingUserPayload,
    TicketingEntityKind.LABEL: TicketingLabelPayload,
    TicketingEntityKind.CYCLE: TicketingCyclePayload,
    TicketingEntityKind.COMMENT: TicketingCommentPayload,
    TicketingEntityKind.RELATION: TicketingRelationPayload,
}


class TicketingIssueRelation(SorCanonicalRecord):
    """One vendor relation plus the exact issue stream containing its endpoints."""

    external_id: str
    issue_vendor_object_key: str
    from_issue_external_id: str
    to_issue_external_id: str
    canonical_kind: TicketingRelationKind
    native_kind: str
    source_revision: str | None


@runtime_checkable
class TicketingAdapter(SorLifecycleAdapter, Protocol):
    """Ticketing port with pure, I/O-free synchronous normalization methods."""

    def normalize_issue(
        self,
        record: SorExternalRecord,
        payload: TicketingIssuePayload,
    ) -> TicketingIssue: ...

    def normalize_project(
        self,
        record: SorExternalRecord,
        payload: TicketingProjectPayload,
    ) -> TicketingProject: ...

    def normalize_workflow_state(
        self,
        record: SorExternalRecord,
        payload: TicketingWorkflowStatePayload,
    ) -> TicketingWorkflowState: ...

    def normalize_user(
        self,
        record: SorExternalRecord,
        payload: TicketingUserPayload,
    ) -> TicketingUser: ...

    def normalize_label(
        self,
        record: SorExternalRecord,
        payload: TicketingLabelPayload,
    ) -> TicketingLabel: ...

    def normalize_cycle(
        self,
        record: SorExternalRecord,
        payload: TicketingCyclePayload,
    ) -> TicketingCycle: ...

    def normalize_comment(
        self,
        record: SorExternalRecord,
        payload: TicketingCommentPayload,
    ) -> TicketingComment: ...

    def normalize_relation(
        self,
        record: SorExternalRecord,
        payload: TicketingRelationPayload,
    ) -> TicketingIssueRelation: ...


__all__ = [
    "TICKETING_COMMAND_PAYLOAD_TYPES",
    "TICKETING_PAYLOAD_TYPES",
    "TicketingAssignCommandPayload",
    "TicketingAdapter",
    "TicketingComment",
    "TicketingCommentCommandPayload",
    "TicketingCommentPayload",
    "TicketingCycle",
    "TicketingCyclePayload",
    "TicketingEntityKind",
    "TicketingIssue",
    "TicketingIssuePayload",
    "TicketingIssueRelation",
    "TicketingLabel",
    "TicketingLabelCommandPayload",
    "TicketingLabelPayload",
    "TicketingPayload",
    "TicketingProject",
    "TicketingProjectPayload",
    "TicketingRelationPayload",
    "TicketingRelationKind",
    "TicketingLinkCommandPayload",
    "TicketingMappedFieldsCommandPayload",
    "TicketingTransitionCommandPayload",
    "TicketingToolName",
    "TicketingUser",
    "TicketingUserPayload",
    "TicketingWorkState",
    "TicketingWorkflowState",
    "TicketingWorkflowStatePayload",
]
