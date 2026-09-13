"""Jira Cloud adapter for Eylo's canonical ticketing profile."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from http import HTTPMethod, HTTPStatus
from typing import Annotated, Literal

import jwt
from jwt.exceptions import PyJWTError
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
    field_validator,
)

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.atlassian import (
    ATLASSIAN_API_ORIGIN,
    ATLASSIAN_AUTHORIZATION_PARAMS,
    ATLASSIAN_AUTHORIZATION_URL,
    ATLASSIAN_INSTANCE_HOST_SUFFIX,
    ATLASSIAN_INSTANCE_HOST_SUFFIXES,
    ATLASSIAN_TOKEN_URL,
)
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeMode,
    SorChangeStrategy,
    SorCommandRequest,
    SorCommandResult,
    SorConnectionVerification,
    SorDeletedRecord,
    SorDiscoveredField,
    SorDiscoveredObject,
    SorDiscoveredSchema,
    SorExternalRecord,
    SorExternalRecordNotFound,
    SorFieldDataType,
    SorMutationOperation,
    SorOAuthSpec,
    SorOAuthTokenRequestFormat,
    SorProfile,
    SorRecordPage,
    SorRecoveryPolicy,
    SorRelationshipRole,
    SorRelationshipTargets,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookPayloadError,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookVerificationError,
)
from eylo.sor.shared.json_values import SorJsonValue, require_json_value
from eylo.sor.ticketing.contracts import (
    TicketingAssignCommandPayload,
    TicketingComment,
    TicketingCommentCommandPayload,
    TicketingCommentPayload,
    TicketingCycle,
    TicketingCyclePayload,
    TicketingEntityKind,
    TicketingIssue,
    TicketingIssuePayload,
    TicketingIssueRelation,
    TicketingIssueWriteField,
    TicketingLabel,
    TicketingLabelCommandPayload,
    TicketingLabelPayload,
    TicketingLinkCommandPayload,
    TicketingMappedFieldsCommandPayload,
    TicketingProject,
    TicketingProjectPayload,
    TicketingRelationKind,
    TicketingRelationPayload,
    TicketingToolName,
    TicketingTransitionCommandPayload,
    TicketingUser,
    TicketingUserPayload,
    TicketingWorkState,
    TicketingWorkflowState,
    TicketingWorkflowStatePayload,
)
from eylo.sor.ticketing.vendors import jira_wire as native
from eylo.sor.ticketing.vendors.jira_webhooks import (
    JIRA_WEBHOOK_DELIVERY_HEADER,
    JIRA_WEBHOOK_FUTURE_TOLERANCE,
    JIRA_WEBHOOK_IDENTIFIER_MAX_LENGTH,
    JIRA_WEBHOOK_TIMESTAMP_MILLISECONDS,
    JiraWebhookDelivery,
    JiraWebhookDetails,
    JiraWebhookEvent,
    JiraWebhookEventFamily,
    JiraWebhookIdsRequest,
    JiraWebhookListQuery,
    JiraWebhookPage,
    JiraWebhookRegistrationRequest,
    JiraWebhookRegistrationResponse,
    JiraWebhookRenewalResponse,
    JiraWebhookWire,
    parse_jira_webhook_body,
    parse_jira_webhook_response,
)

JIRA_API_ORIGIN = ATLASSIAN_API_ORIGIN
JIRA_API_VERSION = "jira-cloud-rest-v3"
JIRA_CURSOR_VERSION = 1
JIRA_ISSUE_CURSOR_VERSION = 2
JIRA_NESTED_CURSOR_VERSION = 3
JIRA_RELATION_CURSOR_VERSION = 4
JIRA_COMMENT_CURSOR_VERSION = 5
JIRA_SPRINT_CURSOR_VERSION = 6
JIRA_RECONCILIATION_OVERLAP = timedelta(minutes=5)
JIRA_EMBEDDED_COMMENT_LIMIT = 20
JIRA_COMMENT_ISSUE_BATCH_SIZE = 10
JIRA_RELATION_ISSUE_BATCH_SIZE = 20
JIRA_SPRINT_ISSUE_BATCH_SIZE = 100
JIRA_SPRINT_SCAN_LIMIT = 25
JIRA_CURSOR_TOKEN_LIMIT = 4_096
JIRA_SPRINT_FIELD_TYPE = "com.pyxis.greenhopper.jira:gh-sprint"

READ_WORK_SCOPE = "read:jira-work"
READ_USER_SCOPE = "read:jira-user"
WRITE_SCOPE = "write:jira-work"
OFFLINE_SCOPE = "offline_access"
READ_SPRINT_SCOPE = "read:sprint:jira-software"
MANAGE_WEBHOOK_SCOPE = "manage:jira-webhook"
JIRA_WEBHOOK_LIFETIME = timedelta(days=30)
JIRA_ALL_PROJECTS_WEBHOOK_JQL = "project != EMPTY"


class JiraStream(StrEnum):
    """Closed vendor stream vocabulary owned by this adapter."""

    ISSUES = "issues"
    PROJECTS = "projects"
    WORKFLOW_STATES = "workflow_states"
    USERS = "users"
    LABELS = "labels"
    SPRINTS = "sprints"
    COMMENTS = "comments"
    ISSUE_RELATIONS = "issue_relations"


_STREAM_ENTITY = {
    JiraStream.ISSUES: TicketingEntityKind.ISSUE,
    JiraStream.PROJECTS: TicketingEntityKind.PROJECT,
    JiraStream.WORKFLOW_STATES: TicketingEntityKind.WORKFLOW_STATE,
    JiraStream.USERS: TicketingEntityKind.USER,
    JiraStream.LABELS: TicketingEntityKind.LABEL,
    JiraStream.SPRINTS: TicketingEntityKind.CYCLE,
    JiraStream.COMMENTS: TicketingEntityKind.COMMENT,
    JiraStream.ISSUE_RELATIONS: TicketingEntityKind.RELATION,
}
_RELATIONSHIP_TARGETS = {
    JiraStream.ISSUES: {
        SorRelationshipRole.PROJECT: JiraStream.PROJECTS,
        SorRelationshipRole.ASSIGNEE: JiraStream.USERS,
        SorRelationshipRole.REPORTER: JiraStream.USERS,
        SorRelationshipRole.LABEL: JiraStream.LABELS,
        SorRelationshipRole.PARENT: JiraStream.ISSUES,
        SorRelationshipRole.CYCLE: JiraStream.SPRINTS,
    },
    JiraStream.LABELS: {
        SorRelationshipRole.PROJECT: JiraStream.PROJECTS,
        SorRelationshipRole.PARENT: JiraStream.LABELS,
    },
    JiraStream.COMMENTS: {
        SorRelationshipRole.ISSUE: JiraStream.ISSUES,
        SorRelationshipRole.AUTHOR: JiraStream.USERS,
    },
    JiraStream.ISSUE_RELATIONS: {
        SorRelationshipRole.FROM_ISSUE: JiraStream.ISSUES,
        SorRelationshipRole.TO_ISSUE: JiraStream.ISSUES,
    },
}
_READ_TOOLS = frozenset(
    {
        TicketingToolName.SEARCH,
        TicketingToolName.GET,
        TicketingToolName.LIST_PROJECTS,
        TicketingToolName.LIST_WORKFLOW_STATES,
        TicketingToolName.DESCRIBE_FIELDS,
    }
)
_WRITE_TOOLS = frozenset(
    {
        TicketingToolName.CREATE,
        TicketingToolName.UPDATE,
        TicketingToolName.TRANSITION,
        TicketingToolName.ASSIGN,
        TicketingToolName.ADD_LABEL,
        TicketingToolName.REMOVE_LABEL,
        TicketingToolName.COMMENT,
        TicketingToolName.LINK,
    }
)
_TOOL_STREAMS = {
    TicketingToolName.SEARCH: frozenset({JiraStream.ISSUES}),
    TicketingToolName.GET: frozenset({JiraStream.ISSUES}),
    TicketingToolName.LIST_PROJECTS: frozenset({JiraStream.PROJECTS}),
    TicketingToolName.LIST_WORKFLOW_STATES: frozenset({JiraStream.WORKFLOW_STATES}),
    TicketingToolName.DESCRIBE_FIELDS: frozenset({JiraStream.ISSUES}),
    TicketingToolName.CREATE: frozenset({JiraStream.ISSUES, JiraStream.PROJECTS}),
    TicketingToolName.UPDATE: frozenset({JiraStream.ISSUES}),
    TicketingToolName.TRANSITION: frozenset(
        {JiraStream.ISSUES, JiraStream.WORKFLOW_STATES}
    ),
    TicketingToolName.ASSIGN: frozenset({JiraStream.ISSUES, JiraStream.USERS}),
    TicketingToolName.ADD_LABEL: frozenset({JiraStream.ISSUES, JiraStream.LABELS}),
    TicketingToolName.REMOVE_LABEL: frozenset({JiraStream.ISSUES, JiraStream.LABELS}),
    TicketingToolName.COMMENT: frozenset({JiraStream.ISSUES, JiraStream.COMMENTS}),
    TicketingToolName.LINK: frozenset({JiraStream.ISSUES, JiraStream.ISSUE_RELATIONS}),
}
_MUTATION_RESULT_STREAMS = {
    **{tool_name: JiraStream.ISSUES for tool_name in _WRITE_TOOLS},
    TicketingToolName.COMMENT: JiraStream.COMMENTS,
    TicketingToolName.LINK: JiraStream.ISSUE_RELATIONS,
}


JIRA_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.TICKETING,
    vendor_key="jira",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                JiraStream.ISSUES: "Issues",
                JiraStream.PROJECTS: "Projects",
                JiraStream.WORKFLOW_STATES: "Workflow states",
                JiraStream.USERS: "Users",
                JiraStream.LABELS: "Labels",
                JiraStream.SPRINTS: "Sprints",
                JiraStream.COMMENTS: "Comments",
                JiraStream.ISSUE_RELATIONS: "Issue relations",
            }[stream_key],
            description={
                JiraStream.ISSUES: "Jira issues, ownership, labels, planning fields, and custom fields.",
                JiraStream.PROJECTS: "Jira projects exposed as ticketing work containers.",
                JiraStream.WORKFLOW_STATES: "Jira statuses and normalized status categories.",
                JiraStream.USERS: "Visible active and inactive Jira users.",
                JiraStream.LABELS: "Values used by Jira's global label field.",
                JiraStream.SPRINTS: (
                    "Jira Software sprints referenced by the issue Sprint field."
                ),
                JiraStream.COMMENTS: "Chronological issue comments with Atlassian Document Format retained.",
                JiraStream.ISSUE_RELATIONS: "Typed Jira issue links normalized into canonical directions.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key == JiraStream.ISSUES
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
            ),
            scope_category=(
                "Classic Jira + granular Jira Software scopes"
                if stream_key == JiraStream.SPRINTS
                else "Classic Jira Cloud platform scopes"
            ),
            depends_on=frozenset(
                set(_RELATIONSHIP_TARGETS.get(stream_key, {}).values()) - {stream_key}
            ),
            relationship_targets=SorRelationshipTargets(
                by_role=_RELATIONSHIP_TARGETS.get(stream_key, {}),
            ),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset({"issue", "comment", "relation"}),
    readable_tools=_READ_TOOLS,
    writable_tools=_WRITE_TOOLS,
    change_strategies=frozenset(
        {SorChangeStrategy.UPDATED_AT, SorChangeStrategy.FULL_RECONCILE}
    ),
    required_scopes={
        JiraStream.ISSUES: (READ_WORK_SCOPE,),
        JiraStream.PROJECTS: (READ_WORK_SCOPE,),
        JiraStream.WORKFLOW_STATES: (READ_WORK_SCOPE,),
        JiraStream.USERS: (READ_USER_SCOPE,),
        JiraStream.LABELS: (READ_WORK_SCOPE,),
        JiraStream.SPRINTS: (READ_WORK_SCOPE, READ_SPRINT_SCOPE),
        JiraStream.COMMENTS: (READ_WORK_SCOPE,),
        JiraStream.ISSUE_RELATIONS: (READ_WORK_SCOPE,),
    },
    tool_required_scopes={tool_name: (WRITE_SCOPE,) for tool_name in _WRITE_TOOLS},
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    oauth=SorOAuthSpec(
        authorization_url=ATLASSIAN_AUTHORIZATION_URL,
        token_url=ATLASSIAN_TOKEN_URL,
        base_scopes=(OFFLINE_SCOPE, MANAGE_WEBHOOK_SCOPE),
        authorization_params=ATLASSIAN_AUTHORIZATION_PARAMS,
        token_request_format=SorOAuthTokenRequestFormat.JSON,
        instance_host_suffixes=ATLASSIAN_INSTANCE_HOST_SUFFIXES,
        operator_instance_origin=True,
    ),
    fixed_origin=JIRA_API_ORIGIN,
    requires_instance_origin=True,
    change_mode=SorChangeMode.MANAGED_WEBHOOK,
    supports_custom_fields=True,
    supports_comments=True,
)


def _field(
    key: str,
    label: str,
    data_type: SorFieldDataType,
    *,
    nullable: bool = True,
    writable: bool = False,
    description: str | None = None,
    group: str = "Jira",
    vendor_type: str | None = None,
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        description=description,
        group=group,
        vendor_type=vendor_type,
    )


_SCHEMA_FIELDS = {
    JiraStream.ISSUES: (
        _field("key", "Key", SorFieldDataType.TEXT, nullable=False),
        _field("title", "Title", SorFieldDataType.TEXT, nullable=False, writable=True),
        _field(
            "normalized_description",
            "Description",
            SorFieldDataType.TEXT,
            writable=True,
        ),
        _field(
            "source_description",
            "Source description",
            SorFieldDataType.BOUNDED_JSON,
            description="The original Atlassian Document Format value retained for audit.",
        ),
        _field(
            "issue_type",
            "Issue type",
            SorFieldDataType.TEXT,
            nullable=False,
            writable=True,
        ),
        _field("native_status", "Status", SorFieldDataType.TEXT),
        _field("normalized_status", "Normalized status", SorFieldDataType.ENUM),
        _field("priority", "Priority", SorFieldDataType.TEXT, writable=True),
        _field(
            "project_external_id",
            "Project ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field(
            "assignee_external_id",
            "Assignee ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field("reporter_external_id", "Reporter ID", SorFieldDataType.REFERENCE),
        _field("estimate", "Estimate", SorFieldDataType.DECIMAL, writable=True),
        _field(
            "label_external_ids", "Labels", SorFieldDataType.STRING_ARRAY, writable=True
        ),
        _field(
            "parent_external_id",
            "Parent issue ID",
            SorFieldDataType.REFERENCE,
            writable=True,
        ),
        _field("due_date", "Due date", SorFieldDataType.DATE, writable=True),
        _field("completed_at", "Completed at", SorFieldDataType.TIMESTAMP),
    ),
    JiraStream.PROJECTS: (
        _field("key", "Key", SorFieldDataType.TEXT, nullable=False),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
    ),
    JiraStream.WORKFLOW_STATES: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("native_category", "Source category", SorFieldDataType.TEXT),
        _field("normalized_category", "Normalized category", SorFieldDataType.ENUM),
        _field("order", "Order", SorFieldDataType.INTEGER),
    ),
    JiraStream.USERS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("display_name", "Display name", SorFieldDataType.TEXT),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN, nullable=False),
        _field("assignable", "Assignable", SorFieldDataType.BOOLEAN),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
    JiraStream.LABELS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("color", "Color", SorFieldDataType.TEXT),
        _field("project_external_id", "Project ID", SorFieldDataType.REFERENCE),
        _field("parent_external_id", "Parent label ID", SorFieldDataType.REFERENCE),
        _field("is_group", "Group", SorFieldDataType.BOOLEAN, nullable=False),
    ),
    JiraStream.SPRINTS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("number", "Number", SorFieldDataType.INTEGER),
        _field("description", "Goal", SorFieldDataType.TEXT),
        _field("starts_at", "Starts at", SorFieldDataType.TIMESTAMP),
        _field("ends_at", "Ends at", SorFieldDataType.TIMESTAMP),
        _field("completed_at", "Completed at", SorFieldDataType.TIMESTAMP),
        _field("active", "Active", SorFieldDataType.BOOLEAN),
    ),
    JiraStream.COMMENTS: (
        _field(
            "issue_external_id", "Issue ID", SorFieldDataType.REFERENCE, nullable=False
        ),
        _field("author_external_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("normalized_text", "Comment", SorFieldDataType.TEXT, nullable=False),
        _field("source_body", "Source body", SorFieldDataType.BOUNDED_JSON),
        _field("created_at", "Created at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated at", SorFieldDataType.TIMESTAMP),
    ),
    JiraStream.ISSUE_RELATIONS: (
        _field(
            "issue_vendor_object_key",
            "Issue stream",
            SorFieldDataType.TEXT,
            nullable=False,
        ),
        _field(
            "from_issue_external_id",
            "From issue ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field(
            "to_issue_external_id",
            "To issue ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field(
            "canonical_kind",
            "Normalized relation",
            SorFieldDataType.ENUM,
            nullable=False,
        ),
        _field("native_kind", "Source relation", SorFieldDataType.TEXT, nullable=False),
    ),
}

_ISSUE_API_FIELDS = {
    "assignee",
    "created",
    "description",
    "duedate",
    "issuetype",
    JiraStream.LABELS,
    "parent",
    "priority",
    "project",
    "reporter",
    "resolutiondate",
    "status",
    "summary",
    "timeoriginalestimate",
    "updated",
}
_NORMALIZED_TO_JIRA_FIELD = {
    "title": "summary",
    "normalized_description": "description",
    "source_description": "description",
    "issue_type": "issuetype",
    "native_status": "status",
    "normalized_status": "status",
    "priority": "priority",
    "project_external_id": "project",
    "assignee_external_id": "assignee",
    "reporter_external_id": "reporter",
    "estimate": "timeoriginalestimate",
    "label_external_ids": JiraStream.LABELS,
    "parent_external_id": "parent",
    "due_date": "duedate",
    "completed_at": "resolutiondate",
}


def _cursor_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A cursor timestamp must include a timezone.")
        return value
    parsed = _optional_datetime(value)
    if parsed is None:
        raise ValueError("A cursor timestamp must include a timezone.")
    return parsed


def _cursor_timestamp_text(value: datetime) -> str:
    return value.isoformat()


def _cursor_token(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("A cursor continuation token must be text or null.")
    return _optional_string(value)


_CursorTimestamp = Annotated[
    datetime,
    BeforeValidator(_cursor_timestamp),
    PlainSerializer(_cursor_timestamp_text, return_type=str),
]
_CursorToken = Annotated[
    Annotated[str, Field(max_length=JIRA_CURSOR_TOKEN_LIMIT)] | None,
    BeforeValidator(_cursor_token),
]


class _CursorHeader(BaseModel):
    """Route persisted versions without interpreting obsolete position fields."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    stream: JiraStream
    v: int


