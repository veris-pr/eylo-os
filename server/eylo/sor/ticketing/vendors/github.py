"""GitHub Issues adapter for Eylo's canonical ticketing profile."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlparse

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorAdapterConfigurationFieldSpec,
    SorAdapterContext,
    SorCapabilityUnavailable,
    SorChangeStrategy,
    SorCommandRequest,
    SorCommandResult,
    SorConfigurationFieldKind,
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
    SorWebhookPayloadError,
    SorWebhookSignal,
    SorWebhookSubscription,
    SorWebhookVerificationError,
)
from eylo.sor.ticketing.contracts import (
    TicketingComment,
    TicketingCycle,
    TicketingIssue,
    TicketingIssueRelation,
    TicketingLabel,
    TicketingProject,
    TicketingUser,
    TicketingWorkflowState,
)

GITHUB_ORIGIN = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_CURSOR_VERSION = 2
GITHUB_RECONCILIATION_OVERLAP = timedelta(minutes=5)

REPOSITORY_SCOPE = "repo"
READ_USER_SCOPE = "read:user"

_REPOSITORY = re.compile(r"^[^/\s]{1,100}/[^/\s]{1,100}$")
_STREAM_ENTITY = {
    "repositories": "project",
    "issues": "issue",
    "workflow_states": "workflow_state",
    "users": "user",
    "labels": "label",
    "milestones": "cycle",
    "comments": "comment",
}
_UPDATED_STREAMS = frozenset({"issues", "comments"})
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
    }
)
_TOOL_STREAMS = {
    "issue_search": frozenset({"issues"}),
    "issue_get": frozenset({"issues"}),
    "issue_list_projects": frozenset({"repositories"}),
    "issue_list_workflow_states": frozenset({"workflow_states"}),
    "issue_describe_fields": frozenset({"issues"}),
    "issue_create": frozenset({"issues", "repositories"}),
    "issue_update": frozenset({"issues"}),
    "issue_transition": frozenset({"issues", "workflow_states"}),
    "issue_assign": frozenset({"issues", "users"}),
    "issue_add_label": frozenset({"issues", "labels"}),
    "issue_remove_label": frozenset({"issues", "labels"}),
    "issue_comment": frozenset({"issues", "comments"}),
}
_MUTATION_RESULT_STREAMS = {
    **{tool_name: "issues" for tool_name in _WRITE_TOOLS},
    "issue_comment": "comments",
}


GITHUB_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.TICKETING,
    vendor_key="github",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                "repositories": "Repositories",
                "issues": "Issues",
                "workflow_states": "Workflow states",
                "users": "Assignees",
                "labels": "Labels",
                "milestones": "Milestones",
                "comments": "Comments",
            }[stream_key],
            description={
                "repositories": "Explicitly selected GitHub repositories used as work containers.",
                "issues": "Repository issues; pull requests are excluded from this stream.",
                "workflow_states": "GitHub open, completed, and not-planned issue states.",
                "users": "Users assignable to issues in the selected repositories.",
                "labels": "Repository-scoped issue labels.",
                "milestones": "Repository milestones used to time-box issues.",
                "comments": "Repository issue comments; pull-request comments are excluded.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.UPDATED_AT})
                if stream_key in _UPDATED_STREAMS
                else frozenset({SorChangeStrategy.FULL_RECONCILE})
            ),
        )
        for stream_key, entity in _STREAM_ENTITY.items()
    ),
    readable_entities=frozenset(_STREAM_ENTITY.values()),
    writable_entities=frozenset({"issue", "comment"}),
    readable_tools=_READ_TOOLS,
    writable_tools=_WRITE_TOOLS,
    change_strategies=frozenset(
        {SorChangeStrategy.UPDATED_AT, SorChangeStrategy.FULL_RECONCILE}
    ),
    configuration_fields=(
        SorAdapterConfigurationFieldSpec(
            key="repositories",
            label="Repositories",
            description="Enter one owner/repository per line. Eylo will not sync other repositories available to the OAuth token.",
            kind=SorConfigurationFieldKind.STRING_LIST,
            required=True,
            placeholder="octo-org/customer-portal",
            minimum_items=1,
            maximum_items=50,
        ),
    ),
    required_scopes={stream_key: (REPOSITORY_SCOPE,) for stream_key in _STREAM_ENTITY},
    tool_required_scopes={tool_name: (REPOSITORY_SCOPE,) for tool_name in _WRITE_TOOLS},
    tool_streams=_TOOL_STREAMS,
    mutation_result_streams=_MUTATION_RESULT_STREAMS,
    oauth=SorOAuthSpec(
        authorization_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        base_scopes=(READ_USER_SCOPE,),
        scope_response_delimiter=",",
    ),
    fixed_origin=GITHUB_ORIGIN,
    supports_webhooks=True,
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
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        description=description,
        group="GitHub",
    )


_SCHEMA_FIELDS = {
    "repositories": (
        _field("key", "Repository", "text", nullable=False),
        _field("name", "Name", "text", nullable=False),
        _field("description", "Description", "text"),
    ),
    "issues": (
        _field("key", "Key", "text", nullable=False),
        _field("title", "Title", "text", nullable=False, writable=True),
        _field("normalized_description", "Description", "text", writable=True),
        _field("source_description", "Source description", "bounded_json"),
        _field("issue_type", "Type", "text"),
        _field("native_status", "Source status", "text"),
        _field("normalized_status", "Normalized status", "enum"),
        _field("priority", "Priority", "text"),
        _field("project_external_id", "Repository", "reference", nullable=False),
        _field("team_external_id", "Owner", "reference"),
        _field("assignee_external_id", "Assignee", "reference", writable=True),
        _field("reporter_external_id", "Reporter", "reference"),
        _field("estimate", "Estimate", "decimal"),
        _field("label_external_ids", "Labels", "string_array", writable=True),
        _field("parent_external_id", "Parent issue", "reference"),
        _field("cycle_external_id", "Milestone", "reference", writable=True),
        _field("due_date", "Due date", "date"),
        _field("started_at", "Started at", "timestamp"),
        _field("completed_at", "Completed at", "timestamp"),
        _field("cancelled_at", "Cancelled at", "timestamp"),
    ),
    "workflow_states": (
        _field("name", "Name", "text", nullable=False),
        _field("native_category", "Source category", "text"),
        _field("normalized_category", "Normalized category", "enum"),
        _field("order", "Order", "integer"),
    ),
    "users": (
        _field("name", "Login", "text", nullable=False),
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
        _field("project_external_id", "Repository", "reference", nullable=False),
        _field("parent_external_id", "Parent label", "reference"),
        _field("is_group", "Group", "boolean", nullable=False),
    ),
    "milestones": (
        _field("name", "Name", "text", nullable=False),
        _field("number", "Number", "integer", nullable=False),
        _field("project_external_id", "Repository", "reference", nullable=False),
        _field("description", "Description", "text"),
        _field("starts_at", "Starts at", "timestamp"),
        _field("ends_at", "Due at", "timestamp"),
        _field("completed_at", "Closed at", "timestamp"),
        _field("active", "Active", "boolean"),
    ),
    "comments": (
        _field("issue_external_id", "Issue", "reference", nullable=False),
        _field("author_external_id", "Author", "reference"),
        _field("normalized_text", "Comment", "text", nullable=False),
        _field("source_body", "Source body", "bounded_json"),
        _field("created_at", "Created at", "timestamp", nullable=False),
        _field("updated_at", "Updated at", "timestamp"),
    ),
}

_WORKFLOW_ROWS = (
    {
        "id": "open",
        "name": "Open",
        "native_category": "open",
        "normalized_category": "UNSTARTED",
        "order": 1,
    },
    {
        "id": "closed:completed",
        "name": "Completed",
        "native_category": "closed/completed",
        "normalized_category": "COMPLETED",
        "order": 2,
    },
    {
        "id": "closed:not_planned",
        "name": "Not planned",
        "native_category": "closed/not_planned",
        "normalized_category": "CANCELLED",
        "order": 3,
    },
)


@dataclass(frozen=True, slots=True)
class _GitHubCursor:
    floor: datetime | None
    repo_index: int
    page: int
    started_at: datetime
    complete: bool = False


class GitHubTicketingAdapter:
    """Translate explicitly selected GitHub repositories into ticketing records."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "github":
            raise ValueError("GitHub adapter requires the github vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("GitHub Issues SOR requires OAuth 2.0.")
        self._context = context
        self._repositories = _configured_repositories(context.configuration)
        token = _credential(context.credentials, "access_token")
        self._client = SorJsonHttpClient(
            origin=GITHUB_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
            default_headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )

    async def verify_connection(self) -> SorConnectionVerification:
        response = await self._client.request("/user")
        viewer = _object(_expect(response, operation="verify GitHub account"))
        await self._repository_metadata(self._repositories)
        login = _required_string(viewer.get("login"), field="GitHub login")
        return SorConnectionVerification(
            account_external_id=login,
            account_display_name=_optional_string(viewer.get("name")) or login,
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=GITHUB_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        if not self._context.selected_objects:
            raise _invalid_configuration("The GitHub source selects no streams.")
        streams = {stream.key: stream for stream in GITHUB_MANIFEST.streams}
        objects: list[SorDiscoveredObject] = []
        for stream_key in self._context.selected_objects:
            stream_key = _require_stream(
                stream_key,
                selected=self._context.selected_objects,
            )
            objects.append(
                SorDiscoveredObject(
                    key=stream_key,
                    label=streams[stream_key].label,
                    fields=_SCHEMA_FIELDS[stream_key],
                )
            )
        return SorDiscoveredSchema(
            objects=tuple(objects),
            vendor_api_version=GITHUB_API_VERSION,
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
        if stream_key == "workflow_states":
            row = next(
                (row for row in _WORKFLOW_ROWS if row["id"] == external_id),
                None,
            )
            if row is None:
                raise SorExternalRecordNotFound(
                    vendor_object_key=stream_key,
                    external_id=external_id,
                )
            return self._external_record(stream_key, row)
        if stream_key == "repositories":
            repository = self._configured_repository(external_id)
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}"
            )
        elif stream_key == "issues":
            repository, issue_number = self._issue_identity(external_id)
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/issues/{issue_number}"
            )
        elif stream_key == "comments":
            repository, comment_id = self._comment_identity(external_id)
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/issues/comments/{comment_id}"
            )
        elif stream_key == "labels":
            repository, label_name = self._label_identity(external_id)
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/labels/{_path_segment(label_name)}"
            )
        elif stream_key == "milestones":
            repository, milestone_number = self._milestone_identity(external_id)
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/milestones/{milestone_number}"
            )
        else:
            login = _required_string(external_id, field="GitHub user login")
            response = await self._client.request(f"/users/{_path_segment(login)}")
        if response.status_code in {404, 410}:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=external_id,
            )
        row = _object(_expect(response, operation="read GitHub record"))
        if stream_key == "issues" and "pull_request" in row:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=external_id,
                reason="GitHub pull requests are outside the issue stream",
            )
        repository = self._record_repository(stream_key, external_id, row)
        return self._external_record(stream_key, row, repository=repository)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "GitHub deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "GitHub webhooks require operator-owned repository webhook configuration."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "GitHub repository webhooks do not use Eylo-managed leases."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "GitHub webhooks require operator-owned repository webhook configuration."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        secret = self._context.webhook_signing_secret
        if secret is None:
            raise SorWebhookVerificationError(
                "GitHub webhook signing secret is not configured."
            )
        signature = _header(headers, "x-hub-signature-256")
        if signature is None or not re.fullmatch(r"sha256=[0-9a-fA-F]{64}", signature):
            raise SorWebhookVerificationError("GitHub webhook signature is invalid.")
        expected = (
            "sha256="
            + hmac.new(
                secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(signature.lower(), expected):
            raise SorWebhookVerificationError("GitHub webhook signature is invalid.")
        _webhook_body(body, verification=True)

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        payload = _webhook_body(body, verification=False)
        event_name = _required_header(headers, "x-github-event", "event")
        delivery_id = _required_header(headers, "x-github-delivery", "delivery ID")
        action = _optional_string(payload.get("action")) or "received"
        repository_row = _optional_object(payload.get("repository"))
        repository = _optional_string(repository_row.get("full_name"))
        configured_repository = self._optional_configured_repository(repository)

        stream_key: str | None = None
        external_id: str | None = None
        occurred_at: datetime | None = None
        if configured_repository is not None:
            stream_key, external_id, occurred_at = _webhook_record_identity(
                event_name,
                payload,
                repository=configured_repository,
            )
        if stream_key not in self._context.selected_objects:
            stream_key = None
            external_id = None
        return (
            SorWebhookSignal(
                delivery_id=delivery_id,
                event_type=f"{event_name}.{action}",
                vendor_object_key=stream_key,
                external_id=external_id,
                occurred_at=occurred_at,
            ),
        )

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                "vendor_tool_unsupported",
                "This GitHub adapter does not execute the requested issue action.",
                retryable=False,
            )
        if command.tool_name == "issue_create":
            return await self._create_issue(command)
        target = _required_target(command)
        repository, issue_number = self._issue_identity(target)
        if command.tool_name == "issue_update":
            return await self._update_issue(repository, issue_number, target, command)
        if command.tool_name == "issue_transition":
            return await self._transition_issue(
                repository, issue_number, target, command
            )
        if command.tool_name == "issue_assign":
            return await self._assign_issue(repository, issue_number, target, command)
        if command.tool_name == "issue_comment":
            return await self._comment_issue(repository, issue_number, command)
        return await self._change_label(
            repository,
            issue_number,
            target,
            command,
            add=command.tool_name == "issue_add_label",
        )

    def normalize_issue(self, record: SorExternalRecord) -> TicketingIssue:
        values = record.payload
        return TicketingIssue(
            external_id=record.external_id,
            key=_optional_string(values.get("key")),
            title=_required_string(values.get("title"), field="GitHub issue title"),
            normalized_description=_optional_string(
                values.get("normalized_description")
            ),
            source_description=_json_value(values.get("source_description")),
            issue_type=_optional_string(values.get("issue_type")),
            native_status=_optional_string(values.get("native_status")),
            normalized_status=_optional_string(values.get("normalized_status")),
            priority=None,
            project_external_id=_optional_string(values.get("project_external_id")),
            team_external_id=_optional_string(values.get("team_external_id")),
            assignee_external_id=_optional_string(values.get("assignee_external_id")),
            reporter_external_id=_optional_string(values.get("reporter_external_id")),
            estimate=None,
            label_external_ids=_string_tuple(values.get("label_external_ids")),
            parent_external_id=None,
            cycle_external_id=_optional_string(values.get("cycle_external_id")),
            due_date=None,
            started_at=None,
            completed_at=_optional_datetime(values.get("completed_at")),
            cancelled_at=_optional_datetime(values.get("cancelled_at")),
            source_updated_at=record.source_updated_at,
            source_url=record.source_url,
        )

    def normalize_project(self, record: SorExternalRecord) -> TicketingProject:
        return TicketingProject(
            external_id=record.external_id,
            key=_optional_string(record.payload.get("key")),
            name=_required_string(
                record.payload.get("name"),
                field="GitHub repository name",
            ),
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
                field="GitHub workflow state name",
            ),
            native_category=_optional_string(record.payload.get("native_category")),
            normalized_category=_optional_string(
                record.payload.get("normalized_category")
            ),
            order=_optional_integer(
                record.payload.get("order"),
                field="GitHub workflow state order",
            ),
        )

    def normalize_user(self, record: SorExternalRecord) -> TicketingUser:
        values = record.payload
        return TicketingUser(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="GitHub user login"),
            display_name=_optional_string(values.get("display_name")),
            primary_email=_optional_string(values.get("primary_email")),
            active=_required_boolean(values.get("active"), field="GitHub user active"),
            assignable=_optional_boolean(values.get("assignable")),
            avatar_url=_optional_string(values.get("avatar_url")),
            source_url=record.source_url,
        )

    def normalize_label(self, record: SorExternalRecord) -> TicketingLabel:
        values = record.payload
        return TicketingLabel(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="GitHub label name"),
            description=_optional_string(values.get("description")),
            color=_optional_string(values.get("color")),
            project_external_id=_optional_string(values.get("project_external_id")),
            parent_external_id=None,
            is_group=False,
        )

    def normalize_cycle(self, record: SorExternalRecord) -> TicketingCycle:
        values = record.payload
        return TicketingCycle(
            external_id=record.external_id,
            name=_required_string(values.get("name"), field="GitHub milestone name"),
            number=_optional_integer(
                values.get("number"),
                field="GitHub milestone number",
            ),
            project_external_id=_optional_string(values.get("project_external_id")),
            description=_optional_string(values.get("description")),
            starts_at=None,
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
                field="GitHub comment issue",
            ),
            author_external_id=_optional_string(values.get("author_external_id")),
            normalized_text=_required_string(
                values.get("normalized_text"),
                field="GitHub comment body",
            ),
            source_body=_json_value(values.get("source_body")),
            created_at=_required_datetime(
                values.get("created_at"),
                field="GitHub comment creation time",
            ),
            updated_at=_optional_datetime(values.get("updated_at")),
        )

    def normalize_relation(
        self,
        record: SorExternalRecord,
    ) -> TicketingIssueRelation:
        raise SorCapabilityUnavailable(
            "GitHub issue relations are not available in this adapter revision."
        )

    async def close(self) -> None:
        """GitHub's bounded HTTP transport owns no persistent session."""

    async def _read_page(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> SorRecordPage:
        stream_key = _require_stream(
            stream_key,
            selected=self._context.selected_objects,
        )
        if limit <= 0:
            raise SorVendorOperationError(
                "vendor_page_invalid",
                "GitHub page limit must be positive.",
                retryable=False,
            )
        limit = min(limit, 100)
        checkpoint = _start_cursor(_decode_cursor(cursor))
        if stream_key == "workflow_states":
            return self._static_page(
                stream_key,
                _WORKFLOW_ROWS,
                checkpoint=checkpoint,
                limit=limit,
            )
        if stream_key == "repositories":
            selected_repositories = self._repositories[
                checkpoint.repo_index : checkpoint.repo_index + limit
            ]
            metadata = await self._repository_metadata(selected_repositories)
            rows = tuple(
                self._external_record(
                    "repositories",
                    metadata[repository.casefold()],
                    repository=repository,
                )
                for repository in selected_repositories
            )
            return _sliced_page(
                rows,
                checkpoint=checkpoint,
                consumed=len(rows),
                total=len(self._repositories),
            )
        if stream_key == "comments":
            return await self._read_comment_page(
                checkpoint=checkpoint,
                limit=limit,
            )
        if checkpoint.repo_index >= len(self._repositories):
            raise _invalid_cursor()
        repository = self._repositories[checkpoint.repo_index]
        query: dict[str, object] = {
            "per_page": limit,
            "page": checkpoint.page,
        }
        if stream_key == "issues":
            path = f"/repos/{_repository_path(repository)}/issues"
            query.update({"state": "all", "sort": "updated", "direction": "asc"})
        elif stream_key == "users":
            path = f"/repos/{_repository_path(repository)}/assignees"
        elif stream_key == "labels":
            path = f"/repos/{_repository_path(repository)}/labels"
        else:
            path = f"/repos/{_repository_path(repository)}/milestones"
            query["state"] = "all"
        if stream_key in _UPDATED_STREAMS and checkpoint.floor is not None:
            query["since"] = _github_datetime(
                checkpoint.floor - GITHUB_RECONCILIATION_OVERLAP
            )
        response = await self._client.request(path, query=query)
        raw_rows = _object_list(
            _expect(response, operation=f"list GitHub {stream_key}"),
            field=f"GitHub {stream_key}",
        )
        rows = tuple(
            self._external_record(stream_key, row, repository=repository)
            for row in raw_rows
            if not (stream_key == "issues" and "pull_request" in row)
        )
        return _vendor_page(
            rows,
            checkpoint=checkpoint,
            raw_count=len(raw_rows),
            page_size=limit,
            repository_count=len(self._repositories),
        )

    async def _read_comment_page(
        self,
        *,
        checkpoint: _GitHubCursor,
        limit: int,
    ) -> SorRecordPage:
        """Page by comment revision, then remove pull-request comments exactly."""
        if checkpoint.repo_index >= len(self._repositories):
            raise _invalid_cursor()
        repository = self._repositories[checkpoint.repo_index]
        query: dict[str, object] = {
            "sort": "updated",
            "direction": "asc",
            "per_page": limit,
            "page": checkpoint.page,
        }
        if checkpoint.floor is not None:
            query["since"] = _github_datetime(
                checkpoint.floor - GITHUB_RECONCILIATION_OVERLAP
            )
        response = await self._client.request(
            f"/repos/{_repository_path(repository)}/issues/comments",
            query=query,
        )
        rows = _object_list(
            _expect(response, operation="list GitHub issue comments"),
            field="GitHub issue comments",
        )
        issue_numbers = {
            _issue_number_from_url(row.get("issue_url"), repository) for row in rows
        }
        pull_request_numbers = await self._pull_request_numbers(
            repository,
            issue_numbers,
        )
        records = tuple(
            self._external_record("comments", row, repository=repository)
            for row in rows
            if _issue_number_from_url(row.get("issue_url"), repository)
            not in pull_request_numbers
        )
        return _vendor_page(
            records,
            checkpoint=checkpoint,
            raw_count=len(rows),
            page_size=limit,
            repository_count=len(self._repositories),
        )

    async def _pull_request_numbers(
        self,
        repository: str,
        issue_numbers: set[int],
    ) -> frozenset[int]:
        if not issue_numbers:
            return frozenset()
        owner, name = repository.split("/", 1)
        ordered_numbers = tuple(sorted(issue_numbers))
        fields = " ".join(
            f"item{index}: issueOrPullRequest(number: {number}) {{ __typename }}"
            for index, number in enumerate(ordered_numbers)
        )
        response = await self._client.request(
            "/graphql",
            method="POST",
            payload={
                "query": (
                    "query($owner: String!, $name: String!) { "
                    "repository(owner: $owner, name: $name) { "
                    f"{fields}"
                    " } }"
                ),
                "variables": {"owner": owner, "name": name},
            },
        )
        data = _expect_graphql(response, operation="classify GitHub issue comments")
        repository_row = _object(
            data.get("repository"),
            field="GitHub GraphQL repository",
        )
        pull_requests: set[int] = set()
        for index, number in enumerate(ordered_numbers):
            row = _object(
                repository_row.get(f"item{index}"),
                field="GitHub issue kind",
            )
            typename = _required_string(
                row.get("__typename"),
                field="GitHub issue kind",
            )
            if typename == "PullRequest":
                pull_requests.add(number)
            elif typename != "Issue":
                raise _invalid_response("GitHub returned an unsupported issue kind.")
        return frozenset(pull_requests)

    def _static_page(
        self,
        stream_key: str,
        rows: Sequence[Mapping[str, object]],
        *,
        checkpoint: _GitHubCursor,
        limit: int,
    ) -> SorRecordPage:
        selected = rows[checkpoint.repo_index : checkpoint.repo_index + limit]
        records = tuple(self._external_record(stream_key, row) for row in selected)
        return _sliced_page(
            records,
            checkpoint=checkpoint,
            consumed=len(records),
            total=len(rows),
        )

    async def _repository_metadata(
        self,
        repositories: Sequence[str],
    ) -> dict[str, Mapping[str, object]]:
        """Read a bounded repository set without one HTTP request per repository."""
        if not repositories:
            return {}
        fields: list[str] = []
        variables: dict[str, object] = {}
        declarations: list[str] = []
        for index, repository in enumerate(repositories):
            owner, name = repository.split("/", 1)
            owner_variable = f"owner{index}"
            name_variable = f"name{index}"
            declarations.extend(
                (f"${owner_variable}: String!", f"${name_variable}: String!")
            )
            variables[owner_variable] = owner
            variables[name_variable] = name
            fields.append(
                f"repo{index}: repository("
                f"owner: ${owner_variable}, name: ${name_variable}"
                ") { nameWithOwner description url updatedAt }"
            )
        response = await self._client.request(
            "/graphql",
            method="POST",
            payload={
                "query": (
                    f"query({', '.join(declarations)}) {{ "
                    f"{' '.join(fields)}"
                    " }"
                ),
                "variables": variables,
            },
        )
        data = _expect_graphql(response, operation="read configured repositories")
        metadata: dict[str, Mapping[str, object]] = {}
        for index, configured_repository in enumerate(repositories):
            row = _object(
                data.get(f"repo{index}"),
                field="GitHub GraphQL repository",
            )
            repository = _repository(
                _required_string(
                    row.get("nameWithOwner"),
                    field="GitHub repository",
                )
            )
            if repository.casefold() != configured_repository.casefold():
                raise _invalid_response(
                    "GitHub returned a repository outside the source configuration."
                )
            metadata[configured_repository.casefold()] = {
                "full_name": configured_repository,
                "description": _optional_string(row.get("description")),
                "html_url": _safe_github_url(row.get("url")),
                "updated_at": _optional_datetime(row.get("updatedAt")),
            }
        return metadata

    async def _create_issue(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise _invalid_command(
                "Creating a GitHub issue cannot target an existing issue."
            )
        repository = self._configured_repository(
            _required_command_string(
                command.payload.get("project_external_id"),
                field="GitHub repository",
            )
        )
        payload = _github_issue_payload(
            command.payload,
            create=True,
            repository=repository,
        )
        try:
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/issues",
                method="POST",
                payload=payload,
                idempotency_key=command.idempotency_key,
            )
            row = _object(_expect(response, operation="create GitHub issue"))
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error,
                "GitHub may have created the issue; reconcile before retrying.",
            )
            raise
        return _issue_command_result(repository, row, response=response)

    async def _update_issue(
        self,
        repository: str,
        issue_number: int,
        external_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        payload = _github_issue_payload(
            command.payload,
            create=False,
            repository=repository,
        )
        response = await self._client.request(
            f"/repos/{_repository_path(repository)}/issues/{issue_number}",
            method="PATCH",
            payload=payload,
            idempotency_key=command.idempotency_key,
        )
        row = _object(_expect(response, operation="update GitHub issue"))
        return _issue_command_result(
            repository,
            row,
            response=response,
            fallback_external_id=external_id,
        )

    async def _transition_issue(
        self,
        repository: str,
        issue_number: int,
        external_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) != {"workflow_state_external_id"}:
            raise _invalid_command(
                "Transitioning a GitHub issue requires only workflow_state_external_id."
            )
        workflow = _required_command_string(
            command.payload.get("workflow_state_external_id"),
            field="GitHub workflow state",
        )
        payload = {
            "open": {"state": "open", "state_reason": "reopened"},
            "closed:completed": {"state": "closed", "state_reason": "completed"},
            "closed:not_planned": {
                "state": "closed",
                "state_reason": "not_planned",
            },
        }.get(workflow)
        if payload is None:
            raise _invalid_command("The requested GitHub workflow state is invalid.")
        response = await self._client.request(
            f"/repos/{_repository_path(repository)}/issues/{issue_number}",
            method="PATCH",
            payload=payload,
            idempotency_key=command.idempotency_key,
        )
        row = _object(_expect(response, operation="transition GitHub issue"))
        return _issue_command_result(
            repository,
            row,
            response=response,
            fallback_external_id=external_id,
        )

    async def _assign_issue(
        self,
        repository: str,
        issue_number: int,
        external_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) != {"assignee_external_id"}:
            raise _invalid_command(
                "Assigning a GitHub issue requires only assignee_external_id."
            )
        assignee = _nullable_command_string(
            command.payload.get("assignee_external_id"),
            field="GitHub assignee",
        )
        response = await self._client.request(
            f"/repos/{_repository_path(repository)}/issues/{issue_number}",
            method="PATCH",
            payload={"assignees": [] if assignee is None else [assignee]},
            idempotency_key=command.idempotency_key,
        )
        row = _object(_expect(response, operation="assign GitHub issue"))
        return _issue_command_result(
            repository,
            row,
            response=response,
            fallback_external_id=external_id,
        )

    async def _change_label(
        self,
        repository: str,
        issue_number: int,
        external_id: str,
        command: SorCommandRequest,
        *,
        add: bool,
    ) -> SorCommandResult:
        if set(command.payload) != {"label_external_id"}:
            raise _invalid_command(
                "Changing a GitHub issue label requires only label_external_id."
            )
        label_repository, label_name = self._label_identity(
            _required_command_string(
                command.payload.get("label_external_id"),
                field="GitHub label ID",
            )
        )
        if label_repository.casefold() != repository.casefold():
            raise _invalid_command(
                "A GitHub label must belong to the issue repository."
            )
        path = f"/repos/{_repository_path(repository)}/issues/{issue_number}/labels"
        if add:
            response = await self._client.request(
                path,
                method="POST",
                payload={"labels": [label_name]},
                idempotency_key=command.idempotency_key,
            )
        else:
            response = await self._client.request(
                f"{path}/{_path_segment(label_name)}",
                method="DELETE",
                idempotency_key=command.idempotency_key,
            )
        _expect(response, operation="change GitHub issue label")
        return SorCommandResult(
            vendor_object_key="issues",
            external_id=external_id,
            external_request_id=_request_id(response),
            source_url=_issue_url(external_id),
            response={"status": "accepted"},
        )

    async def _comment_issue(
        self,
        repository: str,
        issue_number: int,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if set(command.payload) != {"text"}:
            raise _invalid_command("Commenting on a GitHub issue requires only text.")
        text = _required_command_string(
            command.payload.get("text"),
            field="GitHub comment",
        )
        try:
            response = await self._client.request(
                f"/repos/{_repository_path(repository)}/issues/{issue_number}/comments",
                method="POST",
                payload={"body": text},
                idempotency_key=command.idempotency_key,
            )
            row = _object(_expect(response, operation="comment on GitHub issue"))
        except SorVendorOperationError as error:
            _raise_unknown_create(
                error,
                "GitHub may have created the comment; reconcile before retrying.",
            )
            raise
        comment_id = _required_integer(row.get("id"), field="GitHub comment ID")
        updated_at = _optional_datetime(row.get("updated_at")) or _required_datetime(
            row.get("created_at"),
            field="GitHub comment creation time",
        )
        return SorCommandResult(
            vendor_object_key="comments",
            external_id=_comment_external_id(repository, comment_id),
            external_request_id=_request_id(response),
            source_revision=_github_datetime(updated_at),
            source_url=_safe_github_url(row.get("html_url")),
            response={"status": "accepted"},
        )

    def _external_record(
        self,
        stream_key: str,
        row: Mapping[str, object],
        *,
        repository: str | None = None,
    ) -> SorExternalRecord:
        payload = _record_payload(stream_key, row, repository=repository)
        external_id = _record_external_id(stream_key, row, repository=repository)
        created_at = _optional_datetime(row.get("created_at"))
        updated_at = _optional_datetime(row.get("updated_at"))
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=external_id,
            payload=payload,
            source_created_at=created_at,
            source_updated_at=updated_at,
            source_revision=(
                _github_datetime(updated_at) if updated_at is not None else None
            ),
            source_url=_record_url(stream_key, row, external_id=external_id),
        )

    def _configured_repository(self, value: str) -> str:
        repository = _repository(value)
        match = self._optional_configured_repository(repository)
        if match is None:
            raise _invalid_command(
                "The GitHub repository is outside this source configuration."
            )
        return match

    def _optional_configured_repository(self, value: str | None) -> str | None:
        if value is None:
            return None
        folded = value.casefold()
        return next(
            (repo for repo in self._repositories if repo.casefold() == folded),
            None,
        )

    def _issue_identity(self, value: str) -> tuple[str, int]:
        repository, issue_number = _issue_identity(value)
        return self._configured_repository(repository), issue_number

    def _comment_identity(self, value: str) -> tuple[str, int]:
        repository, comment_id = _comment_identity(value)
        return self._configured_repository(repository), comment_id

    def _label_identity(self, value: str) -> tuple[str, str]:
        repository, label_name = _label_identity(value)
        return self._configured_repository(repository), label_name

    def _milestone_identity(self, value: str) -> tuple[str, int]:
        repository, milestone_number = _milestone_identity(value)
        return self._configured_repository(repository), milestone_number

    def _record_repository(
        self,
        stream_key: str,
        external_id: str,
        row: Mapping[str, object],
    ) -> str | None:
        if stream_key == "repositories":
            return self._configured_repository(external_id)
        if stream_key == "issues":
            return self._issue_identity(external_id)[0]
        if stream_key == "comments":
            return self._comment_identity(external_id)[0]
        if stream_key == "labels":
            return self._label_identity(external_id)[0]
        if stream_key == "milestones":
            return self._milestone_identity(external_id)[0]
        return None


def create_github_adapter(context: SorAdapterContext) -> GitHubTicketingAdapter:
    """Construct the production GitHub Issues adapter for the registry."""
    return GitHubTicketingAdapter(context)


def _configured_repositories(configuration: Mapping[str, object]) -> tuple[str, ...]:
    value = configuration.get("repositories")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid_configuration(
            "GitHub source configuration requires a repository list."
        )
    repositories = tuple(_repository(item) for item in value)
    if not 1 <= len(repositories) <= 50:
        raise _invalid_configuration(
            "GitHub source configuration requires 1 to 50 repositories."
        )
    folded = [repository.casefold() for repository in repositories]
    if len(folded) != len(set(folded)):
        raise _invalid_configuration("GitHub repositories must be unique.")
    return repositories


def _repository(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid_configuration("GitHub repositories must use owner/repository.")
    normalized = value.strip()
    if (
        not _REPOSITORY.fullmatch(normalized)
        or any(part in {".", ".."} for part in normalized.split("/"))
        or any(character in normalized for character in "?#%")
    ):
        raise _invalid_configuration("GitHub repositories must use owner/repository.")
    return normalized


def _repository_path(repository: str) -> str:
    owner, name = repository.split("/", 1)
    return f"{_path_segment(owner)}/{_path_segment(name)}"


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def _issue_external_id(repository: str, issue_number: int) -> str:
    return f"{repository}#{issue_number}"


def _issue_identity(value: str) -> tuple[str, int]:
    if not isinstance(value, str) or "#" not in value:
        raise _invalid_command("GitHub issue ID must use owner/repository#number.")
    repository, raw_number = value.rsplit("#", 1)
    return _repository(repository), _positive_integer(raw_number, field="issue number")


def _comment_external_id(repository: str, comment_id: int) -> str:
    return f"{repository}@comment/{comment_id}"


def _comment_identity(value: str) -> tuple[str, int]:
    marker = "@comment/"
    if not isinstance(value, str) or marker not in value:
        raise _invalid_command("GitHub comment ID is invalid.")
    repository, raw_id = value.rsplit(marker, 1)
    return _repository(repository), _positive_integer(raw_id, field="comment ID")


def _label_external_id(repository: str, label_name: str) -> str:
    return f"{repository}@label/{quote(label_name, safe='')}"


def _label_identity(value: str) -> tuple[str, str]:
    marker = "@label/"
    if not isinstance(value, str) or marker not in value:
        raise _invalid_command("GitHub label ID is invalid.")
    repository, encoded_name = value.rsplit(marker, 1)
    name = unquote(encoded_name)
    if not name.strip() or len(name) > 100:
        raise _invalid_command("GitHub label ID is invalid.")
    return _repository(repository), name


def _milestone_external_id(repository: str, number: int) -> str:
    return f"{repository}@milestone/{number}"


def _milestone_identity(value: str) -> tuple[str, int]:
    marker = "@milestone/"
    if not isinstance(value, str) or marker not in value:
        raise _invalid_command("GitHub milestone ID is invalid.")
    repository, raw_number = value.rsplit(marker, 1)
    return _repository(repository), _positive_integer(
        raw_number,
        field="milestone number",
    )


def _record_external_id(
    stream_key: str,
    row: Mapping[str, object],
    *,
    repository: str | None,
) -> str:
    if stream_key == "repositories":
        return _repository(_required_string(row.get("full_name"), field="repository"))
    if stream_key == "workflow_states":
        return _required_string(row.get("id"), field="GitHub workflow state ID")
    if stream_key == "users":
        return _required_string(row.get("login"), field="GitHub user login")
    if repository is None:
        raise _invalid_response("GitHub record repository is missing.")
    if stream_key == "issues":
        return _issue_external_id(
            repository,
            _required_integer(row.get("number"), field="GitHub issue number"),
        )
    if stream_key == "comments":
        return _comment_external_id(
            repository,
            _required_integer(row.get("id"), field="GitHub comment ID"),
        )
    if stream_key == "labels":
        return _label_external_id(
            repository,
            _required_string(row.get("name"), field="GitHub label name"),
        )
    return _milestone_external_id(
        repository,
        _required_integer(row.get("number"), field="GitHub milestone number"),
    )


def _record_payload(
    stream_key: str,
    row: Mapping[str, object],
    *,
    repository: str | None,
) -> dict[str, object]:
    if stream_key == "repositories":
        full_name = _repository(
            _required_string(row.get("full_name"), field="GitHub repository")
        )
        return {
            "key": full_name,
            "name": full_name,
            "description": _optional_string(row.get("description")),
        }
    if stream_key == "workflow_states":
        return {
            "name": row.get("name"),
            "native_category": row.get("native_category"),
            "normalized_category": row.get("normalized_category"),
            "order": row.get("order"),
        }
    if stream_key == "users":
        login = _required_string(row.get("login"), field="GitHub user login")
        return {
            "name": login,
            "display_name": _optional_string(row.get("name")),
            "primary_email": _optional_string(row.get("email")),
            "active": row.get("suspended_at") is None,
            "assignable": True,
            "avatar_url": _safe_github_url(row.get("avatar_url")),
        }
    if repository is None:
        raise _invalid_response("GitHub record repository is missing.")
    if stream_key == "issues":
        issue_number = _required_integer(
            row.get("number"),
            field="GitHub issue number",
        )
        state = _required_string(row.get("state"), field="GitHub issue state")
        state_reason = _optional_string(row.get("state_reason"))
        user = _optional_object(row.get("user"))
        assignee = _optional_object(row.get("assignee"))
        milestone = _optional_object(row.get("milestone"))
        labels = _object_list(row.get("labels") or [], field="GitHub issue labels")
        closed_at = _optional_datetime(row.get("closed_at"))
        normalized = (
            "UNSTARTED"
            if state == "open"
            else "CANCELLED"
            if state_reason == "not_planned"
            else "COMPLETED"
        )
        return {
            "key": _issue_external_id(repository, issue_number),
            "title": _required_string(row.get("title"), field="GitHub issue title"),
            "normalized_description": _optional_string(row.get("body")),
            "source_description": _optional_string(row.get("body")),
            "issue_type": "issue",
            "native_status": state
            if state_reason is None
            else f"{state}/{state_reason}",
            "normalized_status": normalized,
            "priority": None,
            "project_external_id": repository,
            "team_external_id": repository.split("/", 1)[0],
            "assignee_external_id": _optional_string(assignee.get("login")),
            "reporter_external_id": _optional_string(user.get("login")),
            "estimate": None,
            "label_external_ids": [
                _label_external_id(
                    repository,
                    _required_string(label.get("name"), field="GitHub label name"),
                )
                for label in labels
            ],
            "parent_external_id": None,
            "cycle_external_id": (
                None
                if not milestone
                else _milestone_external_id(
                    repository,
                    _required_integer(
                        milestone.get("number"),
                        field="GitHub milestone number",
                    ),
                )
            ),
            "due_date": None,
            "started_at": None,
            "completed_at": closed_at if normalized == "COMPLETED" else None,
            "cancelled_at": closed_at if normalized == "CANCELLED" else None,
        }
    if stream_key == "comments":
        issue_number = _issue_number_from_url(row.get("issue_url"), repository)
        user = _optional_object(row.get("user"))
        body = _required_string(row.get("body"), field="GitHub comment body")
        return {
            "issue_external_id": _issue_external_id(repository, issue_number),
            "author_external_id": _optional_string(user.get("login")),
            "normalized_text": body,
            "source_body": body,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
    if stream_key == "labels":
        return {
            "name": row.get("name"),
            "description": _optional_string(row.get("description")),
            "color": _optional_string(row.get("color")),
            "project_external_id": repository,
            "parent_external_id": None,
            "is_group": False,
        }
    return {
        "name": row.get("title"),
        "number": row.get("number"),
        "project_external_id": repository,
        "description": _optional_string(row.get("description")),
        "starts_at": None,
        "ends_at": row.get("due_on"),
        "completed_at": row.get("closed_at"),
        "active": row.get("state") == "open",
    }


def _record_url(
    stream_key: str,
    row: Mapping[str, object],
    *,
    external_id: str,
) -> str | None:
    if stream_key == "workflow_states":
        return None
    return _safe_github_url(row.get("html_url")) or (
        _issue_url(external_id) if stream_key == "issues" else None
    )


def _github_issue_payload(
    payload: Mapping[str, object],
    *,
    create: bool,
    repository: str,
) -> dict[str, object]:
    allowed = {
        "title",
        "normalized_description",
        "project_external_id",
        "assignee_external_id",
        "label_external_ids",
        "cycle_external_id",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise _invalid_command(
            "GitHub issue payload contains unsupported fields: "
            + ", ".join(sorted(unknown))
            + "."
        )
    if create and not {"title", "project_external_id"}.issubset(payload):
        raise _invalid_command(
            "Creating a GitHub issue requires title and project_external_id."
        )
    if not create and not payload:
        raise _invalid_command("Updating a GitHub issue requires at least one field.")
    if not create and "project_external_id" in payload:
        raise _invalid_command("A GitHub issue cannot move between repositories.")
    result: dict[str, object] = {}
    if "title" in payload:
        result["title"] = _required_command_string(
            payload.get("title"),
            field="GitHub issue title",
        )
    if "normalized_description" in payload:
        result["body"] = _nullable_string(
            payload.get("normalized_description"),
            field="GitHub issue description",
        )
    if "assignee_external_id" in payload:
        assignee = _nullable_command_string(
            payload.get("assignee_external_id"),
            field="GitHub assignee",
        )
        result["assignees"] = [] if assignee is None else [assignee]
    if "label_external_ids" in payload:
        values = payload.get("label_external_ids")
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise _invalid_command("GitHub issue labels must be a list.")
        labels: list[str] = []
        for value in values:
            label_repository, label_name = _label_identity(
                _required_command_string(value, field="GitHub label ID")
            )
            _require_matching_repository(
                repository,
                label_repository,
                entity="label",
            )
            labels.append(label_name)
        result["labels"] = labels
    if "cycle_external_id" in payload:
        milestone = payload.get("cycle_external_id")
        if milestone is None:
            result["milestone"] = None
        else:
            milestone_repository, milestone_number = _milestone_identity(
                _required_command_string(
                    milestone,
                    field="GitHub milestone ID",
                )
            )
            _require_matching_repository(
                repository,
                milestone_repository,
                entity="milestone",
            )
            result["milestone"] = milestone_number
    return result


def _require_matching_repository(
    expected: str,
    actual: str,
    *,
    entity: str,
) -> None:
    if expected.casefold() != actual.casefold():
        raise _invalid_command(
            f"A GitHub {entity} must belong to the issue repository."
        )


def _issue_command_result(
    repository: str,
    row: Mapping[str, object],
    *,
    response: SorJsonResponse,
    fallback_external_id: str | None = None,
) -> SorCommandResult:
    number = _optional_integer(row.get("number"), field="GitHub issue number")
    external_id = (
        _issue_external_id(repository, number)
        if number is not None
        else fallback_external_id
    )
    if external_id is None:
        raise _invalid_response("GitHub mutation result is missing the issue number.")
    updated_at = _optional_datetime(row.get("updated_at"))
    return SorCommandResult(
        vendor_object_key="issues",
        external_id=external_id,
        external_request_id=_request_id(response),
        source_revision=(
            _github_datetime(updated_at) if updated_at is not None else None
        ),
        source_url=_safe_github_url(row.get("html_url")) or _issue_url(external_id),
        response={"status": "accepted"},
    )


def _issue_url(external_id: str) -> str:
    repository, number = _issue_identity(external_id)
    return f"https://github.com/{_repository_path(repository)}/issues/{number}"


def _issue_number_from_url(value: object, repository: str) -> int:
    url = _required_string(value, field="GitHub issue URL")
    parsed = urlparse(url)
    expected_prefix = f"/repos/{repository}/issues/"
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise _invalid_response("GitHub comment issue URL is invalid.")
    if not parsed.path.casefold().startswith(expected_prefix.casefold()):
        raise _invalid_response("GitHub comment belongs to another repository.")
    return _positive_integer(
        parsed.path[len(expected_prefix) :],
        field="issue number",
    )


def _webhook_record_identity(
    event_name: str,
    payload: Mapping[str, object],
    *,
    repository: str,
) -> tuple[str | None, str | None, datetime | None]:
    if event_name == "issues":
        row = _object(payload.get("issue"), field="GitHub webhook issue")
        if "pull_request" in row:
            return None, None, None
        return (
            "issues",
            _issue_external_id(
                repository,
                _required_integer(row.get("number"), field="GitHub issue number"),
            ),
            _optional_datetime(row.get("updated_at")),
        )
    if event_name == "issue_comment":
        issue = _object(payload.get("issue"), field="GitHub webhook issue")
        if "pull_request" in issue:
            return None, None, None
        comment = _object(payload.get("comment"), field="GitHub webhook comment")
        return (
            "comments",
            _comment_external_id(
                repository,
                _required_integer(comment.get("id"), field="GitHub comment ID"),
            ),
            _optional_datetime(comment.get("updated_at")),
        )
    if event_name == "label":
        row = _object(payload.get("label"), field="GitHub webhook label")
        return (
            "labels",
            _label_external_id(
                repository,
                _required_string(row.get("name"), field="GitHub label name"),
            ),
            None,
        )
    if event_name == "milestone":
        row = _object(payload.get("milestone"), field="GitHub webhook milestone")
        return (
            "milestones",
            _milestone_external_id(
                repository,
                _required_integer(
                    row.get("number"),
                    field="GitHub milestone number",
                ),
            ),
            _optional_datetime(row.get("updated_at")),
        )
    if event_name == "repository":
        return "repositories", repository, None
    return None, None, None


def _webhook_body(body: bytes, *, verification: bool) -> Mapping[str, object]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        exception = (
            SorWebhookVerificationError if verification else SorWebhookPayloadError
        )
        raise exception("GitHub webhook payload is invalid.") from error
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        exception = (
            SorWebhookVerificationError if verification else SorWebhookPayloadError
        )
        raise exception("GitHub webhook payload is invalid.")
    return value


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    return next(
        (
            value.strip()
            for key, value in headers.items()
            if key.casefold() == expected and value.strip()
        ),
        None,
    )


def _required_header(headers: Mapping[str, str], name: str, label: str) -> str:
    value = _header(headers, name)
    if value is None or len(value) > 512 or "\r" in value or "\n" in value:
        raise SorWebhookPayloadError(f"GitHub webhook {label} is invalid.")
    return value


def _start_cursor(cursor: _GitHubCursor | None) -> _GitHubCursor:
    now = datetime.now(timezone.utc)
    if cursor is None:
        return _GitHubCursor(floor=None, repo_index=0, page=1, started_at=now)
    if cursor.complete:
        return _GitHubCursor(
            floor=cursor.floor,
            repo_index=0,
            page=1,
            started_at=now,
        )
    return cursor


def _complete_cursor(checkpoint: _GitHubCursor) -> _GitHubCursor:
    return _GitHubCursor(
        floor=checkpoint.started_at,
        repo_index=0,
        page=1,
        started_at=checkpoint.started_at,
        complete=True,
    )


def _vendor_page(
    records: tuple[SorExternalRecord, ...],
    *,
    checkpoint: _GitHubCursor,
    raw_count: int,
    page_size: int,
    repository_count: int,
) -> SorRecordPage:
    if raw_count == page_size:
        next_cursor = _GitHubCursor(
            floor=checkpoint.floor,
            repo_index=checkpoint.repo_index,
            page=checkpoint.page + 1,
            started_at=checkpoint.started_at,
        )
        return SorRecordPage(
            records=records,
            next_cursor=_encode_cursor(next_cursor),
            has_more=True,
        )
    next_repo = checkpoint.repo_index + 1
    if next_repo < repository_count:
        next_cursor = _GitHubCursor(
            floor=checkpoint.floor,
            repo_index=next_repo,
            page=1,
            started_at=checkpoint.started_at,
        )
        return SorRecordPage(
            records=records,
            next_cursor=_encode_cursor(next_cursor),
            has_more=True,
        )
    complete = _complete_cursor(checkpoint)
    return SorRecordPage(
        records=records,
        next_cursor=_encode_cursor(complete),
        has_more=False,
    )


def _sliced_page(
    records: tuple[SorExternalRecord, ...],
    *,
    checkpoint: _GitHubCursor,
    consumed: int,
    total: int,
) -> SorRecordPage:
    next_index = checkpoint.repo_index + consumed
    if next_index < total:
        next_cursor = _GitHubCursor(
            floor=checkpoint.floor,
            repo_index=next_index,
            page=1,
            started_at=checkpoint.started_at,
        )
        return SorRecordPage(
            records=records,
            next_cursor=_encode_cursor(next_cursor),
            has_more=True,
        )
    complete = _complete_cursor(checkpoint)
    return SorRecordPage(
        records=records,
        next_cursor=_encode_cursor(complete),
        has_more=False,
    )


def _encode_cursor(cursor: _GitHubCursor) -> str:
    payload = {
        "v": GITHUB_CURSOR_VERSION,
        "floor": _github_datetime(cursor.floor) if cursor.floor else None,
        "repo": cursor.repo_index,
        "page": cursor.page,
        "started": _github_datetime(cursor.started_at),
        "complete": cursor.complete,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    return encoded.rstrip("=")


def _decode_cursor(value: str | None) -> _GitHubCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        if (
            not isinstance(payload, Mapping)
            or payload.get("v") != GITHUB_CURSOR_VERSION
        ):
            raise ValueError
        floor = _optional_datetime(payload.get("floor"))
        repo_index = _required_integer(payload.get("repo"), field="cursor repository")
        page = _required_integer(payload.get("page"), field="cursor page")
        started_at = _required_datetime(
            payload.get("started"),
            field="cursor start time",
        )
        complete = payload.get("complete")
        if not isinstance(complete, bool) or repo_index < 0 or page < 1:
            raise ValueError
    except (
        binascii.Error,
        SorVendorOperationError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        raise _invalid_cursor() from error
    return _GitHubCursor(
        floor=floor,
        repo_index=repo_index,
        page=page,
        started_at=started_at,
        complete=complete,
    )


def _expect_graphql(
    response: SorJsonResponse,
    *,
    operation: str,
) -> dict[str, object]:
    payload = _object(_expect(response, operation=operation), field="GitHub GraphQL")
    raw_errors = payload.get("errors")
    if raw_errors:
        errors = _object_list(raw_errors, field="GitHub GraphQL errors")
        error_types = {
            value
            for error in errors
            if (value := _optional_string(error.get("type"))) is not None
        }
        if "RATE_LIMITED" in error_types:
            raise SorVendorOperationError(
                "vendor_rate_limited",
                "GitHub rate-limited the source.",
                retryable=True,
            )
        if "FORBIDDEN" in error_types:
            raise SorVendorOperationError(
                "vendor_forbidden",
                f"GitHub refused permission to {operation}.",
                retryable=False,
            )
        if "NOT_FOUND" in error_types:
            raise SorVendorOperationError(
                "vendor_resource_unavailable",
                f"GitHub could not find the resource needed to {operation}.",
                retryable=False,
            )
        raise SorVendorOperationError(
            "vendor_request_failed",
            f"GitHub could not {operation}.",
            retryable=False,
        )
    return _object(payload.get("data"), field="GitHub GraphQL data")


def _expect(response: SorJsonResponse, *, operation: str) -> object:
    if response.ok:
        return response.data
    if response.status_code == 401:
        raise SorVendorOperationError(
            "vendor_authorization_expired",
            f"GitHub refused authorization while attempting to {operation}.",
            retryable=False,
            requires_reauthorization=True,
        )
    if response.status_code in {403, 429}:
        remaining = response.header_values("x-ratelimit-remaining")
        rate_limited = response.status_code == 429 or remaining == ("0",)
        raise SorVendorOperationError(
            "vendor_rate_limited" if rate_limited else "vendor_forbidden",
            (
                "GitHub rate-limited the source."
                if rate_limited
                else f"GitHub refused permission to {operation}."
            ),
            retryable=rate_limited,
        )
    if response.status_code == 404:
        raise SorVendorOperationError(
            "vendor_resource_unavailable",
            f"GitHub could not find the resource needed to {operation}.",
            retryable=False,
        )
    if response.status_code in {409, 412}:
        raise SorVendorOperationError(
            "vendor_revision_conflict",
            f"GitHub rejected stale state while attempting to {operation}.",
            retryable=False,
        )
    if response.status_code == 422:
        raise SorVendorOperationError(
            "vendor_command_invalid",
            f"GitHub rejected the data used to {operation}.",
            retryable=False,
        )
    if response.status_code >= 500:
        raise SorVendorOperationError(
            "vendor_server_failed",
            f"GitHub failed while attempting to {operation}.",
            retryable=True,
        )
    raise SorVendorOperationError(
        "vendor_request_failed",
        f"GitHub refused the request to {operation}.",
        retryable=False,
    )


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_configuration("GitHub access token is missing.")
    return value.strip()


def _require_stream(stream_key: str, *, selected: Sequence[str]) -> str:
    if stream_key not in _STREAM_ENTITY or stream_key not in selected:
        raise SorVendorOperationError(
            "vendor_stream_unsupported",
            "The requested GitHub stream is unavailable for this source.",
            retryable=False,
        )
    return stream_key


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise _invalid_command("This GitHub issue action requires an issue target.")
    return command.target_external_id


def _required_command_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_command(f"{field} must be non-empty text.")
    return value.strip()


def _nullable_command_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_command_string(value, field=field)


def _invalid_configuration(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "source_configuration_invalid",
        message,
        retryable=False,
    )


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_command_invalid",
        message,
        retryable=False,
    )


def _invalid_cursor() -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_cursor_invalid",
        "GitHub cursor is invalid.",
        retryable=False,
    )


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        "vendor_response_invalid",
        message,
        retryable=False,
    )


def _object(value: object, *, field: str = "GitHub response") -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _invalid_response(f"{field} is invalid.")
    return dict(value)


def _optional_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    return _object(value)


def _object_list(value: object, *, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise _invalid_response(f"{field} is invalid.")
    return [_object(item, field=field) for item in value]


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response(f"{field} is missing.")
    return value.strip()


def _nullable_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_command(f"{field} must be text or null.")
    return value


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid_response(f"{field} is invalid.")
    return value


def _optional_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    return _required_integer(value, field=field)


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _invalid_command(f"GitHub {field} is invalid.")
    try:
        result = int(value)
    except ValueError as error:
        raise _invalid_command(f"GitHub {field} is invalid.") from error
    if result <= 0 or str(result) != str(value):
        raise _invalid_command(f"GitHub {field} is invalid.")
    return result


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"{field} is invalid.")
    return value


def _optional_boolean(value: object) -> bool | None:
    if value is None:
        return None
    return _required_boolean(value, field="GitHub boolean")


def _required_datetime(value: object, *, field: str) -> datetime:
    parsed = _optional_datetime(value)
    if parsed is None:
        raise _invalid_response(f"{field} is invalid.")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise _invalid_response("GitHub timestamp is invalid.") from error
    else:
        raise _invalid_response("GitHub timestamp is invalid.")
    if parsed.tzinfo is None:
        raise _invalid_response("GitHub timestamp lacks a timezone.")
    return parsed.astimezone(timezone.utc)


def _github_datetime(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid_response("GitHub string list is invalid.")
    return tuple(
        _required_string(item, field="GitHub string list item") for item in value
    )


def _json_value(value: object) -> object | None:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    raise _invalid_response("GitHub source value is not JSON compatible.")


def _safe_github_url(value: object) -> str | None:
    url = _optional_string(value)
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {
        "github.com",
        "avatars.githubusercontent.com",
    }:
        return None
    return url[:2_048]


def _request_id(response: SorJsonResponse) -> str | None:
    values = response.header_values("x-github-request-id")
    return values[0][:512] if values else None


def _raise_unknown_create(error: SorVendorOperationError, message: str) -> None:
    if error.code in {
        "vendor_timeout",
        "vendor_transport_failed",
        "vendor_server_failed",
    }:
        raise SorVendorOperationError(
            "vendor_mutation_outcome_unknown",
            message,
            retryable=False,
        ) from error


__all__ = [
    "GITHUB_MANIFEST",
    "GitHubTicketingAdapter",
    "create_github_adapter",
]
