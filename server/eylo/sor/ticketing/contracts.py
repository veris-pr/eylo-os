"""Typed canonical issue records produced by ticketing adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable

from eylo.sor.shared.contracts import SorExternalRecord, SorLifecycleAdapter


@dataclass(frozen=True, slots=True)
class TicketingIssue:
    external_id: str
    key: str | None
    title: str
    normalized_description: str | None
    source_description: object | None
    issue_type: str | None
    native_status: str | None
    normalized_status: str | None
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
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TicketingProject:
    external_id: str
    key: str | None
    name: str
    description: str | None
    source_url: str | None


@dataclass(frozen=True, slots=True)
class TicketingWorkflowState:
    external_id: str
    name: str
    native_category: str | None
    normalized_category: str | None
    order: int | None


@dataclass(frozen=True, slots=True)
class TicketingUser:
    """One source user that may own, report, or receive ticketing work."""

    external_id: str
    name: str
    display_name: str | None
    primary_email: str | None
    active: bool
    assignable: bool | None
    avatar_url: str | None
    source_url: str | None


@dataclass(frozen=True, slots=True)
class TicketingLabel:
    """One source classification label with optional hierarchy and scope."""

    external_id: str
    name: str
    description: str | None
    color: str | None
    project_external_id: str | None
    parent_external_id: str | None
    is_group: bool


@dataclass(frozen=True, slots=True)
class TicketingCycle:
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


@dataclass(frozen=True, slots=True)
class TicketingComment:
    external_id: str
    issue_external_id: str
    author_external_id: str | None
    normalized_text: str
    source_body: object | None
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


@dataclass(frozen=True, slots=True)
class TicketingIssueRelation:
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

    def normalize_issue(self, record: SorExternalRecord) -> TicketingIssue: ...

    def normalize_project(self, record: SorExternalRecord) -> TicketingProject: ...

    def normalize_workflow_state(
        self,
        record: SorExternalRecord,
    ) -> TicketingWorkflowState: ...

    def normalize_user(self, record: SorExternalRecord) -> TicketingUser: ...

    def normalize_label(self, record: SorExternalRecord) -> TicketingLabel: ...

    def normalize_cycle(self, record: SorExternalRecord) -> TicketingCycle: ...

    def normalize_comment(self, record: SorExternalRecord) -> TicketingComment: ...

    def normalize_relation(
        self,
        record: SorExternalRecord,
    ) -> TicketingIssueRelation: ...


__all__ = [
    "TicketingAdapter",
    "TicketingComment",
    "TicketingCycle",
    "TicketingIssue",
    "TicketingIssueRelation",
    "TicketingLabel",
    "TicketingProject",
    "TicketingRelationKind",
    "TicketingUser",
    "TicketingWorkflowState",
]