class _LegacyIssueCursorEnvelope(_CursorHeader):
    """Only the old watermark survives a restart; other v1 fields are discarded."""

    model_config = ConfigDict(extra="forbid")

    floor: _CursorTimestamp | None
    high: SorJsonValue
    next_token: SorJsonValue
    started_at: SorJsonValue


class _LegacySprintCursorEnvelope(_CursorHeader):
    """Old board positions are never reused for the issue-driven Sprint scan."""

    model_config = ConfigDict(extra="forbid")

    board_id: SorJsonValue
    board_is_last: SorJsonValue
    board_offset: SorJsonValue
    project_external_id: SorJsonValue
    sprint_offset: SorJsonValue


class _OffsetCursorEnvelope(_CursorHeader):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)


class _IssueCursor(BaseModel):
    """Jira issue-search position owned by the vendor cursor codec."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    floor: datetime | None
    project_offset: int = Field(ge=0)
    next_token: str | None
    high: datetime | None
    started_at: datetime
    completed: bool


class _CommentCursor(BaseModel):
    """Resume missing comment ranges around Jira's embedded issue comments."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    project_offset: int = Field(ge=0)
    next_issue_token: str | None
    issue_ids: tuple[str, ...]
    item_offsets: tuple[int, ...]
    item_stops: tuple[int, ...]
    issue_page_is_last: bool
    current_project_is_last: bool


class _RelationCursor(BaseModel):
    """Resume project-bounded Jira issue-link search pages."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    project_offset: int = Field(ge=0)
    next_issue_token: str | None


class _SprintCursor(BaseModel):
    """Resume Sprint extraction within stable issue-search pages."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    floor: datetime | None
    project_offset: int = Field(ge=0)
    next_issue_token: str | None
    item_offset: int = Field(ge=0)
    high: datetime | None
    started_at: datetime
    completed: bool


class _IssueCursorEnvelope(_IssueCursor):
    stream: Literal[JiraStream.ISSUES]
    v: int = Field(ge=JIRA_ISSUE_CURSOR_VERSION, le=JIRA_ISSUE_CURSOR_VERSION)
    floor: _CursorTimestamp | None
    high: _CursorTimestamp | None
    started_at: _CursorTimestamp
    next_token: _CursorToken


