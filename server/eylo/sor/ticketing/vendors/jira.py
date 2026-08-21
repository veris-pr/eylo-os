"""Jira Cloud adapter for Eylo's canonical ticketing profile."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterContext,
    SorCapabilityUnavailable,
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
    SorOAuthSpec,
    SorProfile,
    SorRecordPage,
    SorVendorOperationError,
    SorVendorStreamSpec,
    SorWebhookSignal,
    SorWebhookSubscription,
)
from eylo.sor.ticketing.contracts import (
    TicketingComment,
    TicketingCycle,
    TicketingIssue,
    TicketingIssueRelation,
    TicketingLabel,
    TicketingProject,
    TicketingRelationKind,
    TicketingUser,
    TicketingWorkflowState,
)

JIRA_API_ORIGIN = "https://api.atlassian.com"
JIRA_API_VERSION = "jira-cloud-rest-v3"
JIRA_CURSOR_VERSION = 1
JIRA_RECONCILIATION_OVERLAP = timedelta(minutes=5)

READ_WORK_SCOPE = "read:jira-work"
READ_USER_SCOPE = "read:jira-user"
WRITE_SCOPE = "write:jira-work"
OFFLINE_SCOPE = "offline_access"
READ_BOARD_SCOPE = "read:board-scope:jira-software"
READ_PROJECT_SCOPE = "read:project:jira"
READ_SPRINT_SCOPE = "read:sprint:jira-software"

_STREAM_ENTITY = {
    "issues": "issue",
    "projects": "project",
    "workflow_states": "workflow_state",
    "users": "user",
    "labels": "label",
    "sprints": "cycle",
    "comments": "comment",
    "issue_relations": "relation",
}
_READ_TOOLS = frozenset(
    {
        "issue_search",
        "issue_get",
        "issue_list_projects",
        "issue_list_workflow_states",
        "issue_describe_fields",
    }
)
_WRITE_TOOLS = frozenset(
    {
        "issue_create",
        "issue_update",
        "issue_transition",
        "issue_assign",
        "issue_add_label",
        "issue_remove_label",
        "issue_comment",
        "issue_link",
    }
)
_TOOL_STREAMS = {
    "issue_search": frozenset({"issues"}),
    "issue_get": frozenset({"issues"}),
    "issue_list_projects": frozenset({"projects"}),
    "issue_list_workflow_states": frozenset({"workflow_states"}),
    "issue_describe_fields": frozenset({"issues"}),
    "issue_create": frozenset({"issues", "projects"}),
    "issue_update": frozenset({"issues"}),
    "issue_transition": frozenset({"issues", "workflow_states"}),
    "issue_assign": frozenset({"issues", "users"}),
    "issue_add_label": frozenset({"issues", "labels"}),
    "issue_remove_label": frozenset({"issues", "labels"}),
    "issue_comment": frozenset({"issues", "comments"}),
    "issue_link": frozenset({"issues", "issue_relations"}),
}
_MUTATION_RESULT_STREAMS = {
    **{tool_name: "issues" for tool_name in _WRITE_TOOLS},
    "issue_comment": "comments",
    "issue_link": "issue_relations",
}


JIRA_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.TICKETING,
    vendor_key="jira",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "issues": "Issues",
                "projects": "Projects",
                "workflow_states": "Workflow states",
                "users": "Users",
                "labels": "Labels",
                "sprints": "Sprints",
                "comments": "Comments",
                "issue_relations": "Issue relations",
            }[stream_key],
            description={
                "issues": "Jira issues, ownership, labels, planning fields, and custom fields.",
                "projects": "Jira projects exposed as ticketing work containers.",
                "workflow_states": "Jira statuses and normalized status categories.",
                "users": "Visible active and inactive Jira users.",
                "labels": "Values used by Jira's global label field.",
                "sprints": "Jira Software sprints discovered through visible boards.",
                "comments": "Chronological issue comments with Atlassian Document Format retained.",
                "issue_relations": "Typed Jira issue links normalized into canonical directions.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key == "issues"
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
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
        "issues": (READ_WORK_SCOPE,),
        "projects": (READ_WORK_SCOPE,),
        "workflow_states": (READ_WORK_SCOPE,),
        "users": (READ_USER_SCOPE,),
        "labels": (READ_WORK_SCOPE,),
        "sprints": (READ_BOARD_SCOPE, READ_PROJECT_SCOPE, READ_SPRINT_SCOPE),
        "comments": (READ_WORK_SCOPE,),
        "issue_relations": (READ_WORK_SCOPE,),
    },
    tool_required_scopes={tool_name: (WRITE_SCOPE,) for tool_name in _WRITE_TOOLS},
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams=_MUTATION_RESULT_STREAMS,
    oauth=SorOAuthSpec(
        authorization_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        base_scopes=(OFFLINE_SCOPE,),
        authorization_params=(("audience", "api.atlassian.com"), ("prompt", "consent")),
        token_request_format="json",
        instance_host_suffixes=("atlassian.net",),
        operator_instance_origin=True,
    ),
    fixed_origin=JIRA_API_ORIGIN,
    requires_instance_origin=True,
    supports_custom_fields=True,
    supports_comments=True,
)


def _field(
    key: str,
    label: str,
    data_type: str,
    *,
    nullable: bool = True,
    writable: bool = False,
    description: str | None = None,
    group: str = "Jira",
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        description=description,
        group=group,
    )


_SCHEMA_FIELDS = {
    "issues": (
        _field("key", "Key", "text", nullable=False),
        _field("title", "Title", "text", nullable=False, writable=True),
        _field("normalized_description", "Description", "text", writable=True),
        _field(
            "source_description",
            "Source description",
            "bounded_json",
            description="The original Atlassian Document Format value retained for audit.",
        ),
        _field("issue_type", "Issue type", "text", nullable=False, writable=True),
        _field("native_status", "Status", "text"),
        _field("normalized_status", "Normalized status", "enum"),
        _field("priority", "Priority", "text", writable=True),
        _field("project_external_id", "Project ID", "reference", writable=True),
        _field("team_external_id", "Team ID", "reference"),
        _field("assignee_external_id", "Assignee ID", "reference", writable=True),
        _field("reporter_external_id", "Reporter ID", "reference"),
        _field("estimate", "Estimate", "decimal", writable=True),
        _field("label_external_ids", "Labels", "string_array", writable=True),
        _field("parent_external_id", "Parent issue ID", "reference", writable=True),
        _field("cycle_external_id", "Sprint ID", "reference"),
        _field("due_date", "Due date", "date", writable=True),
        _field("started_at", "Started at", "timestamp"),
        _field("completed_at", "Completed at", "timestamp"),
        _field("cancelled_at", "Cancelled at", "timestamp"),
    ),
    "projects": (
        _field("key", "Key", "text", nullable=False),
        _field("name", "Name", "text", nullable=False),
        _field("description", "Description", "text"),
    ),
    "workflow_states": (
        _field("name", "Name", "text", nullable=False),
        _field("native_category", "Source category", "text"),
        _field("normalized_category", "Normalized category", "enum"),
        _field("order", "Order", "integer"),
    ),
    "users": (
        _field("name", "Name", "text", nullable=False),
        _field("display_name", "Display name", "text"),
        _field("primary_email", "Email", "text"),
        _field("active", "Active", "boolean", nullable=False),
        _field("assignable", "Assignable", "boolean"),
        _field("avatar_url", "Avatar URL", "link"),
    ),
    "labels": (
        _field("name", "Name", "text", nullable=False),
        _field("description", "Description", "text"),
        _field("color", "Color", "text"),
        _field("project_external_id", "Project ID", "reference"),
        _field("parent_external_id", "Parent label ID", "reference"),
        _field("is_group", "Group", "boolean", nullable=False),
    ),
    "sprints": (
        _field("name", "Name", "text", nullable=False),
        _field("number", "Number", "integer"),
        _field("project_external_id", "Project ID", "reference"),
        _field("description", "Goal", "text"),
        _field("starts_at", "Starts at", "timestamp"),
        _field("ends_at", "Ends at", "timestamp"),
        _field("completed_at", "Completed at", "timestamp"),
        _field("active", "Active", "boolean"),
    ),
    "comments": (
        _field("issue_external_id", "Issue ID", "reference", nullable=False),
        _field("author_external_id", "Author ID", "reference"),
        _field("normalized_text", "Comment", "text", nullable=False),
        _field("source_body", "Source body", "bounded_json"),
        _field("created_at", "Created at", "timestamp", nullable=False),
        _field("updated_at", "Updated at", "timestamp"),
    ),
    "issue_relations": (
        _field("issue_vendor_object_key", "Issue stream", "text", nullable=False),
        _field("from_issue_external_id", "From issue ID", "reference", nullable=False),
        _field("to_issue_external_id", "To issue ID", "reference", nullable=False),
        _field("canonical_kind", "Normalized relation", "enum", nullable=False),
        _field("native_kind", "Source relation", "text", nullable=False),
    ),
}

_ISSUE_API_FIELDS = {
    "assignee",
    "created",
    "description",
    "duedate",
    "issuetype",
    "labels",
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
    "label_external_ids": "labels",
    "parent_external_id": "parent",
    "due_date": "duedate",
    "completed_at": "resolutiondate",
}


@dataclass(frozen=True, slots=True)
class _IssueCursor:
    floor: datetime | None
    next_token: str | None
    high: datetime | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class _NestedIssueCursor:
    """Resume one bounded child collection while advancing issues one at a time."""

    next_issue_token: str | None
    current_issue_id: str | None
    current_issue_is_last: bool
    item_offset: int


@dataclass(frozen=True, slots=True)
class _SprintCursor:
    """Resume sprint pagination inside one Jira Software board."""

    board_offset: int
    board_id: str | None
    board_is_last: bool
    project_external_id: str | None
    sprint_offset: int


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
        self._site_origin = _jira_site_origin(context.instance_origin)
        self._cloud_id: str | None = None
        self._site_name: str | None = None
        self._board_projects: dict[str, str | None] = {}
        self._client = SorJsonHttpClient(
            origin=JIRA_API_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        cloud_id, site_name = await self._resolve_site()
        response = await self._jira_request("/myself")
        viewer = _object(_expect(response, operation="verify Jira account"), field="Jira user")
        display = _optional_string(viewer.get("displayName"))
        return SorConnectionVerification(
            account_external_id=cloud_id,
            account_display_name=site_name or display or "Jira Cloud site",
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=JIRA_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise SorVendorOperationError(
                "source_selection_empty",
                "The Jira source selects no streams.",
                retryable=False,
            )
        custom_fields: tuple[SorDiscoveredField, ...] = ()
        if "issues" in self._context.selected_objects:
            response = await self._jira_request("/field")
            rows = _object_list(_expect(response, operation="list Jira fields"), field="Jira fields")
            custom_fields = tuple(
                sorted(
                    (_jira_custom_field(row) for row in rows if row.get("custom") is True),
                    key=lambda field: (field.label.casefold(), field.key),
                )
            )
        objects: list[SorDiscoveredObject] = []
        streams = {stream.key: stream for stream in JIRA_MANIFEST.streams}
        for stream_key in self._context.selected_objects:
            _require_stream(stream_key, selected=self._context.selected_objects)
            fields = _SCHEMA_FIELDS[stream_key]
            if stream_key == "issues":
                fields = (*fields, *custom_fields)
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=streams[stream_key].label,
                    fields=fields,
                )
            )
        return SorDiscoveredSchema(objects=tuple(objects), vendor_api_version=JIRA_API_VERSION)

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
        if stream_key == "labels":
            return self._external_record("labels", {"name": record_id})
        if stream_key == "issues":
            response = await self._jira_request(
                f"/issue/{_path_segment(record_id)}",
                query={"fields": list(self._issue_fields())},
            )
        elif stream_key == "projects":
            response = await self._jira_request(f"/project/{_path_segment(record_id)}")
        elif stream_key == "workflow_states":
            response = await self._jira_request(f"/status/{_path_segment(record_id)}")
        elif stream_key == "users":
            response = await self._jira_request(
                "/user",
                query={"accountId": record_id},
            )
        elif stream_key == "sprints":
            response = await self._agile_request(
                f"/sprint/{_path_segment(record_id)}"
            )
        elif stream_key == "comments":
            issue_id, comment_id = _split_comment_external_id(record_id)
            response = await self._jira_request(
                f"/issue/{_path_segment(issue_id)}/comment/{_path_segment(comment_id)}"
            )
        else:
            response = await self._jira_request(
                f"/issueLink/{_path_segment(record_id)}"
            )
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        row = _object(_expect(response, operation="read Jira record"), field="Jira record")
        if stream_key == "sprints":
            board_id = _optional_id(row.get("originBoardId"))
            row["_board_id"] = board_id
            row["_project_external_id"] = (
                await self._board_project_external_id(board_id)
                if board_id is not None
                else None
            )
        elif stream_key == "comments":
            issue_id, _comment_id = _split_comment_external_id(record_id)
            row["_issue_external_id"] = issue_id
        return self._external_record(stream_key, row)

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
        raise SorCapabilityUnavailable(
            "Jira dynamic webhooks require app-secret JWT verification support."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Jira dynamic webhooks require app-secret JWT verification support."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Jira dynamic webhooks require app-secret JWT verification support."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        raise SorCapabilityUnavailable(
            "Jira dynamic webhooks require app-secret JWT verification support."
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        raise SorCapabilityUnavailable(
            "Jira dynamic webhooks require app-secret JWT verification support."
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This Jira adapter does not execute the requested issue action.",
                retryable=False,
            )
        if command.tool_name == "issue_create":
            return await self._create_issue(command)
        target_id = _required_target(command)
        if command.tool_name == "issue_update":
            return await self._update_issue(target_id, command)
        if command.tool_name == "issue_transition":
            return await self._transition_issue(target_id, command)
        if command.tool_name == "issue_assign":
            return await self._assign_issue(target_id, command)
        if command.tool_name == "issue_comment":
            return await self._comment_issue(target_id, command)
        if command.tool_name == "issue_link":
            return await self._link_issue(target_id, command)
        return await self._change_label(
            target_id,
            command,
            add=command.tool_name == "issue_add_label",
        )

    def normalize_issue(self, record: SorExternalRecord) -> TicketingIssue:
        values = record.payload
        return TicketingIssue(
            external_id=record.external_id,
            key=_optional_string(values.get("key")),
            title=_required_string(values.get("title"), field="Jira issue title"),
            normalized_description=_optional_string(values.get("normalized_description")),
            source_description=_json_value(values.get("source_description")),
            issue_type=_optional_string(values.get("issue_type")),
            native_status=_optional_string(values.get("native_status")),
            normalized_status=_optional_string(values.get("normalized_status")),
            priority=_optional_string(values.get("priority")),
            project_external_id=_optional_string(values.get("project_external_id")),
            team_external_id=_optional_string(values.get("team_external_id")),
            assignee_external_id=_optional_string(values.get("assignee_external_id")),
            reporter_external_id=_optional_string(values.get("reporter_external_id")),
            estimate=_optional_decimal(values.get("estimate")),
            label_external_ids=_string_tuple(values.get("label_external_ids")),
            parent_external_id=_optional_string(values.get("parent_external_id")),
            cycle_external_id=_optional_string(values.get("cycle_external_id")),
            due_date=_optional_date(values.get("due_date")),
            started_at=_optional_datetime(values.get("started_at")),
            completed_at=_optional_datetime(values.get("completed_at")),
            cancelled_at=_optional_datetime(values.get("cancelled_at")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
            custom_fields={
                key: value
                for key, value in values.items()
                if key.startswith("customfield_")
            },
        )

    def normalize_project(self, record: SorExternalRecord) -> TicketingProject:
        return TicketingProject(
            external_id=record.external_id,
            key=_optional_string(record.payload.get("key")),
            name=_required_string(record.payload.get("name"), field="Jira project name"),
            description=_optional_string(record.payload.get("description")),
            source_url=record.source_url,
        )

    def normalize_workflow_state(
        self,
        record: SorExternalRecord,
    ) -> TicketingWorkflowState:
        return TicketingWorkflowState(
            external_id=record.external_id,
            name=_required_string(
                record.payload.get("name"),
                field="Jira workflow state name",
            ),
            native_category=_optional_string(record.payload.get("native_category")),
            normalized_category=_optional_string(
                record.payload.get("normalized_category")
            ),
            order=_optional_integer(record.payload.get("order"), field="Jira status order"),
        )

    def normalize_user(self, record: SorExternalRecord) -> TicketingUser:
        values = record.payload
        return TicketingUser(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Jira user name"),
            display_name=_optional_string(values.get("display_name")),
            primary_email=_optional_string(values.get("primary_email")),
            active=_required_boolean(values.get("active"), field="Jira user active"),
            assignable=_optional_boolean(values.get("assignable")),
            avatar_url=_optional_string(values.get("avatar_url")),
            source_url=record.source_url,
        )

    def normalize_label(self, record: SorExternalRecord) -> TicketingLabel:
        values = record.payload
        return TicketingLabel(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Jira label name"),
            description=_optional_string(values.get("description")),
            color=_optional_string(values.get("color")),
            project_external_id=_optional_string(values.get("project_external_id")),
            parent_external_id=_optional_string(values.get("parent_external_id")),
            is_group=_required_boolean(values.get("is_group"), field="Jira label group flag"),
        )

    def normalize_cycle(self, record: SorExternalRecord) -> TicketingCycle:
        values = record.payload
        return TicketingCycle(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="Jira sprint name"),
            number=_optional_integer(values.get("number"), field="Jira sprint number"),
            project_external_id=_optional_string(
                values.get("project_external_id")
            ),
            description=_optional_string(values.get("description")),
            starts_at=_optional_datetime(values.get("starts_at")),
            ends_at=_optional_datetime(values.get("ends_at")),
            completed_at=_optional_datetime(values.get("completed_at")),
            active=_optional_boolean(values.get("active")),
        )

    def normalize_comment(self, record: SorExternalRecord) -> TicketingComment:
        values = record.payload
        return TicketingComment(
            external_id=record.external_id,
            issue_external_id=_required_string(
                values.get("issue_external_id"),
                field="Jira comment issue ID",
            ),
            author_external_id=_optional_string(values.get("author_external_id")),
            normalized_text=_required_string(
                values.get("normalized_text"),
                field="Jira comment body",
            ),
            source_body=_json_value(values.get("source_body")),
            created_at=_required_datetime(
                values.get("created_at"),
                field="Jira comment creation time",
            ),
            updated_at=_optional_datetime(values.get("updated_at")),
        )

    def normalize_relation(self, record: SorExternalRecord) -> TicketingIssueRelation:
        values = record.payload
        return TicketingIssueRelation(
            external_id=record.external_id,
            issue_vendor_object_key="issues",
            from_issue_external_id=_required_string(
                values.get("from_issue_external_id"),
                field="Jira relation source issue ID",
            ),
            to_issue_external_id=_required_string(
                values.get("to_issue_external_id"),
                field="Jira relation target issue ID",
            ),
            canonical_kind=_jira_relation_kind(
                values.get("canonical_kind"),
                error_code="vendor_response_invalid",
            ),
            native_kind=_required_string(
                values.get("native_kind"),
                field="Jira relation type",
            ),
            source_revision=record.source_revision,
        )

    async def close(self) -> None:
        return None

    async def _resolve_site(self) -> tuple[str, str | None]:
        if self._cloud_id is not None:
            return self._cloud_id, self._site_name
        response = await self._client.request("/oauth/token/accessible-resources")
        rows = _object_list(
            _expect(response, operation="list accessible Jira sites"),
            field="Atlassian accessible resources",
        )
        matches = [
            row
            for row in rows
            if _normalized_origin(row.get("url")) == self._site_origin
        ]
        if len(matches) != 1:
            raise SorVendorOperationError(
                "vendor_site_unavailable",
                "The authorized Atlassian account does not expose the configured Jira site.",
                retryable=False,
                requires_reauthorization=True,
            )
        site = matches[0]
        self._cloud_id = _required_id(site.get("id"), field="Jira cloud ID")
        self._site_name = _optional_string(site.get("name"))
        return self._cloud_id, self._site_name

    async def _jira_request(
        self,
        path: str,
        *,
        method: str = "GET",
        query: Mapping[str, object] | None = None,
        payload: object | None = None,
        idempotency_key: str | None = None,
    ) -> SorJsonResponse:
        cloud_id, _name = await self._resolve_site()
        return await self._client.request(
            f"/ex/jira/{_path_segment(cloud_id)}/rest/api/3{path}",
            method=method,
            query=query,
            payload=payload,
            idempotency_key=idempotency_key,
        )

    async def _agile_request(
        self,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
    ) -> SorJsonResponse:
        cloud_id, _name = await self._resolve_site()
        return await self._client.request(
            f"/jira/software/cloud/{_path_segment(cloud_id)}/rest/agile/1.0{path}",
            query=query,
        )

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(stream_key, selected=self._context.selected_objects)
        if limit <= 0:
            raise SorVendorOperationError(
                "vendor_page_invalid",
                "Jira page limit must be positive.",
                retryable=False,
            )
        page_limit = min(limit, 100)
        if stream_key == "issues":
            return await self._read_issues(cursor=cursor, limit=page_limit)
        if stream_key in {"comments", "issue_relations"}:
            return await self._read_issue_children(
                stream_key=stream_key,
                cursor=cursor,
                limit=page_limit,
            )
        if stream_key == "sprints":
            return await self._read_sprints(cursor=cursor, limit=page_limit)
        offset = _decode_offset_cursor(cursor, stream_key=stream_key)
        rows: list[dict[str, object]]
        if stream_key == "projects":
            response = await self._jira_request(
                "/project/search",
                query={"startAt": offset, "maxResults": page_limit, "orderBy": "key"},
            )
            data = _object(_expect(response, operation="list Jira projects"), field="Jira projects")
            rows = _object_list(data.get("values"), field="Jira projects")
            has_more = not _required_boolean(data.get("isLast"), field="Jira projects isLast")
        elif stream_key == "workflow_states":
            response = await self._jira_request("/status")
            all_rows = sorted(
                _object_list(
                    _expect(response, operation="list Jira statuses"),
                    field="Jira statuses",
                ),
                key=lambda row: (
                    _required_string(
                        row.get("name"),
                        field="Jira status name",
                    ).casefold(),
                    _required_id(row.get("id"), field="Jira status ID"),
                ),
            )
            rows = all_rows[offset : offset + page_limit]
            has_more = offset + len(rows) < len(all_rows)
        elif stream_key == "users":
            response = await self._jira_request(
                "/users",
                query={"startAt": offset, "maxResults": page_limit},
            )
            rows = _object_list(_expect(response, operation="list Jira users"), field="Jira users")
            has_more = len(rows) == page_limit
        else:
            response = await self._jira_request(
                "/label",
                query={"startAt": offset, "maxResults": page_limit},
            )
            data = _object(_expect(response, operation="list Jira labels"), field="Jira labels")
            labels = _string_list(data.get("values"), field="Jira labels")
            rows = [{"name": label} for label in labels]
            has_more = not _required_boolean(data.get("isLast"), field="Jira labels isLast")
        if len(rows) > page_limit:
            raise _invalid_response("Jira returned more rows than the requested page limit.")
        return SorRecordPage(
            records=tuple(self._external_record(stream_key, row, position=offset + index) for index, row in enumerate(rows)),
            next_cursor=(
                _encode_offset_cursor(offset + len(rows), stream_key=stream_key)
                if has_more
                else None
            ),
            has_more=has_more,
        )

    async def _read_issues(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        checkpoint = _decode_issue_cursor(cursor)
        jql = "ORDER BY updated ASC, id ASC"
        if checkpoint.floor is not None:
            floor = checkpoint.floor.strftime("%Y-%m-%d %H:%M")
            jql = f'updated >= "{floor}" ORDER BY updated ASC, id ASC'
        payload: dict[str, object] = {
            "fields": list(self._issue_fields()),
            "fieldsByKeys": True,
            "jql": jql,
            "maxResults": limit,
        }
        if checkpoint.next_token is not None:
            payload["nextPageToken"] = checkpoint.next_token
        response = await self._jira_request(
            "/search/jql",
            method="POST",
            payload=payload,
        )
        data = _object(_expect(response, operation="search Jira issues"), field="Jira issue search")
        rows = _object_list(data.get("issues"), field="Jira issues")
        if len(rows) > limit:
            raise _invalid_response("Jira returned more issues than the requested page limit.")
        is_last = _required_boolean(data.get("isLast"), field="Jira issue search isLast")
        next_token = _optional_string(data.get("nextPageToken"))
        if not is_last and next_token is None:
            raise _invalid_response("Jira omitted the next issue page token.")
        high = _maximum_issue_updated_at(rows, current=checkpoint.high)
        if is_last:
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
                    next_token=next_token,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
        return SorRecordPage(
            records=tuple(self._external_record("issues", row) for row in rows),
            next_cursor=next_cursor,
            has_more=not is_last,
        )

    async def _read_issue_children(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        checkpoint = _decode_nested_issue_cursor(cursor, stream_key=stream_key)
        scans = 0
        while scans < 25:
            if checkpoint.current_issue_id is None:
                issue_id, next_token, is_last = await self._next_child_issue(
                    checkpoint.next_issue_token
                )
                if issue_id is None:
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                checkpoint = _NestedIssueCursor(
                    next_issue_token=next_token,
                    current_issue_id=issue_id,
                    current_issue_is_last=is_last,
                    item_offset=0,
                )

            assert checkpoint.current_issue_id is not None
            if stream_key == "comments":
                rows, child_has_more = await self._read_issue_comments(
                    issue_id=checkpoint.current_issue_id,
                    offset=checkpoint.item_offset,
                    limit=limit,
                )
            else:
                rows, child_has_more = await self._read_issue_relations(
                    issue_id=checkpoint.current_issue_id,
                    offset=checkpoint.item_offset,
                    limit=limit,
                )

            if child_has_more:
                if not rows:
                    raise _invalid_response(
                        f"Jira returned an empty partial {stream_key} page."
                    )
                next_checkpoint = _NestedIssueCursor(
                    next_issue_token=checkpoint.next_issue_token,
                    current_issue_id=checkpoint.current_issue_id,
                    current_issue_is_last=checkpoint.current_issue_is_last,
                    item_offset=checkpoint.item_offset + len(rows),
                )
                return SorRecordPage(
                    records=tuple(self._external_record(stream_key, row) for row in rows),
                    next_cursor=_encode_nested_issue_cursor(
                        next_checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )

            records = tuple(self._external_record(stream_key, row) for row in rows)
            if checkpoint.current_issue_is_last:
                return SorRecordPage(
                    records=records,
                    next_cursor=None,
                    has_more=False,
                )

            checkpoint = _NestedIssueCursor(
                next_issue_token=checkpoint.next_issue_token,
                current_issue_id=None,
                current_issue_is_last=False,
                item_offset=0,
            )
            if records:
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_nested_issue_cursor(
                        checkpoint,
                        stream_key=stream_key,
                    ),
                    has_more=True,
                )
            scans += 1

        return SorRecordPage(
            records=(),
            next_cursor=_encode_nested_issue_cursor(
                checkpoint,
                stream_key=stream_key,
            ),
            has_more=True,
        )

    async def _next_child_issue(
        self,
        next_page_token: str | None,
    ) -> tuple[str | None, str | None, bool]:
        payload: dict[str, object] = {
            "fields": ["updated"],
            "fieldsByKeys": True,
            "jql": "ORDER BY id ASC",
            "maxResults": 1,
        }
        if next_page_token is not None:
            payload["nextPageToken"] = next_page_token
        response = await self._jira_request(
            "/search/jql",
            method="POST",
            payload=payload,
        )
        data = _object(
            _expect(response, operation="scan Jira issues"),
            field="Jira issue scan",
        )
        rows = _object_list(data.get("issues"), field="Jira issue scan")
        if len(rows) > 1:
            raise _invalid_response("Jira returned too many issues for a child scan.")
        is_last = _required_boolean(data.get("isLast"), field="Jira issue scan isLast")
        following = _optional_string(data.get("nextPageToken"))
        if not is_last and following is None:
            raise _invalid_response("Jira omitted the next child-scan page token.")
        if not rows:
            if not is_last:
                raise _invalid_response("Jira returned an empty partial issue scan.")
            return None, None, True
        return (
            _required_id(rows[0].get("id"), field="Jira issue ID"),
            following,
            is_last,
        )

    async def _read_issue_comments(
        self,
        *,
        issue_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], bool]:
        response = await self._jira_request(
            f"/issue/{_path_segment(issue_id)}/comment",
            query={"startAt": offset, "maxResults": limit, "orderBy": "created"},
        )
        data = _object(
            _expect(response, operation="list Jira issue comments"),
            field="Jira comments",
        )
        rows = _object_list(data.get("comments"), field="Jira comments")
        if len(rows) > limit:
            raise _invalid_response("Jira returned too many issue comments.")
        total = _required_nonnegative_integer(
            data.get("total"),
            field="Jira comment total",
        )
        for row in rows:
            row["_issue_external_id"] = issue_id
        return rows, offset + len(rows) < total

    async def _read_issue_relations(
        self,
        *,
        issue_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], bool]:
        response = await self._jira_request(
            f"/issue/{_path_segment(issue_id)}",
            query={"fields": ["issuelinks"]},
        )
        issue = _object(
            _expect(response, operation="list Jira issue links"),
            field="Jira issue",
        )
        fields = _object(issue.get("fields"), field="Jira issue fields")
        links = _object_list(fields.get("issuelinks"), field="Jira issue links")
        rows = links[offset : offset + limit]
        for row in rows:
            row["_current_issue_external_id"] = issue_id
        return rows, offset + len(rows) < len(links)

    async def _board_project_external_id(self, board_id: str) -> str | None:
        """Resolve one board's owning project once per adapter invocation."""
        if board_id in self._board_projects:
            return self._board_projects[board_id]
        response = await self._agile_request(f"/board/{_path_segment(board_id)}")
        board = _object(
            _expect(response, operation="read Jira Software board"),
            field="Jira board",
        )
        location = _optional_object(board.get("location"))
        project_external_id = _optional_id(location.get("projectId"))
        self._board_projects[board_id] = project_external_id
        return project_external_id

    async def _read_sprints(self, *, cursor: str | None, limit: int) -> SorRecordPage:
        checkpoint = _decode_sprint_cursor(cursor)
        scans = 0
        while scans < 25:
            if checkpoint.board_id is None:
                response = await self._agile_request(
                    "/board",
                    query={
                        "startAt": checkpoint.board_offset,
                        "maxResults": 1,
                        "type": "scrum",
                    },
                )
                data = _object(
                    _expect(response, operation="list Jira Software boards"),
                    field="Jira boards",
                )
                boards = _object_list(data.get("values"), field="Jira boards")
                if len(boards) > 1:
                    raise _invalid_response("Jira returned too many boards.")
                board_is_last = _required_boolean(
                    data.get("isLast"),
                    field="Jira boards isLast",
                )
                if not boards:
                    if not board_is_last:
                        raise _invalid_response("Jira returned an empty partial board page.")
                    return SorRecordPage(records=(), next_cursor=None, has_more=False)
                board = boards[0]
                location = _optional_object(board.get("location"))
                board_id = _required_id(board.get("id"), field="Jira board ID")
                project_external_id = _optional_id(location.get("projectId"))
                self._board_projects[board_id] = project_external_id
                checkpoint = _SprintCursor(
                    board_offset=checkpoint.board_offset,
                    board_id=board_id,
                    board_is_last=board_is_last,
                    project_external_id=project_external_id,
                    sprint_offset=0,
                )

            assert checkpoint.board_id is not None
            response = await self._agile_request(
                f"/board/{_path_segment(checkpoint.board_id)}/sprint",
                query={"startAt": checkpoint.sprint_offset, "maxResults": limit},
            )
            data = _object(
                _expect(response, operation="list Jira sprints"),
                field="Jira sprints",
            )
            rows = _object_list(data.get("values"), field="Jira sprints")
            if len(rows) > limit:
                raise _invalid_response("Jira returned too many sprints.")
            sprint_is_last = _required_boolean(
                data.get("isLast"),
                field="Jira sprints isLast",
            )
            for row in rows:
                origin_board_id = (
                    _optional_id(row.get("originBoardId")) or checkpoint.board_id
                )
                row["_project_external_id"] = (
                    checkpoint.project_external_id
                    if origin_board_id == checkpoint.board_id
                    else await self._board_project_external_id(origin_board_id)
                )
                row["_board_id"] = origin_board_id
            records = tuple(self._external_record("sprints", row) for row in rows)
            if not sprint_is_last:
                if not rows:
                    raise _invalid_response("Jira returned an empty partial sprint page.")
                next_checkpoint = _SprintCursor(
                    board_offset=checkpoint.board_offset,
                    board_id=checkpoint.board_id,
                    board_is_last=checkpoint.board_is_last,
                    project_external_id=checkpoint.project_external_id,
                    sprint_offset=checkpoint.sprint_offset + len(rows),
                )
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_sprint_cursor(next_checkpoint),
                    has_more=True,
                )
            if checkpoint.board_is_last:
                return SorRecordPage(
                    records=records,
                    next_cursor=None,
                    has_more=False,
                )
            checkpoint = _SprintCursor(
                board_offset=checkpoint.board_offset + 1,
                board_id=None,
                board_is_last=False,
                project_external_id=None,
                sprint_offset=0,
            )
            if records:
                return SorRecordPage(
                    records=records,
                    next_cursor=_encode_sprint_cursor(checkpoint),
                    has_more=True,
                )
            scans += 1

        return SorRecordPage(
            records=(),
            next_cursor=_encode_sprint_cursor(checkpoint),
            has_more=True,
        )

    def _issue_fields(self) -> tuple[str, ...]:
        custom = {
            field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == "issues"
            and field.vendor_field_key.startswith("customfield_")
        }
        return tuple(sorted(_ISSUE_API_FIELDS | custom))

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
        *,
        position: int | None = None,
    ) -> SorExternalRecord:
        if stream_key == "issues":
            return self._external_issue(row)
        if stream_key == "projects":
            record_id = _required_id(row.get("id"), field="Jira project ID")
            key = _optional_string(row.get("key"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "key": key,
                    "name": _required_string(row.get("name"), field="Jira project name"),
                    "description": _adf_text(row.get("description")),
                },
                source_url=f"{self._site_origin}/browse/{key}" if key else None,
            )
        if stream_key == "workflow_states":
            record_id = _required_id(row.get("id"), field="Jira status ID")
            category = _optional_object(row.get("statusCategory"))
            native = _optional_string(category.get("key")) or _optional_string(category.get("name"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": _required_string(row.get("name"), field="Jira status name"),
                    "native_category": native,
                    "normalized_category": _normalized_jira_status(native),
                    "order": position,
                },
            )
        if stream_key == "users":
            record_id = _required_id(row.get("accountId"), field="Jira account ID")
            display_name = _required_string(row.get("displayName"), field="Jira display name")
            avatars = _optional_object(row.get("avatarUrls"))
            return SorExternalRecord(
                vendor_object_key=stream_key,
                external_id=record_id,
                payload={
                    "name": display_name,
                    "display_name": display_name,
                    "primary_email": _optional_string(row.get("emailAddress")),
                    "active": _required_boolean(row.get("active"), field="Jira user active"),
                    "assignable": None,
                    "avatar_url": _optional_string(avatars.get("48x48")),
                },
            )
        if stream_key == "sprints":
            return self._external_sprint(row)
        if stream_key == "comments":
            return self._external_comment(row)
        if stream_key == "issue_relations":
            return self._external_relation(row)
        label = _required_string(row.get("name"), field="Jira label")
        return SorExternalRecord(
            vendor_object_key=stream_key,
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

    def _external_issue(self, row: Mapping[str, object]) -> SorExternalRecord:
        record_id = _required_id(row.get("id"), field="Jira issue ID")
        key = _required_string(row.get("key"), field="Jira issue key")
        fields = _object(row.get("fields"), field="Jira issue fields")
        status = _optional_object(fields.get("status"))
        category = _optional_object(status.get("statusCategory"))
        native_category = _optional_string(category.get("key")) or _optional_string(category.get("name"))
        description = fields.get("description")
        updated = _required_datetime(fields.get("updated"), field="Jira issue update time")
        resolution_at = _optional_datetime(fields.get("resolutiondate"))
        payload: dict[str, object] = {
            "key": key,
            "title": _required_string(fields.get("summary"), field="Jira issue summary"),
            "normalized_description": _adf_text(description),
            "source_description": _json_value(description),
            "issue_type": _nested_string(fields.get("issuetype"), "name"),
            "native_status": _nested_string(fields.get("status"), "name"),
            "normalized_status": _normalized_jira_status(native_category),
            "priority": _nested_string(fields.get("priority"), "name"),
            "project_external_id": _nested_id(fields.get("project")),
            "team_external_id": None,
            "assignee_external_id": _nested_id(fields.get("assignee"), key="accountId"),
            "reporter_external_id": _nested_id(fields.get("reporter"), key="accountId"),
            "estimate": fields.get("timeoriginalestimate"),
            "label_external_ids": _string_list(fields.get("labels"), field="Jira issue labels"),
            "parent_external_id": _nested_id(fields.get("parent")),
            "cycle_external_id": None,
            "due_date": fields.get("duedate"),
            "started_at": None,
            "completed_at": resolution_at if _normalized_jira_status(native_category) == "COMPLETED" else None,
            "cancelled_at": None,
        }
        for field_key in self._issue_fields():
            if field_key.startswith("customfield_"):
                payload[field_key] = fields.get(field_key)
        return SorExternalRecord(
            vendor_object_key="issues",
            external_id=record_id,
            payload=payload,
            source_created_at=_optional_datetime(fields.get("created")),
            source_updated_at=updated,
            source_revision=updated.isoformat(),
            source_url=f"{self._site_origin}/browse/{key}",
        )

    def _external_sprint(self, row: Mapping[str, object]) -> SorExternalRecord:
        record_id = _required_id(row.get("id"), field="Jira sprint ID")
        state = _optional_string(row.get("state"))
        board_id = _optional_id(row.get("_board_id")) or _optional_id(
            row.get("originBoardId")
        )
        return SorExternalRecord(
            vendor_object_key="sprints",
            external_id=record_id,
            payload={
                "name": _required_string(row.get("name"), field="Jira sprint name"),
                "number": None,
                "project_external_id": _optional_id(
                    row.get("_project_external_id")
                ),
                "description": _optional_string(row.get("goal")),
                "starts_at": row.get("startDate"),
                "ends_at": row.get("endDate"),
                "completed_at": row.get("completeDate"),
                "active": state.casefold() == "active" if state else None,
            },
            source_url=(
                f"{self._site_origin}/secure/RapidView.jspa?rapidView={board_id}"
                if board_id
                else None
            ),
        )

    def _external_comment(self, row: Mapping[str, object]) -> SorExternalRecord:
        comment_id = _required_id(row.get("id"), field="Jira comment ID")
        issue_id = _required_id(
            row.get("_issue_external_id"),
            field="Jira comment issue ID",
        )
        body = row.get("body")
        created_at = _required_datetime(
            row.get("created"),
            field="Jira comment creation time",
        )
        updated_at = _optional_datetime(row.get("updated")) or created_at
        author = _optional_object(row.get("author"))
        return SorExternalRecord(
            vendor_object_key="comments",
            external_id=_comment_external_id(issue_id, comment_id),
            payload={
                "issue_external_id": issue_id,
                "author_external_id": _optional_id(author.get("accountId")),
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

    def _external_relation(self, row: Mapping[str, object]) -> SorExternalRecord:
        relation_id = _required_id(row.get("id"), field="Jira issue-link ID")
        current_id = _optional_id(row.get("_current_issue_external_id"))
        inward = _optional_object(row.get("inwardIssue"))
        outward = _optional_object(row.get("outwardIssue"))
        inward_id = _optional_id(inward.get("id"))
        outward_id = _optional_id(outward.get("id"))
        if inward_id is None and current_id is not None and outward_id is not None:
            inward_id = current_id
        if outward_id is None and current_id is not None and inward_id is not None:
            outward_id = current_id
        if inward_id is None or outward_id is None:
            raise _invalid_response("Jira issue-link endpoints are incomplete.")
        relation_type = _object(row.get("type"), field="Jira issue-link type")
        native_kind = _required_string(
            relation_type.get("name"),
            field="Jira issue-link type name",
        )
        canonical_kind = _jira_relation_kind_from_type(relation_type)
        from_id, to_id = outward_id, inward_id
        if canonical_kind is TicketingRelationKind.RELATED and from_id > to_id:
            from_id, to_id = to_id, from_id
        return SorExternalRecord(
            vendor_object_key="issue_relations",
            external_id=relation_id,
            payload={
                "issue_vendor_object_key": "issues",
                "from_issue_external_id": from_id,
                "to_issue_external_id": to_id,
                "canonical_kind": canonical_kind.value,
                "native_kind": native_kind,
            },
            source_url=f"{self._site_origin}/browse/{from_id}",
        )

    async def _create_issue(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command("Creating a Jira issue cannot target an existing issue.")
        required = {"title", "project_external_id", "issue_type"}
        if not required.issubset(command.payload):
            raise _invalid_command(
                "Creating a Jira issue requires title, project_external_id, and issue_type."
            )
        fields = self._write_issue_fields(command.payload, create=True)
        try:
            response = await self._jira_request(
                "/issue",
                method="POST",
                payload={"fields": fields},
                idempotency_key=command.idempotency_key,
            )
            data = _object(_expect_mutation(response, operation="create Jira issue"), field="Jira issue create result")
        except SorVendorOperationError as error:
            _raise_unknown_create(error, "Jira may have created the issue; reconcile before retrying.")
            raise
        issue_id = _required_id(data.get("id"), field="Jira issue ID")
        key = _optional_string(data.get("key"))
        return self._command_result(issue_id, key=key, response=response)

    async def _update_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        fields = self._write_issue_fields(command.payload, create=False)
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}",
            method="PUT",
            payload={"fields": fields},
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="update Jira issue")
        return self._command_result(target_id, response=response)

    async def _transition_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        status_id = _single_string_payload(
            command.payload,
            key="workflow_state_external_id",
            field="Jira status ID",
        )
        available = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/transitions",
        )
        data = _object(_expect(available, operation="list Jira transitions"), field="Jira transitions")
        transitions = _object_list(data.get("transitions"), field="Jira transitions")
        transition_id = next(
            (
                _optional_string(row.get("id"))
                for row in transitions
                if _nested_id(row.get("to")) == status_id
            ),
            None,
        )
        if transition_id is None:
            raise _invalid_command("The requested Jira status is not reachable from this issue.")
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/transitions",
            method="POST",
            payload={"transition": {"id": transition_id}},
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="transition Jira issue")
        return self._command_result(target_id, response=response)

    async def _assign_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        assignee = _single_nullable_string_payload(
            command.payload,
            key="assignee_external_id",
            field="Jira account ID",
        )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}/assignee",
            method="PUT",
            payload={"accountId": assignee},
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="assign Jira issue")
        return self._command_result(target_id, response=response)

    async def _comment_issue(
        self,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        text = _single_string_payload(
            command.payload,
            key="text",
            field="Jira comment",
        )
        try:
            response = await self._jira_request(
                f"/issue/{_path_segment(target_id)}/comment",
                method="POST",
                payload={"body": _adf_document_or_none(text)},
                idempotency_key=command.idempotency_key,
            )
            data = _object(
                _expect_mutation(response, operation="comment on Jira issue"),
                field="Jira comment result",
            )
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error,
                "Jira may have created the comment; reconcile before retrying.",
            )
            raise
        comment_id = _required_id(data.get("id"), field="Jira comment ID")
        updated_at = _optional_datetime(data.get("updated")) or _required_datetime(
            data.get("created"),
            field="Jira comment creation time",
        )
        return SorCommandResult(
            vendor_object_key="comments",
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
        if set(command.payload) != {
            "related_issue_external_id",
            "relation_kind",
        }:
            raise _invalid_command(
                "Linking Jira issues requires related_issue_external_id and "
                "relation_kind only."
            )
        related_id = _required_id(
            command.payload.get("related_issue_external_id"),
            field="Jira related issue ID",
        )
        if related_id == target_id:
            raise _invalid_command("A Jira issue cannot link to itself.")
        requested_kind = _jira_relation_kind(command.payload.get("relation_kind"))
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
        payload = {
            "inwardIssue": {"id": inward_id},
            "outwardIssue": {"id": outward_id},
            "type": {"id": _required_id(link_type.get("id"), field="Jira link type ID")},
        }
        try:
            response = await self._jira_request(
                "/issueLink",
                method="POST",
                payload=payload,
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
        if canonical_kind is TicketingRelationKind.RELATED and expected_from > expected_to:
            expected_from, expected_to = expected_to, expected_from
        relation_id = await self._find_issue_link(
            issue_id=target_id,
            canonical_kind=canonical_kind,
            from_issue_id=expected_from,
            to_issue_id=expected_to,
        )
        if relation_id is None:
            raise SorVendorOperationError(
                "vendor_mutation_outcome_unknown",
                "Jira accepted the issue link but did not expose its ID yet; reconcile "
                "before retrying.",
                retryable=False,
            )
        return SorCommandResult(
            vendor_object_key="issue_relations",
            external_id=relation_id,
            external_request_id=_request_id(response),
            response={"status": "accepted"},
        )

    async def _resolve_link_type(
        self,
        relation_kind: TicketingRelationKind,
    ) -> dict[str, object]:
        response = await self._jira_request("/issueLinkType")
        data = _object(
            _expect(response, operation="list Jira issue-link types"),
            field="Jira issue-link types",
        )
        rows = _object_list(data.get("issueLinkTypes"), field="Jira issue-link types")
        matches = [row for row in rows if _jira_link_type_matches(row, relation_kind)]
        if not matches:
            raise _invalid_command(
                f"The Jira site has no link type compatible with {relation_kind.value}."
            )
        return min(
            matches,
            key=lambda row: (
                _required_string(row.get("name"), field="Jira link type name").casefold(),
                _required_id(row.get("id"), field="Jira link type ID"),
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
            query={"fields": ["issuelinks", "updated"]},
        )
        issue = _object(
            _expect(response, operation="resolve created Jira issue link"),
            field="Jira issue",
        )
        fields = _object(issue.get("fields"), field="Jira issue fields")
        rows = _object_list(fields.get("issuelinks"), field="Jira issue links")
        for row in rows:
            row["_current_issue_external_id"] = issue_id
            relation = self._external_relation(row)
            values = relation.payload
            if (
                values.get("canonical_kind") == canonical_kind.value
                and values.get("from_issue_external_id") == from_issue_id
                and values.get("to_issue_external_id") == to_issue_id
            ):
                return relation.external_id
        return None

    async def _change_label(
        self,
        target_id: str,
        command: SorCommandRequest,
        *,
        add: bool,
    ) -> SorCommandResult:
        label = _single_string_payload(
            command.payload,
            key="label_external_id",
            field="Jira label",
        )
        response = await self._jira_request(
            f"/issue/{_path_segment(target_id)}",
            method="PUT",
            payload={"update": {"labels": [{"add" if add else "remove": label}]}},
            idempotency_key=command.idempotency_key,
        )
        _expect_mutation(response, operation="change Jira issue label")
        return self._command_result(target_id, response=response)

    def _write_issue_fields(
        self,
        payload: Mapping[str, object],
        *,
        create: bool,
    ) -> dict[str, object]:
        if not payload:
            raise _invalid_command("A Jira issue mutation requires at least one field.")
        writable = {
            field.agent_key: field.vendor_field_key
            for field in self._context.fields
            if field.vendor_object_key == "issues" and field.writable
        }
        allowed = set(writable) | {
            "title",
            "normalized_description",
            "issue_type",
            "priority",
            "project_external_id",
            "estimate",
            "label_external_ids",
            "parent_external_id",
            "due_date",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise SorVendorOperationError(
                "vendor_field_not_writable",
                "The Jira mutation contains fields absent from the writable mapping.",
                retryable=False,
            )
        result: dict[str, object] = {}
        mappings = {
            "title": ("summary", _required_command_string),
            "normalized_description": ("description", _adf_document_or_none),
            "issue_type": ("issuetype", lambda value: {"name": _required_command_string(value)}),
            "priority": ("priority", lambda value: None if value is None else {"name": _required_command_string(value)}),
            "project_external_id": ("project", lambda value: {"id": _required_command_string(value)}),
            "estimate": ("timeoriginalestimate", _optional_positive_integer),
            "label_external_ids": ("labels", _command_string_list),
            "parent_external_id": ("parent", lambda value: None if value is None else {"id": _required_command_string(value)}),
            "due_date": ("duedate", _optional_command_string),
        }
        for key, value in payload.items():
            if key in mappings:
                target, transform = mappings[key]
                result[target] = transform(value)
                continue
            vendor_key = writable[key]
            result[vendor_key] = value
        if create:
            for field in ("summary", "project", "issuetype"):
                if field not in result:
                    raise _invalid_command(
                        "Creating a Jira issue requires title, project_external_id, and issue_type."
                    )
        return result

    def _command_result(
        self,
        issue_id: str,
        *,
        response: SorJsonResponse,
        key: str | None = None,
    ) -> SorCommandResult:
        return SorCommandResult(
            vendor_object_key="issues",
            external_id=issue_id,
            external_request_id=_request_id(response),
            source_url=f"{self._site_origin}/browse/{key}" if key else None,
            response={"status": "accepted"},
        )


def create_jira_adapter(context: SorAdapterContext) -> JiraTicketingAdapter:
    """Construct the production Jira adapter for the explicit registry."""
    return JiraTicketingAdapter(context)


def _jira_custom_field(row: Mapping[str, object]) -> SorDiscoveredField:
    key = _required_id(row.get("id"), field="Jira custom field ID")
    if not key.startswith("customfield_"):
        raise _invalid_response("Jira returned an invalid custom field ID.")
    schema = _optional_object(row.get("schema"))
    data_type = {
        "array": "string_array",
        "date": "date",
        "datetime": "timestamp",
        "number": "decimal",
        "option": "text",
        "string": "text",
        "user": "reference",
    }.get(_optional_string(schema.get("type")) or "", "bounded_json")
    return _field(
        key,
        _required_string(row.get("name"), field="Jira custom field name"),
        data_type,
        writable=True,
        description=_optional_string(row.get("description")),
        group="Jira custom fields",
    )


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.status_code in {401, 403}:
        raise SorVendorOperationError(
            "vendor_authorization_failed",
            f"Jira refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
            refreshable_authorization=response.status_code == 401,
        )
    if response.status_code == 429:
        raise SorVendorOperationError(
            "vendor_rate_limited",
            "Jira rate limited the operation.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            "Jira could not complete the operation.",
            retryable=True,
        )
    if not response.ok:
        raise SorVendorOperationError(
            "vendor_request_rejected",
            f"Jira rejected the request while attempting to {operation}.",
            retryable=False,
        )
    return response.data


def _expect_mutation(response: SorJsonResponse, *, operation: str) -> object:
    value = _expect(response, operation=operation)
    if response.status_code not in {200, 201, 204}:
        raise _invalid_response("Jira returned an unexpected mutation status.")
    return value


def _decode_issue_cursor(value: str | None) -> _IssueCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _IssueCursor(floor=None, next_token=None, high=None, started_at=now)
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor("issue") from error
    if not isinstance(payload, dict) or set(payload) != {
        "floor",
        "high",
        "next_token",
        "started_at",
        "stream",
        "v",
    }:
        raise _invalid_cursor("issue")
    if payload.get("v") != JIRA_CURSOR_VERSION or payload.get("stream") != "issues":
        raise _invalid_cursor("issue")
    floor = _optional_datetime(payload.get("floor"))
    high = _optional_datetime(payload.get("high"))
    next_token = _optional_string(payload.get("next_token"))
    started_at = _optional_datetime(payload.get("started_at"))
    if started_at is None or (next_token is not None and high is None):
        raise _invalid_cursor("issue")
    if next_token is None:
        return _IssueCursor(floor=floor, next_token=None, high=None, started_at=now)
    if len(next_token) > 4_096:
        raise _invalid_cursor("issue")
    return _IssueCursor(
        floor=floor,
        next_token=next_token,
        high=high,
        started_at=started_at,
    )


def _encode_issue_cursor(cursor: _IssueCursor) -> str:
    return json.dumps(
        {
            "floor": _datetime_value(cursor.floor),
            "high": _datetime_value(cursor.high),
            "next_token": cursor.next_token,
            "started_at": _datetime_value(cursor.started_at),
            "stream": "issues",
            "v": JIRA_CURSOR_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
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
        next_token=None,
        high=None,
        started_at=started_at,
    )


def _decode_offset_cursor(value: str | None, *, stream_key: str) -> int:
    if value is None:
        return 0
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor(stream_key) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"offset", "stream", "v"}
        or payload.get("v") != JIRA_CURSOR_VERSION
        or payload.get("stream") != stream_key
    ):
        raise _invalid_cursor(stream_key)
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise _invalid_cursor(stream_key)
    return offset


def _encode_offset_cursor(offset: int, *, stream_key: str) -> str:
    return json.dumps(
        {"offset": offset, "stream": stream_key, "v": JIRA_CURSOR_VERSION},
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_nested_issue_cursor(
    value: str | None,
    *,
    stream_key: str,
) -> _NestedIssueCursor:
    if value is None:
        return _NestedIssueCursor(
            next_issue_token=None,
            current_issue_id=None,
            current_issue_is_last=False,
            item_offset=0,
        )
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor(stream_key) from error
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "current_issue_id",
            "current_issue_is_last",
            "item_offset",
            "next_issue_token",
            "stream",
            "v",
        }
        or payload.get("stream") != stream_key
        or payload.get("v") != JIRA_CURSOR_VERSION
    ):
        raise _invalid_cursor(stream_key)
    current_issue_id = _optional_id(payload.get("current_issue_id"))
    next_issue_token = _optional_string(payload.get("next_issue_token"))
    is_last = payload.get("current_issue_is_last")
    item_offset = payload.get("item_offset")
    if (
        not isinstance(is_last, bool)
        or isinstance(item_offset, bool)
        or not isinstance(item_offset, int)
        or item_offset < 0
        or next_issue_token is not None
        and len(next_issue_token) > 4_096
    ):
        raise _invalid_cursor(stream_key)
    if current_issue_id is None:
        if is_last or item_offset != 0:
            raise _invalid_cursor(stream_key)
    elif not is_last and next_issue_token is None:
        raise _invalid_cursor(stream_key)
    return _NestedIssueCursor(
        next_issue_token=next_issue_token,
        current_issue_id=current_issue_id,
        current_issue_is_last=is_last,
        item_offset=item_offset,
    )


def _encode_nested_issue_cursor(
    cursor: _NestedIssueCursor,
    *,
    stream_key: str,
) -> str:
    return json.dumps(
        {
            "current_issue_id": cursor.current_issue_id,
            "current_issue_is_last": cursor.current_issue_is_last,
            "item_offset": cursor.item_offset,
            "next_issue_token": cursor.next_issue_token,
            "stream": stream_key,
            "v": JIRA_CURSOR_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_sprint_cursor(value: str | None) -> _SprintCursor:
    if value is None:
        return _SprintCursor(
            board_offset=0,
            board_id=None,
            board_is_last=False,
            project_external_id=None,
            sprint_offset=0,
        )
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid_cursor("sprints") from error
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "board_id",
            "board_is_last",
            "board_offset",
            "project_external_id",
            "sprint_offset",
            "stream",
            "v",
        }
        or payload.get("stream") != "sprints"
        or payload.get("v") != JIRA_CURSOR_VERSION
    ):
        raise _invalid_cursor("sprints")
    board_offset = payload.get("board_offset")
    sprint_offset = payload.get("sprint_offset")
    board_is_last = payload.get("board_is_last")
    if (
        isinstance(board_offset, bool)
        or not isinstance(board_offset, int)
        or board_offset < 0
        or isinstance(sprint_offset, bool)
        or not isinstance(sprint_offset, int)
        or sprint_offset < 0
        or not isinstance(board_is_last, bool)
    ):
        raise _invalid_cursor("sprints")
    board_id = _optional_id(payload.get("board_id"))
    project_external_id = _optional_id(payload.get("project_external_id"))
    if board_id is None and (
        board_is_last or project_external_id is not None or sprint_offset != 0
    ):
        raise _invalid_cursor("sprints")
    return _SprintCursor(
        board_offset=board_offset,
        board_id=board_id,
        board_is_last=board_is_last,
        project_external_id=project_external_id,
        sprint_offset=sprint_offset,
    )


def _encode_sprint_cursor(cursor: _SprintCursor) -> str:
    return json.dumps(
        {
            "board_id": cursor.board_id,
            "board_is_last": cursor.board_is_last,
            "board_offset": cursor.board_offset,
            "project_external_id": cursor.project_external_id,
            "sprint_offset": cursor.sprint_offset,
            "stream": "sprints",
            "v": JIRA_CURSOR_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _maximum_issue_updated_at(
    rows: Sequence[Mapping[str, object]],
    *,
    current: datetime | None,
) -> datetime | None:
    result = current
    for row in rows:
        fields = _object(row.get("fields"), field="Jira issue fields")
        updated = _required_datetime(fields.get("updated"), field="Jira issue update time")
        if result is None or updated > result:
            result = updated
    return result


def _invalid_cursor(stream_key: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_cursor_invalid",
        f"The Jira {stream_key} cursor is invalid.",
        retryable=False,
    )


def _require_stream(value: str, *, selected: tuple[str, ...]) -> str:
    if value not in _STREAM_ENTITY or value not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unsupported",
            "The requested Jira stream is not selected for this source.",
            retryable=False,
        )
    return value


def _jira_site_origin(value: str | None) -> str:
    normalized = _normalized_origin(value)
    if normalized is None or not normalized.removeprefix("https://").endswith(".atlassian.net"):
        raise SorVendorOperationError(
            "vendor_site_invalid",
            "Jira Cloud requires an exact HTTPS *.atlassian.net site URL.",
            retryable=False,
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
            "vendor_identifier_invalid",
            "A Jira source identifier is invalid.",
            retryable=False,
        )
    return normalized


def _comment_external_id(issue_id: str, comment_id: str) -> str:
    return f"{_path_segment(issue_id)}:{_path_segment(comment_id)}"


def _split_comment_external_id(value: str) -> tuple[str, str]:
    parts = value.split(":")
    if len(parts) != 2:
        raise SorVendorOperationError(
            "vendor_identifier_invalid",
            "A Jira comment identity is invalid.",
            retryable=False,
        )
    return _path_segment(parts[0]), _path_segment(parts[1])


def _jira_relation_kind(
    value: object,
    *,
    error_code: str = "vendor_command_invalid",
) -> TicketingRelationKind:
    if isinstance(value, TicketingRelationKind):
        return value
    if not isinstance(value, str):
        normalized = ""
    else:
        normalized = value.strip().upper()
    try:
        return TicketingRelationKind(normalized)
    except ValueError as error:
        raise SorVendorOperationError(
            error_code,
            "The Jira relation kind is invalid.",
            retryable=False,
        ) from error


def _jira_relation_kind_from_type(
    link_type: Mapping[str, object],
) -> TicketingRelationKind:
    vocabulary = " ".join(
        value.casefold()
        for value in (
            _optional_string(link_type.get("name")),
            _optional_string(link_type.get("inward")),
            _optional_string(link_type.get("outward")),
        )
        if value
    )
    if "duplicat" in vocabulary:
        return TicketingRelationKind.DUPLICATE
    if "block" in vocabulary:
        return TicketingRelationKind.BLOCKS
    return TicketingRelationKind.RELATED


def _jira_link_type_matches(
    link_type: Mapping[str, object],
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
            _optional_string(link_type.get("name")),
            _optional_string(link_type.get("inward")),
            _optional_string(link_type.get("outward")),
        )
        if value
    )
    return "relat" in vocabulary


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This Jira action requires an existing issue.")
    return _required_id(command.target_external_id, field="Jira issue ID")


def _single_string_payload(
    payload: Mapping[str, object],
    *,
    key: str,
    field: str,
) -> str:
    if set(payload) != {key}:
        raise _invalid_command(f"This Jira action requires only {key}.")
    return _required_command_string(payload.get(key), field=field)


def _single_nullable_string_payload(
    payload: Mapping[str, object],
    *,
    key: str,
    field: str,
) -> str | None:
    if set(payload) != {key}:
        raise _invalid_command(f"This Jira action requires only {key}.")
    value = payload.get(key)
    return None if value is None else _required_command_string(value, field=field)


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


def _adf_document_or_none(value: object) -> object | None:
    if value is None:
        return None
    text = _required_command_string(value, field="Jira description")
    return {
        "content": [
            {"content": [{"text": text, "type": "text"}], "type": "paragraph"}
        ],
        "type": "doc",
        "version": 1,
    }


def _adf_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    parts: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, Mapping):
            return
        node_type = node.get("type")
        text = node.get("text")
        if isinstance(text, str):
            parts.append(text)
        if node_type == "hardBreak":
            parts.append("\n")
        walk(node.get("content"))
        if node_type in {"blockquote", "bulletList", "heading", "listItem", "orderedList", "paragraph"}:
            parts.append("\n")

    walk(value)
    result = "".join(parts).strip()
    return result[:262_144] or None


def _normalized_jira_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold().replace("_", " ")
    return {
        "new": "UNSTARTED",
        "to do": "UNSTARTED",
        "indeterminate": "STARTED",
        "in progress": "STARTED",
        "done": "COMPLETED",
        "complete": "COMPLETED",
    }.get(normalized, value.strip().upper().replace(" ", "_"))


def _nested_id(value: object, *, key: str = "id") -> str | None:
    if value is None:
        return None
    return _optional_string(_object(value, field="Jira reference").get(key))


def _nested_string(value: object, key: str) -> str | None:
    if value is None:
        return None
    return _optional_string(_object(value, field="Jira value").get(key))


def _request_id(response: SorJsonResponse) -> str | None:
    for name in ("atl-traceid", "x-arequestid", "x-request-id"):
        values = response.header_values(name)
        if values:
            return values[0][:512]
    return None


def _raise_unknown_create(error: SorVendorOperationError, message: str) -> None:
    if error.code in {"vendor_timeout", "vendor_transport_failed", "vendor_server_failed"}:
        raise SorVendorOperationError(
            "vendor_mutation_outcome_unknown",
            message,
            retryable=False,
        ) from error


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise SorVendorOperationError(
            "vendor_credentials_invalid",
            "The Jira credential is unavailable.",
            retryable=False,
            requires_reauthorization=True,
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
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
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


def _json_value(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    raise _invalid_response("Jira source content is not JSON-compatible.")


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_command_invalid",
        message,
        retryable=False,
    )


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_response_invalid",
        message,
        retryable=False,
    )


__all__ = [
    "JIRA_API_ORIGIN",
    "JIRA_API_VERSION",
    "JIRA_MANIFEST",
    "JiraTicketingAdapter",
    "create_jira_adapter",
]