class _CommentCursorEnvelope(_CommentCursor):
    stream: Literal[JiraStream.COMMENTS]
    v: int = Field(ge=JIRA_COMMENT_CURSOR_VERSION, le=JIRA_COMMENT_CURSOR_VERSION)
    next_issue_token: _CursorToken

    @field_validator("issue_ids", mode="before")
    @classmethod
    def normalize_issue_ids(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("Comment cursor issue IDs must be a sequence.")
        try:
            return tuple(
                _required_id(item, field="Jira child cursor issue ID") for item in value
            )
        except SorVendorOperationError as error:
            raise ValueError("Comment cursor contains an invalid issue ID.") from error


class _RelationCursorEnvelope(_RelationCursor):
    stream: Literal[JiraStream.ISSUE_RELATIONS]
    v: int = Field(ge=JIRA_RELATION_CURSOR_VERSION, le=JIRA_RELATION_CURSOR_VERSION)
    next_issue_token: _CursorToken


class _SprintCursorEnvelope(_SprintCursor):
    stream: Literal[JiraStream.SPRINTS]
    v: int = Field(ge=JIRA_SPRINT_CURSOR_VERSION, le=JIRA_SPRINT_CURSOR_VERSION)
    floor: _CursorTimestamp | None
    high: _CursorTimestamp | None
    started_at: _CursorTimestamp
    next_issue_token: _CursorToken


def _parse_cursor[T: BaseModel](value: str, model: type[T], *, stream: str) -> T:
    try:
        return model.model_validate_json(value)
    except ValidationError as error:
        raise _invalid_cursor(stream) from error


def _encode_cursor(envelope: BaseModel) -> str:
    """Retain sorted keys, ASCII escaping and timestamp spelling of stored cursors."""
    return json.dumps(
        envelope.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    )


class _JiraIssueLinkSnapshot(BaseModel):
    """Validated Jira link values shared by projection and mutation lookup."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    relation_id: str
    from_issue_external_id: str
    to_issue_external_id: str
    canonical_kind: TicketingRelationKind
    native_kind: str


class JiraTicketingAdapter:
    """Translate one exact Jira Cloud site into Eylo's ticketing contract."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "jira":
            raise ValueError("Jira adapter requires the jira vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Jira Cloud SOR requires OAuth 2.0.")
        token = _credential(context.credentials, "access_token")
        self._context = context
        self._issue_agent_keys = {
            field.vendor_field_key: field.agent_key
            for field in context.fields
            if field.vendor_object_key == JiraStream.ISSUES
        }
        self._site_origin = _jira_site_origin(context.instance_origin)
        self._cloud_id: str | None = None
        self._site_name: str | None = None
        self._project_pages: dict[int, tuple[str, bool] | None] = {}
        self._sprint_details: dict[str, SorExternalRecord] = {}
        self._client = SorJsonHttpClient(
            origin=JIRA_API_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        cloud_id, site_name = await self._resolve_site()
        response = await self._jira_request("/myself")
        viewer = native.parse_response(
            _expect(response, operation="verify Jira account"), native.JiraViewer
        )
        display = _optional_string(viewer.displayName)
        return SorConnectionVerification(
            account_external_id=cloud_id,
            account_display_name=site_name or display or "Jira Cloud site",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=JIRA_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Jira source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        custom_fields: tuple[SorDiscoveredField, ...] = ()
        if JiraStream.ISSUES in self._context.selected_objects:
            response = await self._jira_request("/field")
            rows = native.parse_response(
                _expect(response, operation="list Jira fields"),
                native.JiraCollection[native.JiraField],
            ).root
            custom_fields = tuple(
                sorted(
                    (_jira_custom_field(row) for row in rows if row.custom is True),
                    key=lambda field: (field.label.casefold(), field.key),
                )
            )
        objects: list[SorDiscoveredObject] = []
        streams = {stream.key: stream for stream in JIRA_MANIFEST.streams}
        for stream_key in self._context.selected_objects:
            stream_key = _require_stream(
                stream_key, selected=self._context.selected_objects
            )
            fields = _SCHEMA_FIELDS[stream_key]
            if stream_key == JiraStream.ISSUES:
                fields = (*fields, *custom_fields)
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=streams[stream_key].label,
                    fields=fields,
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects), vendor_api_version=JIRA_API_VERSION
        )

    async def bootstrap_stream(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def pull_changes(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        return await self._read_page(stream_key=stream_key, cursor=cursor, limit=limit)

    async def fetch_record(
        self,
        *,
        vendor_object_key: str,
        external_id: str,
    ) -> SorExternalRecord:
        stream_key = _require_stream(
            vendor_object_key,
            selected=self._context.selected_objects,
        )
        record_id = _required_id(external_id, field="Jira record ID")
        if stream_key == JiraStream.LABELS:
            return self._external_directory_record(native.JiraLabel(name=record_id))
        if stream_key == JiraStream.ISSUES:
            response = await self._jira_request(
                f"/issue/{_path_segment(record_id)}",
                query=native.JiraIssueQuery(
                    fields=list(self._issue_fields())
                ).model_dump(mode="json"),
            )
        elif stream_key == JiraStream.PROJECTS:
            response = await self._jira_request(f"/project/{_path_segment(record_id)}")
        elif stream_key == JiraStream.WORKFLOW_STATES:
            response = await self._jira_request(f"/status/{_path_segment(record_id)}")
        elif stream_key == JiraStream.USERS:
            response = await self._jira_request(
                "/user",
                query={"accountId": record_id},
            )
        elif stream_key == JiraStream.SPRINTS:
            return await self._fetch_sprint(record_id)
        elif stream_key == JiraStream.COMMENTS:
            issue_id, comment_id = _split_comment_external_id(record_id)
            response = await self._jira_request(
                f"/issue/{_path_segment(issue_id)}/comment/{_path_segment(comment_id)}"
            )
        else:
            response = await self._jira_request(
                f"/issueLink/{_path_segment(record_id)}"
            )
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        value = _expect(response, operation="read Jira record")
        if stream_key == JiraStream.PROJECTS:
            return self._external_directory_record(
                native.parse_response(value, native.JiraProject)
            )
        if stream_key == JiraStream.WORKFLOW_STATES:
            return self._external_directory_record(
                native.parse_response(value, native.JiraStatus)
            )
        if stream_key == JiraStream.USERS:
            return self._external_directory_record(
                native.parse_response(value, native.JiraUser)
            )
        if stream_key == JiraStream.COMMENTS:
            issue_id, _comment_id = _split_comment_external_id(record_id)
            return self._external_comment(
                native.parse_response(value, native.JiraComment), issue_id=issue_id
            )
        if stream_key == JiraStream.ISSUES:
            return self._external_issue(native.parse_response(value, native.JiraIssue))
        return self._external_relation(
            native.parse_response(value, native.JiraIssueLink)
        )

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Jira deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        events = _webhook_events(self._context.selected_objects)
        if not events:
            raise SorCapabilityUnavailable(
                "The selected Jira objects have no dynamic webhook events."
            )
        existing = await self._recover_webhook(
            callback_url=callback_url,
            events=events,
        )
        if existing is not None:
            return existing
        response = await self._jira_request(
            "/webhook",
            method=HTTPMethod.POST,
            payload=JiraWebhookRegistrationRequest(
                url=callback_url,
                webhooks=(
                    JiraWebhookDetails(
                        events=events,
                        jqlFilter=JIRA_ALL_PROJECTS_WEBHOOK_JQL,
                    ),
                ),
            ).model_dump(mode="json"),
        )
        payload = parse_jira_webhook_response(
            _expect(response, operation="register Jira webhooks"),
            JiraWebhookRegistrationResponse,
        )
        results = payload.webhookRegistrationResult
        if len(results) != 1:
            raise _invalid_response("Jira returned an ambiguous webhook registration.")
        result = results[0]
        if result.errors:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_WEBHOOK_REJECTED,
                "Jira rejected the webhook event selection.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        external_id = _required_id(
            result.createdWebhookId,
            field="Jira webhook ID",
        )
        return SorWebhookSubscription(
            external_id=external_id,
            expires_at=datetime.now(timezone.utc) + JIRA_WEBHOOK_LIFETIME,
        )

    async def _recover_webhook(
        self,
        *,
        callback_url: str,
        events: tuple[JiraWebhookEvent, ...],
    ) -> SorWebhookSubscription | None:
        """Recover an exact prior registration after a post-vendor crash."""
        response = await self._jira_request(
            "/webhook",
            query=JiraWebhookListQuery().model_dump(mode="json"),
        )
        payload = parse_jira_webhook_response(
            _expect(response, operation="list Jira webhooks"),
            JiraWebhookPage,
        )
        if not payload.isLast:
            raise _invalid_response("Jira webhook recovery exceeded one bounded page.")
        exact: list[SorWebhookSubscription] = []
        stale_ids: list[int] = []
        expected_events = frozenset(events)
        for row in payload.values:
            if _optional_string(row.url) != callback_url:
                continue
            webhook_id = _webhook_id(_required_id(row.id, field="Jira webhook ID"))
            row_events = frozenset(row.events or ())
            if (
                row.jqlFilter == JIRA_ALL_PROJECTS_WEBHOOK_JQL
                and row_events == expected_events
            ):
                exact.append(
                    SorWebhookSubscription(
                        external_id=str(webhook_id),
                        expires_at=_required_datetime(
                            row.expirationDate,
                            field="Jira webhook expiration date",
                        ),
                    )
                )
            else:
                stale_ids.append(webhook_id)
        if exact:
            exact.sort(
                key=lambda subscription: subscription.expires_at
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            stale_ids.extend(
                _webhook_id(subscription.external_id) for subscription in exact[1:]
            )
        if stale_ids:
            await self._remove_webhook_ids(stale_ids)
        return exact[0] if exact else None

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        response = await self._jira_request(
            "/webhook/refresh",
            method=HTTPMethod.PUT,
            payload=JiraWebhookIdsRequest(
                webhookIds=(_webhook_id(subscription.external_id),),
            ).model_dump(mode="json"),
        )
        payload = parse_jira_webhook_response(
            _expect(response, operation="renew Jira webhooks"),
            JiraWebhookRenewalResponse,
        )
        return SorWebhookSubscription(
            external_id=subscription.external_id,
            expires_at=_required_datetime(
                payload.expirationDate,
                field="Jira webhook expiration date",
            ),
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        await self._remove_webhook_ids([_webhook_id(subscription.external_id)])

    async def _remove_webhook_ids(self, webhook_ids: Sequence[int]) -> None:
        """Delete source-owned Jira webhooks by their validated IDs."""
        response = await self._jira_request(
            "/webhook",
            method=HTTPMethod.DELETE,
            payload=JiraWebhookIdsRequest(
                webhookIds=tuple(webhook_ids),
            ).model_dump(mode="json"),
        )
        if response.status_code != HTTPStatus.ACCEPTED:
            _expect(response, operation="remove Jira webhooks")
            raise _invalid_response(
                "Jira returned an unexpected webhook deletion status."
            )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        client_secret = self._context.webhook_auth_secret
        if client_secret is None:
            raise SorWebhookVerificationError(
                "Jira webhook application credentials are unavailable."
            )
        authorization = _header(headers, "authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            raise SorWebhookVerificationError(
                "Jira webhook bearer authentication is missing."
            )
        token = authorization.removeprefix("Bearer ").strip()
        if not token or len(token) > 8192:
            raise SorWebhookVerificationError(
                "Jira webhook bearer authentication is invalid."
            )
        try:
            jwt.decode(
                token,
                client_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        except PyJWTError as error:
            raise SorWebhookVerificationError(
                "Jira webhook bearer authentication is invalid."
            ) from error
        parse_jira_webhook_body(
            body, JiraWebhookWire, error_type=SorWebhookVerificationError
        )
        _jira_delivery_id(headers)

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        payload = parse_jira_webhook_body(body, JiraWebhookDelivery)
        delivery_id = _jira_delivery_id(headers)
        event_type = payload.webhookEvent
        subscription_id = self._context.webhook_subscription_id
        matched = frozenset(payload.matchedWebhookIds)
        if subscription_id is not None and subscription_id not in matched:
            raise SorWebhookPayloadError(
                "Jira webhook does not match this source subscription."
            )
        stream_key, external_id = _jira_webhook_record_identity(
            event_type,
            payload,
        )
        if stream_key not in self._context.selected_objects:
            stream_key = None
            external_id = None
        return (
            SorWebhookSignal(
                delivery_id=delivery_id,
                event_type=event_type,
                vendor_object_key=stream_key,
                external_id=external_id,
                occurred_at=_jira_webhook_occurred_at(payload.timestamp),
            ),
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Jira adapter does not execute the requested issue action.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if command.tool_name == TicketingToolName.CREATE:
            return await self._create_issue(command)
        target_id = _required_target(command)
        if command.tool_name == TicketingToolName.UPDATE:
            return await self._update_issue(target_id, command)
        if command.tool_name == TicketingToolName.TRANSITION:
            return await self._transition_issue(target_id, command)
        if command.tool_name == TicketingToolName.ASSIGN:
            return await self._assign_issue(target_id, command)
        if command.tool_name == TicketingToolName.COMMENT:
            return await self._comment_issue(target_id, command)
        if command.tool_name == TicketingToolName.LINK:
            return await self._link_issue(target_id, command)
        return await self._change_label(
            target_id,
            command,
            action=native.JiraLabelAction.ADD
            if command.tool_name == TicketingToolName.ADD_LABEL
            else native.JiraLabelAction.REMOVE,
        )

    def normalize_issue(
        self,
        record: SorExternalRecord,
        payload: TicketingIssuePayload,
    ) -> TicketingIssue:
        return TicketingIssue(
            external_id=record.external_id,
            key=_optional_string(payload.key),
            title=_required_string(payload.title, field="Jira issue title"),
            normalized_description=_optional_string(payload.normalized_description),
            source_description=_json_value(payload.source_description),
            issue_type=_optional_string(payload.issue_type),
            native_status=_optional_string(payload.native_status),
            normalized_status=payload.normalized_status,
            priority=_optional_string(payload.priority),
            project_external_id=_optional_string(payload.project_external_id),
            team_external_id=_optional_string(payload.team_external_id),
            assignee_external_id=_optional_string(payload.assignee_external_id),
            reporter_external_id=_optional_string(payload.reporter_external_id),
            estimate=payload.estimate,
            label_external_ids=payload.label_external_ids,
            parent_external_id=_optional_string(payload.parent_external_id),
            cycle_external_id=_optional_string(payload.cycle_external_id),
            due_date=payload.due_date,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            cancelled_at=payload.cancelled_at,
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
            custom_fields={},
        )

    def normalize_project(
        self,
        record: SorExternalRecord,
        payload: TicketingProjectPayload,
    ) -> TicketingProject:
        return TicketingProject(
            external_id=record.external_id,
            key=_optional_string(payload.key),
            name=_required_string(payload.name, field="Jira project name"),
            description=_optional_string(payload.description),
            source_url=record.source_url,
        )

    def normalize_workflow_state(
        self,
        record: SorExternalRecord,
        payload: TicketingWorkflowStatePayload,
    ) -> TicketingWorkflowState:
        return TicketingWorkflowState(
            external_id=record.external_id,
            name=_required_string(
                payload.name,
                field="Jira workflow state name",
            ),
            native_category=_optional_string(payload.native_category),
            normalized_category=payload.normalized_category,
            order=(int(payload.order) if payload.order is not None else None),
        )

    def normalize_user(
        self,
        record: SorExternalRecord,
        payload: TicketingUserPayload,
    ) -> TicketingUser:
        return TicketingUser(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Jira user name"),
            display_name=_optional_string(payload.display_name),
            primary_email=_optional_string(payload.primary_email),
            active=payload.active,
            assignable=payload.assignable,
            avatar_url=_optional_string(payload.avatar_url),
            source_url=record.source_url,
        )

    def normalize_label(
        self,
        record: SorExternalRecord,
        payload: TicketingLabelPayload,
    ) -> TicketingLabel:
        return TicketingLabel(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Jira label name"),
            description=_optional_string(payload.description),
            color=_optional_string(payload.color),
            project_external_id=_optional_string(payload.project_external_id),
            parent_external_id=_optional_string(payload.parent_external_id),
            is_group=payload.is_group,
        )

    def normalize_cycle(
        self,
        record: SorExternalRecord,
        payload: TicketingCyclePayload,
    ) -> TicketingCycle:
        return TicketingCycle(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Jira sprint name"),
            number=payload.number,
            project_external_id=_optional_string(payload.project_external_id),
            description=_optional_string(payload.description),
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            completed_at=payload.completed_at,
            active=payload.active,
        )

    def normalize_comment(
        self,
        record: SorExternalRecord,
        payload: TicketingCommentPayload,
    ) -> TicketingComment:
        return TicketingComment(
            external_id=record.external_id,
            issue_external_id=_required_string(
                payload.issue_external_id,
                field="Jira comment issue ID",
            ),
            author_external_id=_optional_string(payload.author_external_id),
            normalized_text=_required_string(
                payload.normalized_text,
                field="Jira comment body",
            ),
            source_body=_json_value(payload.source_body),
            created_at=payload.created_at,
            updated_at=payload.updated_at,
        )

    def normalize_relation(
        self,
        record: SorExternalRecord,
        payload: TicketingRelationPayload,
    ) -> TicketingIssueRelation:
        return TicketingIssueRelation(
            external_id=record.external_id,
            issue_vendor_object_key=JiraStream.ISSUES,
            from_issue_external_id=payload.from_issue_external_id,
            to_issue_external_id=payload.to_issue_external_id,
            canonical_kind=payload.canonical_relation_kind,
            native_kind=payload.native_relation_kind,
            source_revision=record.source_revision,
        )

    async def close(self) -> None:
        return None

    async def _resolve_site(self) -> tuple[str, str | None]:
        if self._cloud_id is not None:
            return self._cloud_id, self._site_name
        response = await self._client.request("/oauth/token/accessible-resources")
        rows = native.parse_response(
            _expect(response, operation="list accessible Jira sites"),
            native.JiraCollection[native.JiraSite],
        ).root
        matches = [
            row for row in rows if _normalized_origin(row.url) == self._site_origin
        ]
        if len(matches) != 1:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_SITE_UNAVAILABLE,
                "The authorized Atlassian account does not expose the configured Jira site.",
                recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
            )
        site = matches[0]
        self._cloud_id = _required_id(site.id, field="Jira cloud ID")
        self._site_name = _optional_string(site.name)
        return self._cloud_id, self._site_name

    async def _jira_request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, object] | None = None,
        payload: object | None = None,
        idempotency_key: str | None = None,
        retry_transport_failures: bool = False,
    ) -> SorJsonResponse:
        cloud_id, _name = await self._resolve_site()
        return await self._client.request(
            f"/ex/jira/{_path_segment(cloud_id)}/rest/api/3{path}",
            method=method,
            query=query,
            payload=payload,
            idempotency_key=idempotency_key,
            retry_transport_failures=retry_transport_failures,
        )

    async def _agile_request(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> SorJsonResponse:
        cloud_id, _name = await self._resolve_site()
        return await self._client.request(
            f"/ex/jira/{_path_segment(cloud_id)}/rest/agile/1.0{path}",
            query=query,
        )

    async def _project_at(self, offset: int) -> tuple[str, bool] | None:
        if offset in self._project_pages:
            return self._project_pages[offset]
        response = await self._jira_request(
            "/project/search",
            query=native.JiraPageQuery(
                startAt=offset, maxResults=1, orderBy=native.JiraOrderBy.KEY
            ).model_dump(mode="json", exclude_none=True),
        )
        data = native.parse_response(
            _expect(response, operation="list Jira projects"),
            native.JiraPage[native.JiraProjectIdentity],
        )
        rows = data.values
        if len(rows) > 1:
            raise _invalid_response("Jira returned too many projects.")
        is_last = data.isLast
        if not rows:
            if not is_last:
                raise _invalid_response("Jira returned an empty partial project page.")
            self._project_pages[offset] = None
            return None
        project_id = _required_id(rows[0].id, field="Jira project ID")
        if re.fullmatch(r"[0-9]+", project_id) is None:
            raise _invalid_response("Jira returned an invalid project ID.")
        page = (project_id, is_last)
        self._project_pages[offset] = page
        return page

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(
            stream_key, selected=self._context.selected_objects
        )
        if limit <= 0:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Jira page limit must be positive.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if stream_key == JiraStream.COMMENTS:
            return await self._read_comment_page(
                cursor=cursor,
                limit=min(limit, native.JIRA_COMMENT_PAGE_SIZE),
            )
        page_limit = min(limit, native.JIRA_READ_PAGE_SIZE)
        if stream_key == JiraStream.ISSUES:
            return await self._read_issues(cursor=cursor, limit=page_limit)
        if stream_key == JiraStream.ISSUE_RELATIONS:
            return await self._read_issue_relation_page(
                cursor=cursor,
                limit=page_limit,
            )
        if stream_key == JiraStream.SPRINTS:
            return await self._read_sprints(cursor=cursor, limit=page_limit)
        offset = _decode_offset_cursor(cursor, stream_key=stream_key)
        query = native.JiraPageQuery(startAt=offset, maxResults=page_limit)
        rows: Sequence[native.JiraDirectoryRecord]
        if stream_key == JiraStream.PROJECTS:
            query = native.JiraPageQuery(
                startAt=offset, maxResults=page_limit, orderBy=native.JiraOrderBy.KEY
            )
            response = await self._jira_request(
                "/project/search",
                query=query.model_dump(mode="json", exclude_none=True),
            )
            data = native.parse_response(
                _expect(response, operation="list Jira projects"),
                native.JiraPage[native.JiraProject],
            )
            rows = data.values
            has_more = not data.isLast
        elif stream_key == JiraStream.WORKFLOW_STATES:
            response = await self._jira_request("/status")
            all_rows = sorted(
                native.parse_response(
                    _expect(response, operation="list Jira statuses"),
                    native.JiraCollection[native.JiraStatus],
                ).root,
                key=lambda row: (
                    _required_string(row.name, field="Jira status name").casefold(),
                    _required_id(row.id, field="Jira status ID"),
                ),
            )
            rows = all_rows[offset : offset + page_limit]
            has_more = offset + len(rows) < len(all_rows)
        elif stream_key == JiraStream.USERS:
            response = await self._jira_request(
                "/users", query=query.model_dump(mode="json", exclude_none=True)
            )
            rows = native.parse_response(
                _expect(response, operation="list Jira users"),
                native.JiraCollection[native.JiraUser],
            ).root
            has_more = len(rows) == page_limit
        else:
            response = await self._jira_request(
                "/label", query=query.model_dump(mode="json", exclude_none=True)
            )
            labels = native.parse_response(
                _expect(response, operation="list Jira labels"), native.JiraLabelPage
            )
            rows = [native.JiraLabel(name=label) for label in labels.values]
            has_more = not labels.isLast
        if len(rows) > page_limit:
            raise _invalid_response(
                "Jira returned more rows than the requested page limit."
            )
        return SorRecordPage(
            records=tuple(
                self._external_directory_record(row, position=offset + index)
                for index, row in enumerate(rows)
            ),
            next_cursor=_encode_offset_cursor(offset + len(rows), stream_key=stream_key)
            if has_more
            else None,
            has_more=has_more,
        )

    async def _read_issues(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        checkpoint = _decode_issue_cursor(cursor)
        project = await self._project_at(checkpoint.project_offset)
        if project is None:
            completed = _completed_issue_cursor(
                floor=checkpoint.floor,
                high=checkpoint.high,
                started_at=checkpoint.started_at,
            )
            return SorRecordPage(
                records=(),
                next_cursor=_encode_issue_cursor(completed),
                has_more=False,
            )
        project_id, project_is_last = project
        payload = native.JiraSearchRequest(
            fields=list(self._issue_fields()),
            fieldsByKeys=True,
            jql=_issue_sync_jql(project_id, floor=checkpoint.floor),
            maxResults=limit,
            nextPageToken=checkpoint.next_token,
        )
        response = await self._jira_request(
            "/search/jql",
            method="POST",
            payload=payload.model_dump(mode="json", exclude_none=True),
            retry_transport_failures=True,
        )
        data = native.parse_response(
            _expect(response, operation="search Jira issues"),
            native.JiraSearchPage[native.JiraIssue],
        )
        rows = data.issues
        if len(rows) > limit:
            raise _invalid_response(
                "Jira returned more issues than the requested page limit."
            )
        is_last = data.isLast
        next_token = _optional_string(data.nextPageToken)
        if not is_last and next_token is None:
            raise _invalid_response("Jira omitted the next issue page token.")
        high = _maximum_issue_updated_at(
            [row.fields.updated for row in rows], current=checkpoint.high
        )
        scan_complete = is_last and project_is_last
        if scan_complete:
            next_cursor = _encode_issue_cursor(
                _completed_issue_cursor(
                    floor=checkpoint.floor,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
        else:
            next_cursor = _encode_issue_cursor(
                _IssueCursor(
                    floor=checkpoint.floor,
                    project_offset=(
                        checkpoint.project_offset + 1
                        if is_last
                        else checkpoint.project_offset
                    ),
                    next_token=None if is_last else next_token,
                    high=high,
                    started_at=checkpoint.started_at,
                    completed=False,
                )
            )
        return SorRecordPage(
            records=tuple(self._external_issue(row) for row in rows),
            next_cursor=next_cursor,
            has_more=not scan_complete,
        )

    async def _read_issue_relation_page(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_relation_cursor(cursor)
        project = await self._project_at(checkpoint.project_offset)
        if project is None:
            return SorRecordPage(records=(), next_cursor=None, has_more=False)
        project_id, project_is_last = project
        payload = native.JiraSearchRequest(
            fields=["issuelinks"],
            fieldsByKeys=True,
            jql=_issue_scan_jql(project_id),
            maxResults=min(limit, JIRA_RELATION_ISSUE_BATCH_SIZE),
            nextPageToken=checkpoint.next_issue_token,
        )
        response = await self._jira_request(
            "/search/jql",
            method="POST",
            payload=payload.model_dump(mode="json", exclude_none=True),
            retry_transport_failures=True,
        )
        data = native.parse_response(
            _expect(response, operation="scan Jira issue links"),
            native.JiraSearchPage[native.JiraLinkedIssue],
        )
        issues = data.issues
        if len(issues) > limit:
            raise _invalid_response("Jira returned too many issues for a link scan.")
        is_last = data.isLast
        following = _optional_string(data.nextPageToken)
        if not is_last and following is None:
            raise _invalid_response("Jira omitted the next issue-link page token.")

        records: list[SorExternalRecord] = []
        for issue in issues:
            issue_id = _required_id(issue.id, field="Jira issue ID")
            for link in issue.fields.issuelinks:
                records.append(self._external_relation(link, current_issue_id=issue_id))
        records = _deduplicate_child_records(
            records,
            stream_key=JiraStream.ISSUE_RELATIONS,
        )
        if len(records) > limit:
            raise _invalid_response(
                "Jira returned more issue links than one bounded page can contain."
            )

        scan_complete = is_last and project_is_last
        next_cursor = None
        if not scan_complete:
            next_cursor = _encode_relation_cursor(
                _RelationCursor(
                    project_offset=(
                        checkpoint.project_offset + 1
                        if is_last
                        else checkpoint.project_offset
                    ),
                    next_issue_token=None if is_last else following,
                )
            )
        return SorRecordPage(
            records=tuple(records),
            next_cursor=next_cursor,
            has_more=not scan_complete,
        )

    async def _read_comment_page(
        self,
        *,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_comment_cursor(cursor)
        scans = 0
        while scans < 25:
            if checkpoint.issue_ids:
                page = await self._read_missing_comment_ranges(
                    checkpoint=checkpoint,
                    limit=limit,
                )
                if page is not None:
                    return page
                checkpoint = _advance_comment_cursor(checkpoint)
                if checkpoint is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                scans += 1
                continue

            project = await self._project_at(checkpoint.project_offset)
            if project is None:
                return SorRecordPage(records=(), next_cursor=None, has_more=False)
            project_id, project_is_last = project
            issue_limit = max(
                1,
                min(
                    JIRA_COMMENT_ISSUE_BATCH_SIZE,
                    limit // JIRA_EMBEDDED_COMMENT_LIMIT,
                ),
            )
            payload = native.JiraSearchRequest(
                fields=["comment"],
                fieldsByKeys=True,
                jql=_issue_scan_jql(project_id),
                maxResults=issue_limit,
                nextPageToken=checkpoint.next_issue_token,
            )
            response = await self._jira_request(
                "/search/jql",
                method="POST",
                payload=payload.model_dump(mode="json", exclude_none=True),
                retry_transport_failures=True,
            )
            data = native.parse_response(
                _expect(response, operation="scan Jira issue comments"),
                native.JiraSearchPage[native.JiraCommentIssue],
            )
            issues = data.issues
            if len(issues) > issue_limit:
                raise _invalid_response(
                    "Jira returned too many issues for a comment scan."
                )
            issue_page_is_last = data.isLast
            following = _optional_string(data.nextPageToken)
            if not issue_page_is_last and following is None:
                raise _invalid_response(
                    "Jira omitted the next issue-comment page token."
                )
            if not issues and not issue_page_is_last:
                raise _invalid_response(
                    "Jira returned an empty partial issue-comment scan."
                )

            records: list[SorExternalRecord] = []
            pending_issue_ids: list[str] = []
            pending_item_offsets: list[int] = []
            pending_item_stops: list[int] = []
            for issue in issues:
                issue_id = _required_id(issue.id, field="Jira issue ID")
                comment_page = issue.fields.comment
                rows = comment_page.comments
                start_at = comment_page.startAt
                total = comment_page.total
                embedded_end = start_at + len(rows)
                if embedded_end > total:
                    raise _invalid_response(
                        "Jira embedded comments exceed their declared total."
                    )
                for row in rows:
                    records.append(self._external_comment(row, issue_id=issue_id))
                if start_at > 0:
                    pending_issue_ids.append(issue_id)
                    pending_item_offsets.append(0)
                    pending_item_stops.append(start_at)
                if embedded_end < total:
                    pending_issue_ids.append(issue_id)
                    pending_item_offsets.append(embedded_end)
                    pending_item_stops.append(total)

            if len(records) > limit:
                raise _invalid_response(
                    "Jira returned more embedded comments than one bounded page can contain."
                )
            checkpoint = _CommentCursor(
                project_offset=checkpoint.project_offset,
                next_issue_token=None if issue_page_is_last else following,
                issue_ids=tuple(pending_issue_ids),
                item_offsets=tuple(pending_item_offsets),
                item_stops=tuple(pending_item_stops),
                issue_page_is_last=issue_page_is_last,
                current_project_is_last=project_is_last,
            )
            if checkpoint.issue_ids:
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=_encode_comment_cursor(checkpoint),
                    has_more=True,
                )
            following_checkpoint = _advance_comment_cursor(checkpoint)
            if following_checkpoint is None:
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=None,
                    has_more=False,
                )
            if records:
                return SorRecordPage(
                    records=tuple(records),
                    next_cursor=_encode_comment_cursor(following_checkpoint),
                    has_more=True,
                )
            checkpoint = following_checkpoint
            scans += 1

        return SorRecordPage(
            records=(),
            next_cursor=_encode_comment_cursor(checkpoint),
            has_more=True,
        )

    async def _read_missing_comment_ranges(
        self,
        *,
        checkpoint: _CommentCursor,
        limit: int,
    ) -> SorRecordPage | None:
        per_segment_limit = max(1, limit // len(checkpoint.issue_ids))
        outcomes = await asyncio.gather(
            *(
                self._read_issue_comment_segment(
                    issue_id=issue_id,
                    offset=item_offset,
                    stop=item_stop,
                    limit=per_segment_limit,
                )
                for issue_id, item_offset, item_stop in zip(
                    checkpoint.issue_ids,
                    checkpoint.item_offsets,
                    checkpoint.item_stops,
                    strict=True,
                )
            )
        )
        records: list[SorExternalRecord] = []
        pending_issue_ids: list[str] = []
        pending_item_offsets: list[int] = []
        pending_item_stops: list[int] = []
        for issue_id, item_offset, item_stop, (rows, has_more) in zip(
            checkpoint.issue_ids,
            checkpoint.item_offsets,
            checkpoint.item_stops,
            outcomes,
            strict=True,
        ):
            records.extend(
                self._external_comment(row, issue_id=issue_id) for row in rows
            )
            if has_more:
                pending_issue_ids.append(issue_id)
                pending_item_offsets.append(item_offset + len(rows))
                pending_item_stops.append(item_stop)
        if pending_issue_ids:
            next_checkpoint = _CommentCursor(
                project_offset=checkpoint.project_offset,
                next_issue_token=checkpoint.next_issue_token,
                issue_ids=tuple(pending_issue_ids),
                item_offsets=tuple(pending_item_offsets),
                item_stops=tuple(pending_item_stops),
                issue_page_is_last=checkpoint.issue_page_is_last,
                current_project_is_last=checkpoint.current_project_is_last,
            )
            return SorRecordPage(
                records=tuple(records),
                next_cursor=_encode_comment_cursor(next_checkpoint),
                has_more=True,
            )
        following_checkpoint = _advance_comment_cursor(checkpoint)
        if following_checkpoint is None:
            return SorRecordPage(
                records=tuple(records),
                next_cursor=None,
                has_more=False,
            )
        if not records:
            return None
        return SorRecordPage(
            records=tuple(records),
            next_cursor=_encode_comment_cursor(following_checkpoint),
            has_more=True,
        )

    async def _read_issue_comment_segment(
        self,
        *,
        issue_id: str,
        offset: int,
        stop: int,
        limit: int,
    ) -> tuple[list[native.JiraComment], bool]:
        page_limit = min(limit, stop - offset)
        response = await self._jira_request(
            f"/issue/{_path_segment(issue_id)}/comment",
            query=native.JiraCommentQuery(
                startAt=offset,
                maxResults=page_limit,
                orderBy=native.JiraOrderBy.CREATED,
            ).model_dump(mode="json"),
        )
        data = native.parse_response(
            _expect(response, operation="list Jira issue comments"),
            native.JiraCommentPage,
        )
        rows = data.comments
        if len(rows) > page_limit:
            raise _invalid_response("Jira returned too many issue comments.")
        start_at = data.startAt
        total = data.total
        if start_at != offset or total < stop:
            raise _invalid_response("Jira comment pagination changed during the scan.")
        has_more = offset + len(rows) < stop
        if has_more and not rows:
            raise _invalid_response("Jira returned an empty partial comment page.")
        return rows, has_more

    async def _read_sprints(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        checkpoint = _decode_sprint_cursor(cursor)
        scans = 0
        while scans < JIRA_SPRINT_SCAN_LIMIT:
            project = await self._project_at(checkpoint.project_offset)
            if project is None:
                completed = _completed_sprint_cursor(
                    floor=checkpoint.floor,
                    high=checkpoint.high,
                    started_at=checkpoint.started_at,
                )
                return SorRecordPage(
                    records=(),
                    next_cursor=_encode_sprint_cursor(completed),
                    has_more=False,
                )
            project_id, project_is_last = project
            sprint_field = self._sprint_field_key()
            payload = native.JiraSearchRequest(
                fields=[sprint_field, "updated"],
                fieldsByKeys=True,
                jql=_sprint_issue_jql(project_id, floor=checkpoint.floor),
                maxResults=JIRA_SPRINT_ISSUE_BATCH_SIZE,
                nextPageToken=checkpoint.next_issue_token,
            )
            response = await self._jira_request(
                "/search/jql",
                method="POST",
                payload=payload.model_dump(mode="json", exclude_none=True),
                retry_transport_failures=True,
            )
            data = native.parse_response(
                _expect(response, operation="scan Jira Sprint fields"),
                native.JiraSearchPage[native.JiraSprintIssue],
            )
            issues = data.issues
            if len(issues) > JIRA_SPRINT_ISSUE_BATCH_SIZE:
                raise _invalid_response("Jira returned too many Sprint-bearing issues.")
            issue_page_is_last = data.isLast
            following = _optional_string(data.nextPageToken)
            if not issue_page_is_last and following is None:
                raise _invalid_response("Jira omitted the next Sprint scan page token.")
            high = _maximum_issue_updated_at(
                [issue.fields.updated for issue in issues],
                current=checkpoint.high,
            )
            records = await self._sprint_records(
                issues=issues,
                sprint_field=sprint_field,
            )
            if checkpoint.item_offset > len(records):
                raise _invalid_response("Jira Sprint scan changed during pagination.")
            page_records = records[
                checkpoint.item_offset : checkpoint.item_offset + limit
            ]
            next_item_offset = checkpoint.item_offset + len(page_records)
            if next_item_offset < len(records):
                next_checkpoint = _SprintCursor(
                    floor=checkpoint.floor,
                    project_offset=checkpoint.project_offset,
                    next_issue_token=checkpoint.next_issue_token,
                    item_offset=next_item_offset,
                    high=high,
                    started_at=checkpoint.started_at,
                    completed=False,
                )
                scan_complete = False
            elif not issue_page_is_last:
                next_checkpoint = _SprintCursor(
                    floor=checkpoint.floor,
                    project_offset=checkpoint.project_offset,
                    next_issue_token=following,
                    item_offset=0,
                    high=high,
                    started_at=checkpoint.started_at,
                    completed=False,
                )
                scan_complete = False
            elif not project_is_last:
                next_checkpoint = _SprintCursor(
                    floor=checkpoint.floor,
                    project_offset=checkpoint.project_offset + 1,
                    next_issue_token=None,
                    item_offset=0,
                    high=high,
                    started_at=checkpoint.started_at,
                    completed=False,
                )
                scan_complete = False
            else:
                next_checkpoint = _completed_sprint_cursor(
                    floor=checkpoint.floor,
                    high=high,
                    started_at=checkpoint.started_at,
                )
                scan_complete = True
            if page_records or scan_complete:
                return SorRecordPage(
                    records=tuple(page_records),
                    next_cursor=_encode_sprint_cursor(next_checkpoint),
                    has_more=not scan_complete,
                )
            checkpoint = next_checkpoint
            scans += 1

        return SorRecordPage(
            records=(),
            next_cursor=_encode_sprint_cursor(checkpoint),
            has_more=True,
        )

    async def _sprint_records(
        self,
        *,
        issues: Sequence[native.JiraSprintIssue],
        sprint_field: str,
    ) -> list[SorExternalRecord]:
        """Canonicalize unique Sprint values without trusting mutable field names."""
        candidates: dict[str, list[native.JiraSprint]] = {}
        for issue in issues:
            for row in _jira_sprint_rows(issue.fields.custom_field(sprint_field)):
                sprint_id = _required_id(row.id, field="Jira sprint ID")
                candidates.setdefault(sprint_id, []).append(row)

        records: list[SorExternalRecord] = []
        for sprint_id in sorted(candidates, key=_numeric_string_key):
            projected: list[SorExternalRecord] = []
            for row in candidates[sprint_id]:
                if _optional_string(row.name) is not None:
                    projected.append(self._external_sprint(row))
            if not projected or any(row != projected[0] for row in projected[1:]):
                records.append(await self._fetch_sprint(sprint_id))
            else:
                records.append(projected[0])
        return records

    async def _fetch_sprint(self, sprint_id: str) -> SorExternalRecord:
        """Read one authoritative Sprint when its issue-field value is incomplete."""
        cached = self._sprint_details.get(sprint_id)
        if cached is not None:
            return cached
        response = await self._agile_request(f"/sprint/{_path_segment(sprint_id)}")
        if response.status_code in {HTTPStatus.NOT_FOUND, HTTPStatus.GONE}:
            raise SorExternalRecordNotFound(
                vendor_object_key=JiraStream.SPRINTS,
                external_id=sprint_id,
            )
        row = native.parse_response(
            _expect(response, operation="read Jira Sprint"),
            native.JiraSprint,
        )
        record = self._external_sprint(row)
        if record.external_id != sprint_id:
            raise _invalid_response("Jira returned the wrong Sprint record.")
        self._sprint_details[sprint_id] = record
        return record

    def _sprint_field_key(self) -> str:
        fields = sorted(
            key
            for key, target in self._issue_agent_keys.items()
            if target == "cycle_external_id"
        )
        if len(fields) != 1:
            raise SorVendorOperationError(
                SorVendorErrorCode.MAPPING_INVALID,
                "The active Jira mapping must select exactly one Sprint field.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return fields[0]

    def _issue_fields(self) -> tuple[str, ...]:
        custom = {
            field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == JiraStream.ISSUES
            and field.vendor_field_key.startswith(native.JIRA_CUSTOM_FIELD_PREFIX)
        }
        return tuple(sorted(_ISSUE_API_FIELDS | custom))

    def _external_directory_record(
        self, row: native.JiraDirectoryRecord, *, position: int | None = None
    ) -> SorExternalRecord:
        if isinstance(row, native.JiraProject):
            record_id = _required_id(row.id, field="Jira project ID")
            key = _optional_string(row.key)
            return SorExternalRecord(
                vendor_object_key=JiraStream.PROJECTS,
                external_id=record_id,
                payload={
                    "key": key,
                    "name": _required_string(row.name, field="Jira project name"),
                    "description": _adf_text(row.description),
                },
                source_url=f"{self._site_origin}/browse/{key}" if key else None,
            )
        if isinstance(row, native.JiraStatus):
            category = row.statusCategory
            native_category = (
                (_optional_string(category.key) or _optional_string(category.name))
                if category
                else None
            )
            return SorExternalRecord(
                vendor_object_key=JiraStream.WORKFLOW_STATES,
                external_id=_required_id(row.id, field="Jira status ID"),
                payload={
                    "name": _required_string(row.name, field="Jira status name"),
                    "native_category": native_category,
                    "normalized_category": _normalized_jira_status(native_category),
                    "order": position,
                },
            )
        if isinstance(row, native.JiraUser):
            display_name = _required_string(row.displayName, field="Jira display name")
            return SorExternalRecord(
                vendor_object_key=JiraStream.USERS,
                external_id=_required_id(row.accountId, field="Jira account ID"),
                payload={
                    "name": display_name,
                    "display_name": display_name,
                    "primary_email": _optional_string(row.emailAddress),
                    "active": row.active,
                    "assignable": None,
                    "avatar_url": _optional_string(row.avatarUrls.large)
                    if row.avatarUrls
                    else None,
                },
            )
        label = _required_string(row.name, field="Jira label")
        return SorExternalRecord(
            vendor_object_key=JiraStream.LABELS,
            external_id=label,
            payload={
                "name": label,
                "description": None,
                "color": None,
                "project_external_id": None,
                "parent_external_id": None,
                "is_group": False,
            },
        )

    def _external_issue(self, row: native.JiraIssue) -> SorExternalRecord:
        record_id = _required_id(row.id, field="Jira issue ID")
        key = _required_string(row.key, field="Jira issue key")
        fields = row.fields
        category = fields.status.statusCategory if fields.status else None
        native_category = (
            _optional_string(category.key) or _optional_string(category.name)
            if category
            else None
        )
        description = fields.description
        updated = _required_datetime(fields.updated, field="Jira issue update time")
        resolution_at = _optional_datetime(fields.resolutiondate)
        payload: dict[str, object] = {
            "key": key,
            "title": _required_string(fields.summary, field="Jira issue summary"),
            "normalized_description": _adf_text(description),
            "source_description": _json_value(description),
            "issue_type": _optional_string(fields.issuetype.name)
            if fields.issuetype
            else None,
            "native_status": _optional_string(fields.status.name)
            if fields.status
            else None,
            "normalized_status": _normalized_jira_status(native_category),
            "priority": _optional_string(fields.priority.name)
            if fields.priority
            else None,
            "project_external_id": _optional_id(fields.project.id)
            if fields.project
            else None,
            "team_external_id": None,
            "assignee_external_id": _optional_id(fields.assignee.accountId)
            if fields.assignee
            else None,
            "reporter_external_id": _optional_id(fields.reporter.accountId)
            if fields.reporter
            else None,
            "estimate": fields.timeoriginalestimate,
            "label_external_ids": _string_list(
                fields.labels, field="Jira issue labels"
            ),
            "parent_external_id": _optional_id(fields.parent.id)
            if fields.parent
            else None,
            "cycle_external_id": None,
            "due_date": fields.duedate,
            "started_at": None,
            "completed_at": (
                resolution_at
                if _normalized_jira_status(native_category)
                is TicketingWorkState.COMPLETED
                else None
            ),
            "cancelled_at": None,
        }
        for field_key in self._issue_fields():
            if field_key.startswith(native.JIRA_CUSTOM_FIELD_PREFIX):
                value = fields.custom_field(field_key)
                if self._issue_agent_keys.get(field_key) == "cycle_external_id":
                    value = _jira_current_sprint_id(value)
                payload[field_key] = value
        return SorExternalRecord(
            vendor_object_key=JiraStream.ISSUES,
            external_id=record_id,
            payload=payload,
            source_created_at=_optional_datetime(fields.created),
            source_updated_at=updated,
            source_revision=updated.isoformat(),
            source_url=f"{self._site_origin}/browse/{key}",
        )

    def _external_sprint(self, row: native.JiraSprint) -> SorExternalRecord:
        record_id = _required_id(row.id, field="Jira sprint ID")
        state = _optional_string(row.state)
        board_id = _optional_id(row.originBoardId) or _optional_id(row.boardId)
        return SorExternalRecord(
            vendor_object_key=JiraStream.SPRINTS,
            external_id=record_id,
            payload={
                "name": _required_string(row.name, field="Jira sprint name"),
                "number": None,
                "description": _optional_string(row.goal),
                "starts_at": row.startDate,
                "ends_at": row.endDate,
                "completed_at": row.completeDate,
                "active": state.casefold() == native.JiraSprintState.ACTIVE
                if state
                else None,
            },
            source_url=(
                f"{self._site_origin}/secure/RapidView.jspa?rapidView={board_id}"
                if board_id
                else None
            ),
        )

    def _external_comment(
        self, row: native.JiraComment, *, issue_id: str
    ) -> SorExternalRecord:
        comment_id = _required_id(row.id, field="Jira comment ID")
        issue_id = _required_id(issue_id, field="Jira comment issue ID")
        body = row.body
        created_at = _required_datetime(
            row.created,
            field="Jira comment creation time",
        )
        updated_at = _optional_datetime(row.updated) or created_at
        return SorExternalRecord(
            vendor_object_key=JiraStream.COMMENTS,
            external_id=_comment_external_id(issue_id, comment_id),
            payload={
                "issue_external_id": issue_id,
                "author_external_id": _optional_id(row.author.accountId)
                if row.author
                else None,
                "normalized_text": (
                    _adf_text(body) or "[Jira comment has no plain-text content]"
                ),
                "source_body": _json_value(body),
                "created_at": created_at,
                "updated_at": updated_at,
            },
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=updated_at.isoformat(),
        )

    def _external_relation(
        self, row: native.JiraIssueLink, *, current_issue_id: str | None = None
    ) -> SorExternalRecord:
        relation = _jira_issue_link_snapshot(row, current_issue_id=current_issue_id)
        return SorExternalRecord(
            vendor_object_key=JiraStream.ISSUE_RELATIONS,
            external_id=relation.relation_id,
            payload={
                "issue_vendor_object_key": JiraStream.ISSUES,
                "from_issue_external_id": relation.from_issue_external_id,
                "to_issue_external_id": relation.to_issue_external_id,
                "canonical_kind": relation.canonical_kind.value,
                "native_kind": relation.native_kind,
            },
            source_url=(
                f"{self._site_origin}/browse/{relation.from_issue_external_id}"
            ),
        )

    async def _create_issue(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Creating a Jira issue cannot target an existing issue."
            )
        issue_fields = _mapped_issue_fields(command)
        required = {
            TicketingIssueWriteField.TITLE,
            TicketingIssueWriteField.PROJECT,
            TicketingIssueWriteField.ISSUE_TYPE,
        }
        if not required.issubset(issue_fields):
            raise _invalid_command(
                "Creating a Jira issue requires title, project_external_id, and issue_type."
            )
        fields = self._write_issue_fields(
            issue_fields,
            operation=SorMutationOperation.CREATE,
        )
        try:
            response = await self._jira_request(
                "/issue",
                method="POST",
                payload=native.JiraIssueWrite(fields=fields).model_dump(
                    mode="json", exclude_unset=True
                ),
                idempotency_key=command.idempotency_key,
            )
            data = native.parse_response(
                _expect_mutation(response, operation="create Jira issue"),
                native.JiraCreatedIssue,
            )
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error, "Jira may have created the issue; reconcile before retrying."
            )
            raise
        issue_id = _required_id(data.id, field="Jira issue ID")
        key = _optional_string(data.key)
        return self._command_result(issue_id, key=key, response=response)

    async def _update_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        fields = self._write_issue_fields(
            _mapped_issue_fields(command),
            operation=SorMutationOperation.UPDATE,
        )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}",
            method="PUT",
            payload=native.JiraIssueWrite(fields=fields).model_dump(
                mode="json", exclude_unset=True
            ),
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="update Jira issue")
        return self._command_result(target_id, response=response)

    async def _transition_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingTransitionCommandPayload):
            raise _invalid_command("Jira transition payload is invalid.")
        status_id = _required_id(
            command.payload.workflow_state_external_id,
            field="Jira status ID",
        )
        available = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/transitions",
        )
        data = native.parse_response(
            _expect(available, operation="list Jira transitions"),
            native.JiraTransitions,
        )
        transition_id = next(
            (
                _optional_string(row.id)
                for row in data.transitions
                if row.to is not None and _optional_id(row.to.id) == status_id
            ),
            None,
        )
        if transition_id is None:
            raise _invalid_command(
                "The requested Jira status is not reachable from this issue."
            )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/transitions",
            method="POST",
            payload=native.JiraTransitionRequest(
                transition=native.JiraIdInput(id=transition_id)
            ).model_dump(mode="json"),
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="transition Jira issue")
        return self._command_result(target_id, response=response)

    async def _assign_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingAssignCommandPayload):
            raise _invalid_command("Jira assignment payload is invalid.")
        assignee = (
            _required_id(command.payload.assignee_external_id, field="Jira account ID")
            if command.payload.assignee_external_id is not None
            else None
        )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/assignee",
            method="PUT",
            payload=native.JiraAssignment(accountId=assignee).model_dump(mode="json"),
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="assign Jira issue")
        return self._command_result(target_id, response=response)

    async def _comment_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingCommentCommandPayload):
            raise _invalid_command("Jira comment payload is invalid.")
        text = command.payload.text
        try:
            response = await self._jira_request(
                f"/issue/{_path_segment(target_id)}/comment",
                method="POST",
                payload=native.JiraCommentWrite(
                    body=_adf_document_or_none(text)
                ).model_dump(mode="json"),
                idempotency_key=command.idempotency_key,
            )
            data = native.parse_response(
                _expect_mutation(response, operation="comment on Jira issue"),
                native.JiraCreatedComment,
            )
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error,
                "Jira may have created the comment; reconcile before retrying.",
            )
            raise
        comment_id = _required_id(data.id, field="Jira comment ID")
        updated_at = _optional_datetime(data.updated) or _required_datetime(
            data.created,
            field="Jira comment creation time",
        )
        return SorCommandResult(
            vendor_object_key=JiraStream.COMMENTS,
            external_id=_comment_external_id(target_id, comment_id),
            external_request_id=_request_id(response),
            source_revision=updated_at.isoformat(),
            response={"status": "accepted"},
        )

    async def _link_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingLinkCommandPayload):
            raise _invalid_command("Jira relationship payload is invalid.")
        related_id = _required_id(
            command.payload.related_issue_external_id,
            field="Jira related issue ID",
        )
        if related_id == target_id:
            raise _invalid_command("A Jira issue cannot link to itself.")
        requested_kind = command.payload.relation_kind
        if requested_kind not in {
            TicketingRelationKind.BLOCKS,
            TicketingRelationKind.BLOCKED_BY,
            TicketingRelationKind.RELATED,
            TicketingRelationKind.DUPLICATE,
        }:
            raise _invalid_command(
                "Jira issue_link supports BLOCKS, BLOCKED_BY, RELATED, or DUPLICATE."
            )
        link_type = await self._resolve_link_type(requested_kind)
        outward_id, inward_id = (
            (related_id, target_id)
            if requested_kind is TicketingRelationKind.BLOCKED_BY
            else (target_id, related_id)
        )
        payload = native.JiraLinkCreate(
            inwardIssue=native.JiraIdInput(id=inward_id),
            outwardIssue=native.JiraIdInput(id=outward_id),
            type=native.JiraIdInput(
                id=_required_id(link_type.id, field="Jira link type ID")
            ),
        )
        try:
            response = await self._jira_request(
                "/issueLink",
                method="POST",
                payload=payload.model_dump(mode="json"),
                idempotency_key=command.idempotency_key,
            )
            _expect_mutation(response, operation="link Jira issues")
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error,
                "Jira may have created the issue link; reconcile before retrying.",
            )
            raise

        canonical_kind = (
            TicketingRelationKind.BLOCKS
            if requested_kind is TicketingRelationKind.BLOCKED_BY
            else requested_kind
        )
        expected_from, expected_to = outward_id, inward_id
        if (
            canonical_kind is TicketingRelationKind.RELATED
            and expected_from > expected_to
        ):
            expected_from, expected_to = expected_to, expected_from
        relation_id = await self._find_issue_link(
            issue_id=target_id,
            canonical_kind=canonical_kind,
            from_issue_id=expected_from,
            to_issue_id=expected_to,
        )
        if relation_id is None:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                "Jira accepted the issue link but did not expose its ID yet; reconcile "
                "before retrying.",
                recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
            )
        return SorCommandResult(
            vendor_object_key=JiraStream.ISSUE_RELATIONS,
            external_id=relation_id,
            external_request_id=_request_id(response),
            response={"status": "accepted"},
        )

    async def _resolve_link_type(
        self,
        relation_kind: TicketingRelationKind,
    ) -> native.JiraLinkType:
        response = await self._jira_request("/issueLinkType")
        data = native.parse_response(
            _expect(response, operation="list Jira issue-link types"),
            native.JiraLinkTypes,
        )
        rows = data.issueLinkTypes
        matches = [row for row in rows if _jira_link_type_matches(row, relation_kind)]
        if not matches:
            raise _invalid_command(
                f"The Jira site has no link type compatible with {relation_kind.value}."
            )
        return min(
            matches,
            key=lambda row: (
                _required_string(row.name, field="Jira link type name").casefold(),
                _required_id(row.id, field="Jira link type ID"),
            ),
        )

    async def _find_issue_link(
        self,
        *,
        issue_id: str,
        canonical_kind: TicketingRelationKind,
        from_issue_id: str,
        to_issue_id: str,
    ) -> str | None:
        response = await self._jira_request(
            f"/issue/{_path_segment(issue_id)}",
            query=native.JiraIssueQuery(fields=["issuelinks", "updated"]).model_dump(
                mode="json"
            ),
        )
        issue = native.parse_response(
            _expect(response, operation="resolve created Jira issue link"),
            native.JiraLinkedIssue,
        )
        for row in issue.fields.issuelinks:
            relation = _jira_issue_link_snapshot(row, current_issue_id=issue_id)
            if (
                relation.canonical_kind is canonical_kind
                and relation.from_issue_external_id == from_issue_id
                and relation.to_issue_external_id == to_issue_id
            ):
                return relation.relation_id
        return None

    async def _change_label(
        self,
        target_id: str,
        command: SorCommandRequest,
        *,
        action: native.JiraLabelAction,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingLabelCommandPayload):
            raise _invalid_command("Jira label payload is invalid.")
        label = command.payload.label_external_id
        operation = (
            native.JiraLabelAdd(add=label)
            if action is native.JiraLabelAction.ADD
            else native.JiraLabelRemove(remove=label)
        )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}",
            method="PUT",
            payload=native.JiraLabelRequest(
                update=native.JiraLabelUpdates(labels=[operation])
            ).model_dump(mode="json"),
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="change Jira issue label")
        return self._command_result(target_id, response=response)

    def _write_issue_fields(
        self,
        payload: Mapping[str, object],
        *,
        operation: SorMutationOperation,
    ) -> native.JiraWriteFields:
        if not payload:
            raise _invalid_command("A Jira issue mutation requires at least one field.")
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == JiraStream.ISSUES and field.writable
        }
        allowed = set(writable) | set(TicketingIssueWriteField)
        unknown = set(payload) - allowed
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_FIELD_NOT_WRITABLE,
                "The Jira mutation contains fields absent from the writable mapping.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        result: dict[str, object] = {}
        mappings: Mapping[
            TicketingIssueWriteField,
            tuple[
                native.JiraIssueWriteField,
                Callable[[object], SorJsonValue | native.JiraRequest],
            ],
        ] = {
            TicketingIssueWriteField.TITLE: (
                native.JiraIssueWriteField.SUMMARY,
                _required_command_string,
            ),
            TicketingIssueWriteField.DESCRIPTION: (
                native.JiraIssueWriteField.DESCRIPTION,
                _adf_document_or_none,
            ),
            TicketingIssueWriteField.ISSUE_TYPE: (
                native.JiraIssueWriteField.ISSUE_TYPE,
                lambda value: native.JiraNameInput(
                    name=_required_command_string(value)
                ),
            ),
            TicketingIssueWriteField.PRIORITY: (
                native.JiraIssueWriteField.PRIORITY,
                lambda value: None
                if value is None
                else native.JiraNameInput(name=_required_command_string(value)),
            ),
            TicketingIssueWriteField.PROJECT: (
                native.JiraIssueWriteField.PROJECT,
                lambda value: native.JiraIdInput(id=_required_command_string(value)),
            ),
            TicketingIssueWriteField.ESTIMATE: (
                native.JiraIssueWriteField.ESTIMATE,
                _optional_positive_integer,
            ),
            TicketingIssueWriteField.LABELS: (
                native.JiraIssueWriteField.LABELS,
                _command_string_list,
            ),
            TicketingIssueWriteField.PARENT: (
                native.JiraIssueWriteField.PARENT,
                lambda value: None
                if value is None
                else native.JiraIdInput(id=_required_command_string(value)),
            ),
            TicketingIssueWriteField.DUE_DATE: (
                native.JiraIssueWriteField.DUE_DATE,
                _optional_command_string,
            ),
        }
        for key, value in payload.items():
            try:
                canonical_key = TicketingIssueWriteField(key)
            except ValueError:
                result[writable[key]] = value
                continue
            target, transform = mappings[canonical_key]
            try:
                transformed = transform(value)
            except ValidationError as error:
                raise _invalid_command(
                    "The Jira request contains invalid field values."
                ) from error
            result[target] = (
                transformed.model_dump(mode="json")
                if isinstance(transformed, native.JiraRequest)
                else transformed
            )
        if operation is SorMutationOperation.CREATE:
            for field in (
                native.JiraIssueWriteField.SUMMARY,
                native.JiraIssueWriteField.PROJECT,
                native.JiraIssueWriteField.ISSUE_TYPE,
            ):
                if field not in result:
                    raise _invalid_command(
                        "Creating a Jira issue requires title, project_external_id, and issue_type."
                    )
        return native.parse_request(result, native.JiraWriteFields)

    def _command_result(
        self,
        issue_id: str,
        *,
        response: SorJsonResponse,
        key: str | None = None,
    ) -> SorCommandResult:
        return SorCommandResult(
            vendor_object_key=JiraStream.ISSUES,
            external_id=issue_id,
            external_request_id=_request_id(response),
            source_url=f"{self._site_origin}/browse/{key}" if key else None,
            response={"status": "accepted"},
        )


def create_jira_adapter(context: SorAdapterContext) -> JiraTicketingAdapter:
    """Construct the production Jira adapter for the explicit registry."""
    return JiraTicketingAdapter(context)


def _jira_custom_field(row: native.JiraField) -> SorDiscoveredField:
    key = _required_id(row.id, field="Jira custom field ID")
    if not key.startswith("customfield_"):
        raise _invalid_response("Jira returned an invalid custom field ID.")
    schema = row.field_schema
    vendor_type = _optional_string(schema.custom) if schema else None
    data_types: dict[str, SorFieldDataType] = {
        native.JiraFieldType.ARRAY: SorFieldDataType.STRING_ARRAY,
        native.JiraFieldType.DATE: SorFieldDataType.DATE,
        native.JiraFieldType.DATETIME: SorFieldDataType.TIMESTAMP,
        native.JiraFieldType.NUMBER: SorFieldDataType.DECIMAL,
        native.JiraFieldType.OPTION: SorFieldDataType.TEXT,
        native.JiraFieldType.STRING: SorFieldDataType.TEXT,
        native.JiraFieldType.USER: SorFieldDataType.REFERENCE,
    }
    data_type = (
        SorFieldDataType.REFERENCE
        if vendor_type == JIRA_SPRINT_FIELD_TYPE
        else data_types.get(
            (_optional_string(schema.type) if schema else None) or "",
            SorFieldDataType.BOUNDED_JSON,
        )
    )
    return _field(
        key,
        _required_string(row.name, field="Jira custom field name"),
        data_type,
        writable=True,
        description=_optional_string(row.description),
        group="Jira custom fields",
        vendor_type=vendor_type,
    )


def _jira_current_sprint_id(value: object) -> str | None:
    """Select the issue's current sprint from Jira's historical Sprint field."""
    if value is None or value == []:
        return None
    values = value if isinstance(value, (list, tuple)) else (value,)
    candidates: list[native.JiraSprintReference] = []
    for item in values:
        sprint_id: str | None
        state: str | None
        if isinstance(item, Mapping):
            reference = native.parse_response(item, native.JiraSprintReference)
            sprint_id = _optional_id(reference.id)
            state = _optional_string(reference.state)
        elif isinstance(item, str):
            stripped = item.strip()
            sprint_id = stripped if stripped.isdigit() else None
            if sprint_id is None:
                match = re.search(r"(?:^|[,\[])\s*id=(\d+)(?:,|\])", stripped)
                sprint_id = match.group(1) if match is not None else None
            state_match = re.search(r"(?:^|[,\[])\s*state=([^,\]]+)", stripped)
            state = state_match.group(1).strip() if state_match is not None else None
        elif isinstance(item, int) and not isinstance(item, bool):
            sprint_id = str(item)
            state = None
        else:
            raise _invalid_response("Jira returned a malformed Sprint custom field.")
        if sprint_id is None:
            raise _invalid_response("Jira returned a Sprint without an ID.")
        candidates.append(
            native.JiraSprintReference(
                id=_required_id(sprint_id, field="Jira sprint ID"),
                state=state.casefold() if state is not None else None,
            )
        )

    for preferred_state in (
        native.JiraSprintState.ACTIVE,
        native.JiraSprintState.FUTURE,
    ):
        for reference in reversed(candidates):
            if reference.state == preferred_state:
                return _required_id(reference.id, field="Jira sprint ID")
    return _required_id(candidates[-1].id, field="Jira sprint ID")


def _jira_sprint_rows(value: object) -> tuple[native.JiraSprint, ...]:
    """Normalize Jira's current and legacy Sprint-field representations."""
    if value is None or value == []:
        return ()
    values = value if isinstance(value, (list, tuple)) else (value,)
    rows: list[native.JiraSprint] = []
    for item in values:
        if isinstance(item, Mapping):
            rows.append(native.parse_response(item, native.JiraSprint))
            continue
        if isinstance(item, int) and not isinstance(item, bool):
            rows.append(
                native.JiraSprint(id=_required_id(str(item), field="Jira sprint ID"))
            )
            continue
        if not isinstance(item, str):
            raise _invalid_response("Jira returned a malformed Sprint custom field.")
        stripped = item.strip()
        if stripped.isdigit():
            rows.append(
                native.JiraSprint(id=_required_id(stripped, field="Jira sprint ID"))
            )
            continue
        sprint_id = _legacy_sprint_field(stripped, native.JiraLegacySprintField.ID)
        if sprint_id is None or not sprint_id.isdigit():
            raise _invalid_response("Jira returned a Sprint without an ID.")
        rows.append(
            native.JiraSprint(
                id=_required_id(sprint_id, field="Jira sprint ID"),
                name=_legacy_sprint_field(stripped, native.JiraLegacySprintField.NAME),
                state=_legacy_sprint_field(
                    stripped, native.JiraLegacySprintField.STATE
                ),
                goal=_legacy_sprint_field(stripped, native.JiraLegacySprintField.GOAL),
                startDate=_legacy_sprint_field(
                    stripped, native.JiraLegacySprintField.START_DATE
                ),
                endDate=_legacy_sprint_field(
                    stripped, native.JiraLegacySprintField.END_DATE
                ),
                completeDate=_legacy_sprint_field(
                    stripped, native.JiraLegacySprintField.COMPLETE_DATE
                ),
                boardId=_optional_id(
                    _legacy_sprint_field(
                        stripped, native.JiraLegacySprintField.BOARD_ID
                    )
                ),
            )
        )
    return tuple(rows)


def _legacy_sprint_field(value: str, key: native.JiraLegacySprintField) -> str | None:
    match = re.search(
        rf"(?:^|[,\[]){re.escape(key)}=(.*?)(?=,[A-Za-z][A-Za-z0-9]*=|\]$)",
        value,
    )
    if match is None:
        return None
    field = match.group(1).strip()
    return None if field in {"", "<null>"} else field


def _numeric_string_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_FAILED,
            f"Jira refused authorization while attempting to {operation}.",
            recovery=(
                SorRecoveryPolicy.REFRESH_AND_RETRY
                if response.status_code == HTTPStatus.UNAUTHORIZED
                else SorRecoveryPolicy.REAUTH_REQUIRED
            ),
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Jira rate limited the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            "Jira could not complete the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if not response.ok:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
            f"Jira rejected the request while attempting to {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return response.data


def _expect_mutation(response: SorJsonResponse, *, operation: str) -> object:
    value = _expect(response, operation=operation)
    if response.status_code not in {
        HTTPStatus.OK,
        HTTPStatus.CREATED,
        HTTPStatus.NO_CONTENT,
    }:
        raise _invalid_response("Jira returned an unexpected mutation status.")
    return value


def _decode_issue_cursor(value: str | None) -> _IssueCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _IssueCursor(
            floor=None,
            project_offset=0,
            next_token=None,
            high=None,
            started_at=now,
            completed=False,
        )
    header = _parse_cursor(value, _CursorHeader, stream=JiraStream.ISSUES)
    if header.stream is not JiraStream.ISSUES:
        raise _invalid_cursor("issue")
    if header.v == JIRA_CURSOR_VERSION:
        legacy = _parse_cursor(
            value, _LegacyIssueCursorEnvelope, stream=JiraStream.ISSUES
        )
        return _IssueCursor(
            floor=legacy.floor,
            project_offset=0,
            next_token=None,
            high=None,
            started_at=now,
            completed=False,
        )
    saved = _parse_cursor(value, _IssueCursorEnvelope, stream=JiraStream.ISSUES)
    if saved.completed:
        if (
            saved.project_offset != 0
            or saved.next_token is not None
            or saved.high is not None
        ):
            raise _invalid_cursor("issue")
        return _IssueCursor(
            floor=saved.floor,
            project_offset=0,
            next_token=None,
            high=None,
            started_at=now,
            completed=False,
        )
    if saved.next_token is not None and saved.high is None:
        raise _invalid_cursor("issue")
    return _IssueCursor(
        floor=saved.floor,
        project_offset=saved.project_offset,
        next_token=saved.next_token,
        high=saved.high,
        started_at=saved.started_at,
        completed=False,
    )


def _encode_issue_cursor(cursor: _IssueCursor) -> str:
    return _encode_cursor(
        _IssueCursorEnvelope(
            completed=cursor.completed,
            floor=cursor.floor,
            high=cursor.high,
            next_token=cursor.next_token,
            project_offset=cursor.project_offset,
            started_at=cursor.started_at,
            stream=JiraStream.ISSUES,
            v=JIRA_ISSUE_CURSOR_VERSION,
        )
    )


def _completed_issue_cursor(
    *,
    floor: datetime | None,
    high: datetime | None,
    started_at: datetime,
) -> _IssueCursor:
    candidate = (high or started_at) - JIRA_RECONCILIATION_OVERLAP
    if floor is not None and floor > candidate:
        candidate = floor
    return _IssueCursor(
        floor=candidate,
        project_offset=0,
        next_token=None,
        high=None,
        started_at=started_at,
        completed=True,
    )


def _decode_offset_cursor(value: str | None, *, stream_key: str) -> int:
    if value is None:
        return 0
    saved = _parse_cursor(value, _OffsetCursorEnvelope, stream=stream_key)
    if saved.v != JIRA_CURSOR_VERSION or saved.stream != stream_key:
        raise _invalid_cursor(stream_key)
    return saved.offset


def _encode_offset_cursor(offset: int, *, stream_key: str) -> str:
    return _encode_cursor(
        _OffsetCursorEnvelope(
            offset=offset, stream=JiraStream(stream_key), v=JIRA_CURSOR_VERSION
        )
    )


def _decode_comment_cursor(value: str | None) -> _CommentCursor:
    stream_key = JiraStream.COMMENTS
    initial = _CommentCursor(
        project_offset=0,
        next_issue_token=None,
        issue_ids=(),
        item_offsets=(),
        item_stops=(),
        issue_page_is_last=False,
        current_project_is_last=False,
    )
    if value is None:
        return initial
    header = _parse_cursor(value, _CursorHeader, stream=stream_key)
    if header.stream != stream_key:
        raise _invalid_cursor(stream_key)
    if header.v in {
        JIRA_CURSOR_VERSION,
        JIRA_ISSUE_CURSOR_VERSION,
        JIRA_NESTED_CURSOR_VERSION,
    }:
        return initial
    saved = _parse_cursor(value, _CommentCursorEnvelope, stream=stream_key)
    next_issue_token = saved.next_issue_token
    issue_ids = saved.issue_ids
    item_offsets = saved.item_offsets
    item_stops = saved.item_stops
    issue_page_is_last = saved.issue_page_is_last
    project_is_last = saved.current_project_is_last
    if (
        len(issue_ids) != len(item_offsets)
        or len(issue_ids) != len(item_stops)
        or len(issue_ids) > 2 * JIRA_COMMENT_ISSUE_BATCH_SIZE
        or any(offset < 0 for offset in item_offsets)
        or any(stop <= 0 for stop in item_stops)
    ):
        raise _invalid_cursor(stream_key)
    ranges = tuple(zip(issue_ids, item_offsets, item_stops, strict=True))
    if any(offset >= stop for _issue_id, offset, stop in ranges):
        raise _invalid_cursor(stream_key)
    if len(ranges) != len(set(ranges)):
        raise _invalid_cursor(stream_key)
    if not issue_ids:
        if issue_page_is_last or project_is_last:
            raise _invalid_cursor(stream_key)
    elif issue_page_is_last and next_issue_token is not None:
        raise _invalid_cursor(stream_key)
    elif not issue_page_is_last and next_issue_token is None:
        raise _invalid_cursor(stream_key)
    return _CommentCursor(
        project_offset=saved.project_offset,
        next_issue_token=next_issue_token,
        issue_ids=issue_ids,
        item_offsets=item_offsets,
        item_stops=item_stops,
        issue_page_is_last=issue_page_is_last,
        current_project_is_last=project_is_last,
    )


def _encode_comment_cursor(cursor: _CommentCursor) -> str:
    return _encode_cursor(
        _CommentCursorEnvelope(
            current_project_is_last=cursor.current_project_is_last,
            issue_ids=cursor.issue_ids,
            issue_page_is_last=cursor.issue_page_is_last,
            item_offsets=cursor.item_offsets,
            item_stops=cursor.item_stops,
            next_issue_token=cursor.next_issue_token,
            project_offset=cursor.project_offset,
            stream=JiraStream.COMMENTS,
            v=JIRA_COMMENT_CURSOR_VERSION,
        )
    )


def _advance_comment_cursor(cursor: _CommentCursor) -> _CommentCursor | None:
    if cursor.issue_page_is_last and cursor.current_project_is_last:
        return None
    return _CommentCursor(
        project_offset=(
            cursor.project_offset + 1
            if cursor.issue_page_is_last
            else cursor.project_offset
        ),
        next_issue_token=(
            None if cursor.issue_page_is_last else cursor.next_issue_token
        ),
        issue_ids=(),
        item_offsets=(),
        item_stops=(),
        issue_page_is_last=False,
        current_project_is_last=False,
    )


def _decode_relation_cursor(value: str | None) -> _RelationCursor:
    initial = _RelationCursor(project_offset=0, next_issue_token=None)
    if value is None:
        return initial
    header = _parse_cursor(value, _CursorHeader, stream=JiraStream.ISSUE_RELATIONS)
    if header.stream is not JiraStream.ISSUE_RELATIONS:
        raise _invalid_cursor(JiraStream.ISSUE_RELATIONS)
    if header.v in {
        JIRA_CURSOR_VERSION,
        JIRA_ISSUE_CURSOR_VERSION,
        JIRA_NESTED_CURSOR_VERSION,
    }:
        return initial
    saved = _parse_cursor(
        value, _RelationCursorEnvelope, stream=JiraStream.ISSUE_RELATIONS
    )
    return _RelationCursor(
        project_offset=saved.project_offset,
        next_issue_token=saved.next_issue_token,
    )


def _encode_relation_cursor(cursor: _RelationCursor) -> str:
    return _encode_cursor(
        _RelationCursorEnvelope(
            next_issue_token=cursor.next_issue_token,
            project_offset=cursor.project_offset,
            stream=JiraStream.ISSUE_RELATIONS,
            v=JIRA_RELATION_CURSOR_VERSION,
        )
    )


def _issue_sync_jql(project_id: str, *, floor: datetime | None) -> str:
    clause = f"project = {project_id}"
    if floor is not None:
        value = floor.strftime("%Y-%m-%d %H:%M")
        clause = f'{clause} AND updated >= "{value}"'
    return f"{clause} ORDER BY updated ASC, id ASC"


def _sprint_issue_jql(project_id: str, *, floor: datetime | None) -> str:
    clause = f"project = {project_id} AND sprint is not EMPTY"
    if floor is not None:
        value = floor.strftime("%Y-%m-%d %H:%M")
        clause = f'{clause} AND updated >= "{value}"'
    return f"{clause} ORDER BY updated ASC, id ASC"


def _issue_scan_jql(project_id: str) -> str:
    return f"project = {project_id} ORDER BY id ASC"


def _deduplicate_child_records(
    records: Sequence[SorExternalRecord],
    *,
    stream_key: str,
) -> list[SorExternalRecord]:
    """Collapse identical Jira child copies without hiding conflicting payloads."""
    unique: dict[tuple[str, str], SorExternalRecord] = {}
    for record in records:
        identity = (record.vendor_object_key, record.external_id)
        existing = unique.get(identity)
        if existing is not None and existing != record:
            raise _invalid_response(
                f"Jira returned conflicting copies of one {stream_key} record."
            )
        unique[identity] = record
    return list(unique.values())


def _decode_sprint_cursor(value: str | None) -> _SprintCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _SprintCursor(
            floor=None,
            project_offset=0,
            next_issue_token=None,
            item_offset=0,
            high=None,
            started_at=now,
            completed=False,
        )
    header = _parse_cursor(value, _CursorHeader, stream=JiraStream.SPRINTS)
    if header.stream is not JiraStream.SPRINTS:
        raise _invalid_cursor(JiraStream.SPRINTS)
    if header.v == JIRA_CURSOR_VERSION:
        _parse_cursor(value, _LegacySprintCursorEnvelope, stream=JiraStream.SPRINTS)
        # V1 enumerated boards. Restarting is safe because projection is idempotent.
        return _SprintCursor(
            floor=None,
            project_offset=0,
            next_issue_token=None,
            item_offset=0,
            high=None,
            started_at=now,
            completed=False,
        )
    saved = _parse_cursor(value, _SprintCursorEnvelope, stream=JiraStream.SPRINTS)
    if saved.completed:
        if (
            saved.project_offset != 0
            or saved.next_issue_token is not None
            or saved.item_offset != 0
            or saved.high is not None
        ):
            raise _invalid_cursor(JiraStream.SPRINTS)
        return _SprintCursor(
            floor=saved.floor,
            project_offset=0,
            next_issue_token=None,
            item_offset=0,
            high=None,
            started_at=now,
            completed=False,
        )
    if saved.next_issue_token is not None and saved.high is None:
        raise _invalid_cursor(JiraStream.SPRINTS)
    return _SprintCursor(
        floor=saved.floor,
        project_offset=saved.project_offset,
        next_issue_token=saved.next_issue_token,
        item_offset=saved.item_offset,
        high=saved.high,
        started_at=saved.started_at,
        completed=False,
    )


def _encode_sprint_cursor(cursor: _SprintCursor) -> str:
    return _encode_cursor(
        _SprintCursorEnvelope(
            completed=cursor.completed,
            floor=cursor.floor,
            high=cursor.high,
            item_offset=cursor.item_offset,
            next_issue_token=cursor.next_issue_token,
            project_offset=cursor.project_offset,
            started_at=cursor.started_at,
            stream=JiraStream.SPRINTS,
            v=JIRA_SPRINT_CURSOR_VERSION,
        )
    )


def _completed_sprint_cursor(
    *,
    floor: datetime | None,
    high: datetime | None,
    started_at: datetime,
) -> _SprintCursor:
    candidate = (high or started_at) - JIRA_RECONCILIATION_OVERLAP
    if floor is not None and floor > candidate:
        candidate = floor
    return _SprintCursor(
        floor=candidate,
        project_offset=0,
        next_issue_token=None,
        item_offset=0,
        high=None,
        started_at=started_at,
        completed=True,
    )


def _maximum_issue_updated_at(
    timestamps: Sequence[str],
    *,
    current: datetime | None,
) -> datetime | None:
    result = current
    for timestamp in timestamps:
        updated = _required_datetime(timestamp, field="Jira issue update time")
        if result is None or updated > result:
            result = updated
    return result


def _invalid_cursor(stream_key: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        f"The Jira {stream_key} cursor is invalid.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _require_stream(value: str, *, selected: tuple[str, ...]) -> JiraStream:
    if value not in _STREAM_ENTITY or value not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
            "The requested Jira stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return JiraStream(value)


def _jira_site_origin(value: str | None) -> str:
    normalized = _normalized_origin(value)
    if normalized is None or not normalized.removeprefix("https://").endswith(
        f".{ATLASSIAN_INSTANCE_HOST_SUFFIX}"
    ):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SITE_INVALID,
            "Jira Cloud requires an exact HTTPS *.atlassian.net site URL.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return normalized


def _normalized_origin(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().rstrip("/").lower()
    if not normalized.startswith("https://") or "/" in normalized[8:]:
        return None
    return normalized


def _path_segment(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", normalized):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
            "A Jira source identifier is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return normalized


def _comment_external_id(issue_id: str, comment_id: str) -> str:
    return f"{_path_segment(issue_id)}:{_path_segment(comment_id)}"


def _split_comment_external_id(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_IDENTIFIER_INVALID,
            "A Jira comment identity is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _path_segment(parts[0]), _path_segment(parts[1])


def _jira_issue_link_snapshot(
    row: native.JiraIssueLink,
    *,
    current_issue_id: str | None = None,
) -> _JiraIssueLinkSnapshot:
    current_id = _optional_id(current_issue_id)
    inward_id = _optional_id(row.inwardIssue.id) if row.inwardIssue else None
    outward_id = _optional_id(row.outwardIssue.id) if row.outwardIssue else None
    if inward_id is None and current_id is not None and outward_id is not None:
        inward_id = current_id
    if outward_id is None and current_id is not None and inward_id is not None:
        outward_id = current_id
    if inward_id is None or outward_id is None:
        raise _invalid_response("Jira issue-link endpoints are incomplete.")
    relation_type = row.type
    canonical_kind = _jira_relation_kind_from_type(relation_type)
    from_id, to_id = outward_id, inward_id
    if canonical_kind is TicketingRelationKind.RELATED and from_id > to_id:
        from_id, to_id = to_id, from_id
    return _JiraIssueLinkSnapshot(
        relation_id=_required_id(row.id, field="Jira issue-link ID"),
        from_issue_external_id=from_id,
        to_issue_external_id=to_id,
        canonical_kind=canonical_kind,
        native_kind=_required_string(
            relation_type.name,
            field="Jira issue-link type name",
        ),
    )


def _jira_relation_kind_from_type(
    link_type: native.JiraLinkType,
) -> TicketingRelationKind:
    vocabulary = " ".join(
        value.casefold()
        for value in (
            _optional_string(link_type.name),
            _optional_string(link_type.inward),
            _optional_string(link_type.outward),
        )
        if value
    )
    if "duplicat" in vocabulary:
        return TicketingRelationKind.DUPLICATE
    if "block" in vocabulary:
        return TicketingRelationKind.BLOCKS
    return TicketingRelationKind.RELATED


def _jira_link_type_matches(
    link_type: native.JiraLinkType,
    relation_kind: TicketingRelationKind,
) -> bool:
    normalized = _jira_relation_kind_from_type(link_type)
    if relation_kind is TicketingRelationKind.BLOCKED_BY:
        relation_kind = TicketingRelationKind.BLOCKS
    if normalized is not relation_kind:
        return False
    if relation_kind is not TicketingRelationKind.RELATED:
        return True
    vocabulary = " ".join(
        value.casefold()
        for value in (
            _optional_string(link_type.name),
            _optional_string(link_type.inward),
            _optional_string(link_type.outward),
        )
        if value
    )
    return "relat" in vocabulary


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This Jira action requires an existing issue.")
    return _required_id(command.target_external_id, field="Jira issue ID")


def _mapped_issue_fields(command: SorCommandRequest) -> Mapping[str, object]:
    if not isinstance(command.payload, TicketingMappedFieldsCommandPayload):
        raise _invalid_command("Jira issue field payload is invalid.")
    return command.payload.fields


def _required_command_string(value: object, *, field: str = "Jira field") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 32_768:
        raise _invalid_command(f"{field} must be non-empty text.")
    return value.strip()


def _optional_command_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 32_768:
        raise _invalid_command("The Jira field must be text or null.")
    return value


def _optional_positive_integer(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_command("Jira estimate must be a non-negative integer or null.")
    return value


def _command_string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or len(value) > 1_000:
        raise _invalid_command("Jira labels must be a bounded list of text values.")
    result = [_required_command_string(item, field="Jira label") for item in value]
    if len(result) != len(set(result)):
        raise _invalid_command("Jira labels cannot contain duplicates.")
    return result


def _adf_document_or_none(value: object) -> native.JiraAdfDocument | None:
    if value is None:
        return None
    text = _required_command_string(value, field="Jira description")
    return native.JiraAdfDocument(
        content=[native.JiraAdfParagraph(content=[native.JiraAdfText(text=text)])]
    )


_ADF_BLOCK_NODES = frozenset(
    {
        native.JiraAdfNodeKind.BLOCKQUOTE,
        native.JiraAdfNodeKind.BULLET_LIST,
        native.JiraAdfNodeKind.HEADING,
        native.JiraAdfNodeKind.LIST_ITEM,
        native.JiraAdfNodeKind.ORDERED_LIST,
        native.JiraAdfNodeKind.PARAGRAPH,
    }
)


def _adf_text(value: SorJsonValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    parts: list[str] = []

    def walk(node: SorJsonValue) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, Mapping):
            return
        node_type = node.get(native.JiraAdfField.TYPE)
        text = node.get(native.JiraAdfField.TEXT)
        if isinstance(text, str):
            parts.append(text)
        if node_type == native.JiraAdfNodeKind.HARD_BREAK:
            parts.append("\n")
        walk(node.get(native.JiraAdfField.CONTENT))
        if node_type in _ADF_BLOCK_NODES:
            parts.append("\n")

    walk(value)
    result = "".join(parts).strip()
    return result[:262_144] or None


def _normalized_jira_status(value: str | None) -> TicketingWorkState | None:
    if value is None:
        return None
    normalized = value.strip().casefold().replace("_", " ")
    return {
        "new": TicketingWorkState.UNSTARTED,
        "to do": TicketingWorkState.UNSTARTED,
        "indeterminate": TicketingWorkState.STARTED,
        "in progress": TicketingWorkState.STARTED,
        "done": TicketingWorkState.COMPLETED,
        "complete": TicketingWorkState.COMPLETED,
    }.get(normalized, TicketingWorkState.UNKNOWN)


def _request_id(response: SorJsonResponse) -> str | None:
    for name in ("atl-traceid", "x-arequestid", "x-request-id"):
        values = response.header_values(name)
        if values:
            return values[0][:512]
    return None


def _raise_unknown_create(error: SorVendorOperationError, message: str) -> None:
    if error.code in {
        SorVendorErrorCode.VENDOR_TIMEOUT,
        SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
        SorVendorErrorCode.VENDOR_SERVER_FAILED,
    }:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
            message,
            recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
        ) from error


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CREDENTIALS_INVALID,
            "The Jira credential is unavailable.",
            recovery=SorRecoveryPolicy.REAUTH_REQUIRED,
        )
    return value


def _object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} is not an object.")
    return value


def _optional_object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _invalid_response(f"{field} is not a list of objects.")
    return value


def _string_list(value: object, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise _invalid_response(f"{field} is not a list of text values.")
    if len(value) != len(set(value)):
        raise _invalid_response(f"{field} contains duplicates.")
    return value


def _required_id(value: object, *, field: str) -> str:
    if isinstance(value, bool):
        raise _invalid_response(f"{field} is missing.")
    if isinstance(value, int) and value >= 0:
        result = str(value)
    else:
        result = _required_string(value, field=field)
    if len(result) > 512:
        raise _invalid_response(f"{field} is too long.")
    return result


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    return _required_id(value, field="Jira identifier")


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response(f"{field} is missing.")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_datetime(value: object, *, field: str) -> datetime:
    result = _optional_datetime(value)
    if result is None:
        raise _invalid_response(f"{field} is missing or invalid.")
    return result


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise _invalid_response("Jira due date is invalid.") from error
    raise _invalid_response("Jira due date is invalid.")


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _invalid_response("Jira numeric value is invalid.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _invalid_response("Jira numeric value is invalid.") from error
    if not result.is_finite():
        raise _invalid_response("Jira numeric value is invalid.")
    return result


def _optional_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    decimal = _optional_decimal(value)
    if decimal is None or decimal != decimal.to_integral_value():
        raise _invalid_response(f"{field} is invalid.")
    return int(decimal)


def _required_nonnegative_integer(value: object, *, field: str) -> int:
    result = _optional_integer(value, field=field)
    if result is None or result < 0:
        raise _invalid_response(f"{field} is missing or invalid.")
    return result


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"{field} is missing or invalid.")
    return value


def _optional_boolean(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _invalid_response("Jira boolean value is invalid.")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(_string_list(value, field="Jira label IDs"))


def _json_value(value: object) -> SorJsonValue:
    try:
        return require_json_value(value)
    except ValueError as error:
        raise _invalid_response(
            "Jira source content is not JSON-compatible."
        ) from error


def _webhook_events(selected_objects: tuple[str, ...]) -> tuple[JiraWebhookEvent, ...]:
    """Return the one bounded dynamic-webhook event set Jira supports."""
    events: list[JiraWebhookEvent] = []
    if (
        JiraStream.ISSUES in selected_objects
        or JiraStream.ISSUE_RELATIONS in selected_objects
    ):
        events.extend(
            (
                JiraWebhookEvent.ISSUE_CREATED,
                JiraWebhookEvent.ISSUE_UPDATED,
                JiraWebhookEvent.ISSUE_DELETED,
            )
        )
    if JiraStream.COMMENTS in selected_objects:
        events.extend(
            (
                JiraWebhookEvent.COMMENT_CREATED,
                JiraWebhookEvent.COMMENT_UPDATED,
                JiraWebhookEvent.COMMENT_DELETED,
            )
        )
    if JiraStream.SPRINTS in selected_objects:
        events.extend(
            (
                JiraWebhookEvent.SPRINT_CREATED,
                JiraWebhookEvent.SPRINT_UPDATED,
                JiraWebhookEvent.SPRINT_CLOSED,
                JiraWebhookEvent.SPRINT_DELETED,
                JiraWebhookEvent.SPRINT_STARTED,
            )
        )
    return tuple(events)


def _webhook_id(value: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
            "The Jira webhook subscription identity is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
    if result <= 0:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_WEBHOOK_INVALID,
            "The Jira webhook subscription identity is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return result


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            normalized = value.strip()
            return normalized or None
    return None


def _jira_delivery_id(headers: Mapping[str, str]) -> str:
    delivery_id = _header(headers, JIRA_WEBHOOK_DELIVERY_HEADER)
    if (
        delivery_id is None
        or not 1 <= len(delivery_id) <= JIRA_WEBHOOK_IDENTIFIER_MAX_LENGTH
    ):
        raise SorWebhookPayloadError("Jira webhook delivery ID is invalid.")
    return delivery_id


def _jira_webhook_record_identity(
    event_type: str,
    payload: JiraWebhookDelivery,
) -> tuple[str | None, str | None]:
    if event_type.startswith(JiraWebhookEventFamily.ISSUE):
        if payload.issue is None:
            raise SorWebhookPayloadError("Jira webhook issue is invalid.")
        return JiraStream.ISSUES, payload.issue.id
    if event_type.startswith(JiraWebhookEventFamily.COMMENT):
        if payload.issue is None or payload.comment is None:
            raise SorWebhookPayloadError("Jira webhook comment identity is invalid.")
        return JiraStream.COMMENTS, f"{payload.issue.id}:{payload.comment.id}"
    if event_type.startswith(JiraWebhookEventFamily.SPRINT):
        if payload.sprint is None:
            raise SorWebhookPayloadError("Jira webhook sprint is invalid.")
        return JiraStream.SPRINTS, payload.sprint.id
    return None, None


def _jira_webhook_occurred_at(value: int | float | None) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromtimestamp(
            float(value) / JIRA_WEBHOOK_TIMESTAMP_MILLISECONDS, tz=timezone.utc
        )
    except (OverflowError, OSError, ValueError) as error:
        raise SorWebhookPayloadError("Jira webhook timestamp is invalid.") from error
    now = datetime.now(timezone.utc)
    if result > now + JIRA_WEBHOOK_FUTURE_TOLERANCE:
        raise SorWebhookPayloadError("Jira webhook timestamp is in the future.")
    return result


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_COMMAND_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


__all__ = [
    "JIRA_API_ORIGIN",
    "JIRA_API_VERSION",
    "JIRA_MANIFEST",
    "JiraTicketingAdapter",
    "create_jira_adapter",
]
