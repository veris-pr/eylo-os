"""Linear GraphQL adapter for Eylo's canonical ticketing profile."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal, overload

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from eylo.modules.connections.domain import ConnectionAuthKind
from eylo.sor.runtime.http import SorHttpTransport, SorJsonHttpClient, SorJsonResponse
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
from eylo.sor.shared.linear import linear_graphql_data
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
from eylo.sor.ticketing.vendors.linear_contracts import (
    MAX_PAGE_RECORDS,
    PAGE_MODELS,
    RECORD_MODELS,
    LinearComment,
    LinearCommentInput,
    LinearCommentMutation,
    LinearCommentResult,
    LinearCommentVariables,
    LinearCreateResult,
    LinearCreateVariables,
    LinearCycle,
    LinearDateComparator,
    LinearIssue,
    LinearIssueCreateInput,
    LinearIssueInput,
    LinearIssueLabelsResult,
    LinearIssueMutation,
    LinearLabel,
    LinearLabelAction,
    LinearMutationRecord,
    LinearNativeModel,
    LinearPageVariables,
    LinearPriority,
    LinearProject,
    LinearRecord,
    LinearRecordVariables,
    LinearRelationInput,
    LinearRelationMutation,
    LinearRelationResult,
    LinearRelationType,
    LinearRelationVariables,
    LinearRequestModel,
    LinearStateType,
    LinearTeam,
    LinearTicketingRecord,
    LinearTicketingStream,
    LinearUpdateResult,
    LinearUpdateVariables,
    LinearUpdatedFilter,
    LinearUser,
    LinearVariables,
    LinearWorkflowState,
    LinearWorkspaceResult,
)

LINEAR_ORIGIN = "https://api.linear.app"
LINEAR_GRAPHQL_PATH = "/graphql"
LINEAR_API_VERSION = "graphql-current"
LINEAR_CURSOR_VERSION = 1
LINEAR_RECONCILIATION_OVERLAP = timedelta(minutes=2)

READ_SCOPE = "read"
WRITE_SCOPE = "write"
ISSUES_CREATE_SCOPE = "issues:create"
COMMENTS_CREATE_SCOPE = "comments:create"


_STREAM_ENTITY = {
    LinearTicketingStream.ISSUES: TicketingEntityKind.ISSUE,
    LinearTicketingStream.TEAMS: TicketingEntityKind.PROJECT,
    LinearTicketingStream.PROJECTS: TicketingEntityKind.PROJECT,
    LinearTicketingStream.WORKFLOW_STATES: TicketingEntityKind.WORKFLOW_STATE,
    LinearTicketingStream.USERS: TicketingEntityKind.USER,
    LinearTicketingStream.ISSUE_LABELS: TicketingEntityKind.LABEL,
    LinearTicketingStream.CYCLES: TicketingEntityKind.CYCLE,
    LinearTicketingStream.COMMENTS: TicketingEntityKind.COMMENT,
    LinearTicketingStream.ISSUE_RELATIONS: TicketingEntityKind.RELATION,
}
_RELATIONSHIP_TARGETS = {
    LinearTicketingStream.ISSUES: {
        SorRelationshipRole.PROJECT: LinearTicketingStream.PROJECTS,
        SorRelationshipRole.TEAM: LinearTicketingStream.TEAMS,
        SorRelationshipRole.ASSIGNEE: LinearTicketingStream.USERS,
        SorRelationshipRole.REPORTER: LinearTicketingStream.USERS,
        SorRelationshipRole.LABEL: LinearTicketingStream.ISSUE_LABELS,
        SorRelationshipRole.PARENT: LinearTicketingStream.ISSUES,
        SorRelationshipRole.CYCLE: LinearTicketingStream.CYCLES,
    },
    LinearTicketingStream.ISSUE_LABELS: {
        SorRelationshipRole.PROJECT: LinearTicketingStream.TEAMS,
        SorRelationshipRole.PARENT: LinearTicketingStream.ISSUE_LABELS,
    },
    LinearTicketingStream.CYCLES: {
        SorRelationshipRole.PROJECT: LinearTicketingStream.TEAMS
    },
    LinearTicketingStream.COMMENTS: {
        SorRelationshipRole.ISSUE: LinearTicketingStream.ISSUES,
        SorRelationshipRole.AUTHOR: LinearTicketingStream.USERS,
    },
    LinearTicketingStream.ISSUE_RELATIONS: {
        SorRelationshipRole.FROM_ISSUE: LinearTicketingStream.ISSUES,
        SorRelationshipRole.TO_ISSUE: LinearTicketingStream.ISSUES,
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
        TicketingToolName.COMMENT,
        TicketingToolName.LINK,
        TicketingToolName.ADD_LABEL,
        TicketingToolName.REMOVE_LABEL,
    }
)
_TOOL_STREAMS = {
    TicketingToolName.SEARCH: frozenset({LinearTicketingStream.ISSUES}),
    TicketingToolName.GET: frozenset({LinearTicketingStream.ISSUES}),
    TicketingToolName.LIST_PROJECTS: frozenset(
        {LinearTicketingStream.TEAMS, LinearTicketingStream.PROJECTS}
    ),
    TicketingToolName.LIST_WORKFLOW_STATES: frozenset(
        {LinearTicketingStream.WORKFLOW_STATES}
    ),
    TicketingToolName.DESCRIBE_FIELDS: frozenset({LinearTicketingStream.ISSUES}),
    TicketingToolName.CREATE: frozenset({LinearTicketingStream.ISSUES}),
    TicketingToolName.UPDATE: frozenset({LinearTicketingStream.ISSUES}),
    TicketingToolName.TRANSITION: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.WORKFLOW_STATES}
    ),
    TicketingToolName.ASSIGN: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.USERS}
    ),
    TicketingToolName.COMMENT: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.COMMENTS}
    ),
    TicketingToolName.LINK: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.ISSUE_RELATIONS}
    ),
    TicketingToolName.ADD_LABEL: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.ISSUE_LABELS}
    ),
    TicketingToolName.REMOVE_LABEL: frozenset(
        {LinearTicketingStream.ISSUES, LinearTicketingStream.ISSUE_LABELS}
    ),
}
_MUTATION_RESULT_STREAMS = {
    **{tool_name: LinearTicketingStream.ISSUES for tool_name in _WRITE_TOOLS},
    TicketingToolName.COMMENT: LinearTicketingStream.COMMENTS,
    TicketingToolName.LINK: LinearTicketingStream.ISSUE_RELATIONS,
}
_FULL_RECONCILE_STREAMS = frozenset({LinearTicketingStream.ISSUE_RELATIONS})
_WEBHOOK_STREAMS = {
    "Issue": LinearTicketingStream.ISSUES,
    "Comment": LinearTicketingStream.COMMENTS,
    "Project": LinearTicketingStream.PROJECTS,
    "IssueRelation": LinearTicketingStream.ISSUE_RELATIONS,
    "IssueLabel": LinearTicketingStream.ISSUE_LABELS,
    "Cycle": LinearTicketingStream.CYCLES,
    "User": LinearTicketingStream.USERS,
    "Document": "documents",
}


class LinearAppWebhookDelivery(BaseModel):
    """One verified Linear workspace event before source selection filtering."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_external_id: str
    signal: SorWebhookSignal


LINEAR_MANIFEST = SorAdapterCapabilityManifest(
    profile=SorProfile.TICKETING,
    vendor_key="linear",
    auth_kinds=(ConnectionAuthKind.OAUTH2,),
    streams=tuple(
        SorVendorStreamSpec(
            key=stream_key,
            label={
                LinearTicketingStream.ISSUES: "Issues",
                LinearTicketingStream.TEAMS: "Teams",
                LinearTicketingStream.PROJECTS: "Projects",
                LinearTicketingStream.WORKFLOW_STATES: "Workflow states",
                LinearTicketingStream.USERS: "Users",
                LinearTicketingStream.ISSUE_LABELS: "Labels",
                LinearTicketingStream.CYCLES: "Cycles",
                LinearTicketingStream.COMMENTS: "Comments",
                LinearTicketingStream.ISSUE_RELATIONS: "Issue relations",
            }[stream_key],
            description={
                LinearTicketingStream.ISSUES: "Issues, workflow state, ownership, labels, and planning fields.",
                LinearTicketingStream.TEAMS: "Linear teams exposed as ticketing work containers.",
                LinearTicketingStream.PROJECTS: "Linear projects exposed as ticketing projects.",
                LinearTicketingStream.WORKFLOW_STATES: "Team workflow states and normalized categories.",
                LinearTicketingStream.USERS: "Assignable and inactive Linear workspace users.",
                LinearTicketingStream.ISSUE_LABELS: "Workspace and team-scoped issue labels.",
                LinearTicketingStream.CYCLES: "Team cycles used to time-box issues.",
                LinearTicketingStream.COMMENTS: "Chronological issue comments.",
                LinearTicketingStream.ISSUE_RELATIONS: "Typed relationships between issues.",
            }[stream_key],
            canonical_entity=entity,
            change_strategies=(
                frozenset({SorChangeStrategy.FULL_RECONCILE})
                if stream_key in _FULL_RECONCILE_STREAMS
                else frozenset({SorChangeStrategy.UPDATED_AT})
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
    required_scopes={stream_key: (READ_SCOPE,) for stream_key in _STREAM_ENTITY},
    tool_required_scopes={
        TicketingToolName.CREATE: (ISSUES_CREATE_SCOPE,),
        TicketingToolName.COMMENT: (COMMENTS_CREATE_SCOPE,),
        **{
            tool_name: (WRITE_SCOPE,)
            for tool_name in _WRITE_TOOLS
            - {TicketingToolName.CREATE, TicketingToolName.COMMENT}
        },
    },
    tool_streams={
        tool.value: frozenset(stream.value for stream in streams)
        for tool, streams in _TOOL_STREAMS.items()
    },
    mutation_result_streams={
        tool.value: stream.value for tool, stream in _MUTATION_RESULT_STREAMS.items()
    },
    oauth=SorOAuthSpec(
        authorization_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        base_scopes=(READ_SCOPE,),
        scope_delimiter=",",
        scope_response_delimiter=" ",
        authorization_params=(("actor", "app"), ("prompt", "consent")),
        pkce=True,
    ),
    fixed_origin=LINEAR_ORIGIN,
    change_mode=SorChangeMode.APP_WEBHOOK,
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
) -> SorDiscoveredField:
    return SorDiscoveredField(
        key=key,
        label=label,
        data_type=data_type,
        nullable=nullable,
        writable=writable,
        description=description,
        group="Linear",
    )


_SCHEMA_FIELDS = {
    LinearTicketingStream.ISSUES: (
        _field("identifier", "Identifier", SorFieldDataType.TEXT, nullable=False),
        _field("title", "Title", SorFieldDataType.TEXT, nullable=False, writable=True),
        _field("description", "Description", SorFieldDataType.TEXT, writable=True),
        _field(
            "description_source",
            "Source description",
            SorFieldDataType.BOUNDED_JSON,
            description="The original Linear Markdown string retained for audit.",
        ),
        _field("state_name", "Status", SorFieldDataType.TEXT),
        _field("normalized_status", "Normalized status", SorFieldDataType.ENUM),
        _field("priority_label", "Priority", SorFieldDataType.TEXT, writable=True),
        _field("project_id", "Project ID", SorFieldDataType.REFERENCE, writable=True),
        _field(
            "team_id",
            "Team ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
            writable=True,
        ),
        _field("assignee_id", "Assignee ID", SorFieldDataType.REFERENCE, writable=True),
        _field("creator_id", "Creator ID", SorFieldDataType.REFERENCE),
        _field("estimate", "Estimate", SorFieldDataType.DECIMAL, writable=True),
        _field("label_ids", "Label IDs", SorFieldDataType.STRING_ARRAY, writable=True),
        _field(
            "parent_id", "Parent issue ID", SorFieldDataType.REFERENCE, writable=True
        ),
        _field("cycle_id", "Cycle ID", SorFieldDataType.REFERENCE, writable=True),
        _field("due_date", "Due date", SorFieldDataType.DATE, writable=True),
        _field("started_at", "Started at", SorFieldDataType.TIMESTAMP),
        _field("completed_at", "Completed at", SorFieldDataType.TIMESTAMP),
        _field("cancelled_at", "Cancelled at", SorFieldDataType.TIMESTAMP),
    ),
    LinearTicketingStream.TEAMS: (
        _field("key", "Key", SorFieldDataType.TEXT, nullable=False),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
    ),
    LinearTicketingStream.PROJECTS: (
        _field("key", "Slug", SorFieldDataType.TEXT),
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
    ),
    LinearTicketingStream.WORKFLOW_STATES: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("native_category", "Source category", SorFieldDataType.TEXT),
        _field("normalized_category", "Normalized category", SorFieldDataType.ENUM),
        _field("position", "Position", SorFieldDataType.DECIMAL),
    ),
    LinearTicketingStream.USERS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("display_name", "Display name", SorFieldDataType.TEXT),
        _field("primary_email", "Email", SorFieldDataType.TEXT),
        _field("active", "Active", SorFieldDataType.BOOLEAN, nullable=False),
        _field("assignable", "Assignable", SorFieldDataType.BOOLEAN),
        _field("avatar_url", "Avatar URL", SorFieldDataType.LINK),
    ),
    LinearTicketingStream.ISSUE_LABELS: (
        _field("name", "Name", SorFieldDataType.TEXT, nullable=False),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("color", "Color", SorFieldDataType.TEXT),
        _field("project_external_id", "Team ID", SorFieldDataType.REFERENCE),
        _field("parent_external_id", "Parent label ID", SorFieldDataType.REFERENCE),
        _field("is_group", "Group", SorFieldDataType.BOOLEAN, nullable=False),
    ),
    LinearTicketingStream.CYCLES: (
        _field("name", "Name", SorFieldDataType.TEXT),
        _field("number", "Number", SorFieldDataType.INTEGER, nullable=False),
        _field(
            "project_external_id", "Team ID", SorFieldDataType.REFERENCE, nullable=False
        ),
        _field("description", "Description", SorFieldDataType.TEXT),
        _field("starts_at", "Starts at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("ends_at", "Ends at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("completed_at", "Completed at", SorFieldDataType.TIMESTAMP),
        _field("active", "Active", SorFieldDataType.BOOLEAN, nullable=False),
    ),
    LinearTicketingStream.COMMENTS: (
        _field("issue_id", "Issue ID", SorFieldDataType.REFERENCE, nullable=False),
        _field("author_id", "Author ID", SorFieldDataType.REFERENCE),
        _field("body", "Comment", SorFieldDataType.TEXT, nullable=False),
        _field(
            "body_source",
            "Source body",
            SorFieldDataType.BOUNDED_JSON,
            description="The original Linear Markdown string retained for audit.",
        ),
        _field("created_at", "Created at", SorFieldDataType.TIMESTAMP, nullable=False),
        _field("updated_at", "Updated at", SorFieldDataType.TIMESTAMP),
    ),
    LinearTicketingStream.ISSUE_RELATIONS: (
        _field("issue_id", "From issue ID", SorFieldDataType.REFERENCE, nullable=False),
        _field(
            "related_issue_id",
            "To issue ID",
            SorFieldDataType.REFERENCE,
            nullable=False,
        ),
        _field("native_type", "Source relation", SorFieldDataType.TEXT, nullable=False),
        _field(
            "canonical_type",
            "Normalized relation",
            SorFieldDataType.ENUM,
            nullable=False,
        ),
    ),
}


_ISSUE_FIELDS = """
  id identifier title description priority priorityLabel estimate url
  createdAt updatedAt dueDate startedAt completedAt canceledAt archivedAt
  state { id name type }
  assignee { id }
  creator { id }
  team { id key name }
  project { id name slugId }
  labels { nodes { id name } }
  parent { id }
  cycle { id }
"""
_PAGE_QUERIES = {
    LinearTicketingStream.ISSUES: f"""
      query EyloIssues($first: Int!, $after: String, $filter: IssueFilter) {{
        issues(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {{
          nodes {{{_ISSUE_FIELDS}}}
          pageInfo {{ hasNextPage endCursor }}
        }}
      }}
    """,
    LinearTicketingStream.TEAMS: """
      query EyloTeams($first: Int!, $after: String, $filter: TeamFilter) {
        teams(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {
          nodes { id key name description createdAt updatedAt }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.PROJECTS: """
      query EyloProjects($first: Int!, $after: String, $filter: ProjectFilter) {
        projects(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {
          nodes { id slugId name description url createdAt updatedAt archivedAt }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.WORKFLOW_STATES: """
      query EyloWorkflowStates(
        $first: Int!, $after: String, $filter: WorkflowStateFilter
      ) {
        workflowStates(
          first: $first, after: $after, filter: $filter, orderBy: updatedAt
        ) {
          nodes { id name type position createdAt updatedAt team { id } }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.USERS: """
      query EyloUsers($first: Int!, $after: String, $filter: UserFilter) {
        users(
          first: $first, after: $after, filter: $filter,
          includeDisabled: true, orderBy: updatedAt
        ) {
          nodes {
            id name displayName email active isAssignable avatarUrl url
            createdAt updatedAt archivedAt
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.ISSUE_LABELS: """
      query EyloIssueLabels(
        $first: Int!, $after: String, $filter: IssueLabelFilter
      ) {
        issueLabels(
          first: $first, after: $after, filter: $filter, orderBy: updatedAt
        ) {
          nodes {
            id name description color isGroup createdAt updatedAt archivedAt
            team { id }
            parent { id }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.CYCLES: """
      query EyloCycles($first: Int!, $after: String, $filter: CycleFilter) {
        cycles(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {
          nodes {
            id name number description startsAt endsAt completedAt isActive
            createdAt updatedAt archivedAt
            team { id }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.COMMENTS: """
      query EyloComments($first: Int!, $after: String, $filter: CommentFilter) {
        comments(first: $first, after: $after, filter: $filter, orderBy: updatedAt) {
          nodes { id body createdAt updatedAt archivedAt issue { id } user { id } }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
    LinearTicketingStream.ISSUE_RELATIONS: """
      query EyloIssueRelations($first: Int!, $after: String) {
        issueRelations(first: $first, after: $after, orderBy: updatedAt) {
          nodes {
            id type createdAt updatedAt archivedAt
            issue { id }
            relatedIssue { id }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """,
}


class _LinearCursor(BaseModel):
    """Validated read continuation, separate from the persisted cursor encoding."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    floor: AwareDatetime | None
    after: str | None
    high: AwareDatetime | None
    started_at: AwareDatetime


class LinearTicketingAdapter:
    """Translate Linear GraphQL records into Eylo's ticketing contract."""

    def __init__(
        self,
        context: SorAdapterContext,
        *,
        transport: SorHttpTransport | None = None,
    ) -> None:
        if context.vendor_key != "linear":
            raise ValueError("Linear adapter requires the linear vendor key.")
        if context.auth_kind is not ConnectionAuthKind.OAUTH2:
            raise ValueError("Linear SOR currently requires OAuth 2.0.")
        token = _credential(context.credentials, "access_token")
        self._context = context
        self._client = SorJsonHttpClient(
            origin=LINEAR_ORIGIN,
            authorization=f"Bearer {token}",
            transport=transport,
            response_body_limit=8_388_608,
        )

    async def verify_connection(self) -> SorConnectionVerification:
        data, _response = await self._graphql(
            """
              query EyloVerifyLinear {
                organization { id name }
                viewer { id name email }
              }
            """,
            operation="verify Linear workspace",
        )
        organization = _parse_native(data, LinearWorkspaceResult).organization
        account_id = organization.id
        display_name = _optional_string(organization.name) or "Linear workspace"
        return SorConnectionVerification(
            account_external_id=account_id,
            account_display_name=display_name,
            granted_scopes=tuple(sorted(self._context.granted_scopes)),
            vendor_api_version=LINEAR_API_VERSION,
        )

    async def discover_schema(self) -> SorDiscoveredSchema:
        selected_streams = tuple(
            _require_stream(key, selected=self._context.selected_objects)
            for key in self._context.selected_objects
        )
        streams = {stream.key: stream for stream in LINEAR_MANIFEST.streams}
        objects = tuple(
            SorDiscoveredObject(
                key=stream_key,
                label=streams[stream_key].label,
                fields=_SCHEMA_FIELDS[stream_key],
            )
            for stream_key in selected_streams
        )
        if not objects:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_SELECTION_EMPTY,
                "The Linear source selects no streams.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return SorDiscoveredSchema(
            objects=objects,
            vendor_api_version=LINEAR_API_VERSION,
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
        record_id = _required_id(external_id, field="Linear record ID")
        singular = {
            LinearTicketingStream.ISSUES: "issue",
            LinearTicketingStream.TEAMS: "team",
            LinearTicketingStream.PROJECTS: "project",
            LinearTicketingStream.WORKFLOW_STATES: "workflowState",
            LinearTicketingStream.USERS: "user",
            LinearTicketingStream.ISSUE_LABELS: "issueLabel",
            LinearTicketingStream.CYCLES: "cycle",
            LinearTicketingStream.COMMENTS: "comment",
            LinearTicketingStream.ISSUE_RELATIONS: "issueRelation",
        }[stream_key]
        selection = {
            LinearTicketingStream.ISSUES: _ISSUE_FIELDS,
            LinearTicketingStream.TEAMS: "id key name description createdAt updatedAt",
            LinearTicketingStream.PROJECTS: "id slugId name description url createdAt updatedAt archivedAt",
            LinearTicketingStream.WORKFLOW_STATES: (
                "id name type position createdAt updatedAt team { id }"
            ),
            LinearTicketingStream.USERS: (
                "id name displayName email active isAssignable avatarUrl url "
                "createdAt updatedAt archivedAt"
            ),
            LinearTicketingStream.ISSUE_LABELS: (
                "id name description color isGroup createdAt updatedAt archivedAt "
                "team { id } parent { id }"
            ),
            LinearTicketingStream.CYCLES: (
                "id name number description startsAt endsAt completedAt isActive "
                "createdAt updatedAt archivedAt team { id }"
            ),
            LinearTicketingStream.COMMENTS: (
                "id body createdAt updatedAt archivedAt issue { id } user { id }"
            ),
            LinearTicketingStream.ISSUE_RELATIONS: (
                "id type createdAt updatedAt archivedAt "
                "issue { id } relatedIssue { id }"
            ),
        }[stream_key]
        data, _response = await self._graphql(
            f"""
              query EyloLinearRecord($id: String!) {{
                {singular}(id: $id) {{ {selection} }}
              }}
            """,
            LinearRecordVariables(id=record_id),
            operation="read Linear record",
        )
        if singular not in data:
            raise _invalid_response("Linear returned no selected record field.")
        row = data[singular]
        if row is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
            )
        record = _parse_native(row, RECORD_MODELS[stream_key])
        archived_at = record.archived_datetime
        if archived_at is not None:
            raise SorExternalRecordNotFound(
                vendor_object_key=stream_key,
                external_id=record_id,
                deleted_at=archived_at,
                reason="Archived in Linear",
            )
        return self._external_record(record)

    async def fetch_deleted(
        self,
        *,
        stream_key: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[SorDeletedRecord, ...]:
        raise SorCapabilityUnavailable(
            "Linear deletion polling is not available in this adapter revision."
        )

    async def subscribe_webhook(self, callback_url: str) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Linear webhooks require operator-owned app webhook configuration."
        )

    async def renew_webhook(
        self,
        subscription: SorWebhookSubscription,
    ) -> SorWebhookSubscription:
        raise SorCapabilityUnavailable(
            "Linear webhooks require operator-owned app webhook configuration."
        )

    async def remove_webhook(self, subscription: SorWebhookSubscription) -> None:
        raise SorCapabilityUnavailable(
            "Linear webhooks require operator-owned app webhook configuration."
        )

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        if self._context.webhook_signing_secret is None:
            raise SorWebhookVerificationError(
                "Linear webhook signing secret is not configured."
            )
        verify_linear_app_webhook(
            headers=headers,
            body=body,
            signing_secret=self._context.webhook_signing_secret,
        )

    async def parse_webhook_signal(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> tuple[SorWebhookSignal, ...]:
        delivery = parse_linear_app_webhook(headers=headers, body=body)
        signal = delivery.signal
        stream_key = signal.vendor_object_key
        external_id = signal.external_id
        if stream_key not in self._context.selected_objects:
            signal = SorWebhookSignal(
                delivery_id=signal.delivery_id,
                event_type=signal.event_type,
                vendor_object_key=None,
                external_id=None,
                occurred_at=signal.occurred_at,
            )
        elif external_id is None:
            raise SorWebhookPayloadError("Linear webhook record identity is missing.")
        return (signal,)

    async def execute_command(self, command: SorCommandRequest) -> SorCommandResult:
        if command.tool_name not in _WRITE_TOOLS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_TOOL_UNSUPPORTED,
                "This Linear adapter does not execute the requested issue action.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if command.tool_name == TicketingToolName.CREATE:
            return await self._create_issue(command)
        target_id = _required_target(command)
        if command.tool_name == TicketingToolName.UPDATE:
            payload = _linear_issue_input(
                _mapped_issue_fields(command),
                operation=SorMutationOperation.UPDATE,
            )
            return await self._update_issue(
                target_id=target_id,
                payload=payload,
                command=command,
            )
        if command.tool_name == TicketingToolName.TRANSITION:
            if not isinstance(command.payload, TicketingTransitionCommandPayload):
                raise _invalid_command("Linear transition payload is invalid.")
            state_id = _required_id(
                command.payload.workflow_state_external_id,
                field="Linear workflow state ID",
            )
            return await self._update_issue(
                target_id=target_id,
                payload=LinearIssueInput(stateId=state_id),
                command=command,
            )
        if command.tool_name == TicketingToolName.ASSIGN:
            if not isinstance(command.payload, TicketingAssignCommandPayload):
                raise _invalid_command("Linear assignment payload is invalid.")
            assignee = _nullable_id(
                command.payload.assignee_external_id,
                field="Linear assignee ID",
            )
            return await self._update_issue(
                target_id=target_id,
                payload=LinearIssueInput(assigneeId=assignee),
                command=command,
            )
        if command.tool_name == TicketingToolName.COMMENT:
            return await self._comment_issue(target_id=target_id, command=command)
        if command.tool_name == TicketingToolName.LINK:
            return await self._link_issue(target_id=target_id, command=command)
        if not isinstance(command.payload, TicketingLabelCommandPayload):
            raise _invalid_command("Linear label payload is invalid.")
        label_id = _required_id(
            command.payload.label_external_id, field="Linear label ID"
        )
        return await self._change_label(
            target_id=target_id,
            label_id=label_id,
            action=(
                LinearLabelAction.ADD
                if command.tool_name == TicketingToolName.ADD_LABEL
                else LinearLabelAction.REMOVE
            ),
            command=command,
        )

    def normalize_issue(
        self,
        record: SorExternalRecord,
        payload: TicketingIssuePayload,
    ) -> TicketingIssue:
        return TicketingIssue(
            external_id=record.external_id,
            key=_optional_string(payload.key),
            title=_required_string(payload.title, field="Linear issue title"),
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
        )

    def normalize_project(
        self,
        record: SorExternalRecord,
        payload: TicketingProjectPayload,
    ) -> TicketingProject:
        return TicketingProject(
            external_id=record.external_id,
            key=_optional_string(payload.key),
            name=_required_string(payload.name, field="Linear project name"),
            description=_optional_string(payload.description),
            source_url=record.source_url,
        )

    def normalize_workflow_state(
        self,
        record: SorExternalRecord,
        payload: TicketingWorkflowStatePayload,
    ) -> TicketingWorkflowState:
        order = payload.order
        if isinstance(order, Decimal) and order != order.to_integral_value():
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "Linear returned a fractional workflow position.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return TicketingWorkflowState(
            external_id=record.external_id,
            name=_required_string(
                payload.name,
                field="Linear workflow state name",
            ),
            native_category=_optional_string(payload.native_category),
            normalized_category=payload.normalized_category,
            order=int(order) if order is not None else None,
        )

    def normalize_user(
        self,
        record: SorExternalRecord,
        payload: TicketingUserPayload,
    ) -> TicketingUser:
        return TicketingUser(
            external_id=record.external_id,
            name=_required_string(payload.name, field="Linear user name"),
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
            name=_required_string(payload.name, field="Linear label name"),
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
        number = payload.number
        name = _optional_string(payload.name)
        if name is None:
            if number is None:
                raise _invalid_response("Linear cycle name and number are missing.")
            name = f"Cycle {number}"
        return TicketingCycle(
            external_id=record.external_id,
            name=name,
            number=number,
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
                field="Linear comment issue ID",
            ),
            author_external_id=_optional_string(payload.author_external_id),
            normalized_text=_required_string(
                payload.normalized_text,
                field="Linear comment body",
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
            issue_vendor_object_key=LinearTicketingStream.ISSUES,
            from_issue_external_id=payload.from_issue_external_id,
            to_issue_external_id=payload.to_issue_external_id,
            canonical_kind=payload.canonical_relation_kind,
            native_kind=payload.native_relation_kind,
            source_revision=record.source_revision,
        )

    async def close(self) -> None:
        """Linear's bounded HTTP transport owns no persistent session."""

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
        if isinstance(limit, bool) or not 1 <= limit <= MAX_PAGE_RECORDS:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_PAGE_INVALID,
                "Linear page limit must be between 1 and 200.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        selected_fields = self._selected_fields(stream_key)
        checkpoint = _decode_cursor(cursor)
        variables = _page_variables(stream_key, limit=limit, checkpoint=checkpoint)
        data, _response = await self._graphql(
            _PAGE_QUERIES[stream_key],
            variables,
            operation=f"list Linear {stream_key}",
        )
        connection = _parse_native(
            data.get(_connection_name(stream_key)), PAGE_MODELS[stream_key]
        )
        rows = connection.nodes
        if len(rows) > limit:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
                "Linear returned more records than requested.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        has_more = connection.page_info.has_next_page
        end_cursor = _optional_string(connection.page_info.end_cursor)
        high = _maximum_updated_at(rows, current=checkpoint.high)
        if has_more:
            next_cursor = _encode_cursor(
                _LinearCursor(
                    floor=checkpoint.floor,
                    after=end_cursor,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
        else:
            next_cursor = _encode_cursor(
                _completed_cursor(
                    floor=checkpoint.floor,
                    high=high,
                    started_at=checkpoint.started_at,
                )
            )
        return SorRecordPage(
            records=tuple(
                self._external_record(
                    row,
                    selected_fields=selected_fields,
                )
                for row in rows
                if row.archived_at is None
            ),
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def _selected_fields(self, stream_key: LinearTicketingStream) -> tuple[str, ...]:
        fields = tuple(
            sorted(
                {
                    field.vendor_field_key
                    for field in self._context.fields
                    if field.vendor_object_key == stream_key
                }
            )
        )
        allowed = {field.key for field in _SCHEMA_FIELDS[stream_key]}
        unknown = set(fields) - allowed
        if unknown:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_MAPPING_INVALID,
                f"The Linear mapping selects unknown {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        if not fields:
            raise SorVendorOperationError(
                SorVendorErrorCode.SOURCE_MAPPING_EMPTY,
                f"The active mapping selects no {stream_key} fields.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        return fields

    def _external_record(
        self,
        row: LinearTicketingRecord,
        *,
        selected_fields: tuple[str, ...] | None = None,
    ) -> SorExternalRecord:
        stream_key = row.stream
        selected = selected_fields or self._selected_fields(stream_key)
        values = _linear_payload(row)
        payload = {field: values.get(field) for field in selected}
        updated_at = row.updated_datetime
        return SorExternalRecord(
            vendor_object_key=stream_key,
            external_id=row.id,
            payload=payload,
            source_created_at=row.created_datetime,
            source_updated_at=updated_at,
            source_revision=updated_at.isoformat(),
            source_url=_safe_linear_url(row.url),
        )

    async def _graphql(
        self,
        document: str,
        variables: LinearVariables | None = None,
        *,
        operation: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, object], SorJsonResponse]:
        response = await self._client.request(
            LINEAR_GRAPHQL_PATH,
            method="POST",
            payload={
                "query": document,
                "variables": variables.model_dump(
                    mode="json", by_alias=True, exclude_unset=True
                )
                if variables is not None
                else {},
            },
            idempotency_key=idempotency_key,
        )
        data = linear_graphql_data(response, operation=operation)
        return data, response

    async def _create_issue(self, command: SorCommandRequest) -> SorCommandResult:
        if command.target_external_id is not None:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "Creating a Linear issue cannot target an existing issue.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        payload = _linear_issue_input(
            _mapped_issue_fields(command),
            operation=SorMutationOperation.CREATE,
        )
        try:
            data, response = await self._graphql(
                f"""
                  mutation EyloCreateLinearIssue($input: IssueCreateInput!) {{
                    issueCreate(input: $input) {{
                      success
                      issue {{{_ISSUE_FIELDS}}}
                    }}
                  }}
                """,
                LinearCreateVariables(input=payload),
                operation="create Linear issue",
                idempotency_key=command.idempotency_key,
            )
        except SorVendorOperationError as error:
            if error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "Linear may have created the issue; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise
        result = _mutation_record(
            _parse_native(data, LinearCreateResult).issue_create,
            operation="create issue",
        )
        return _command_result(result, response=response)

    async def _update_issue(
        self,
        *,
        target_id: str,
        payload: LinearIssueInput,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        data, response = await self._graphql(
            f"""
              mutation EyloUpdateLinearIssue(
                $id: String!, $input: IssueUpdateInput!
              ) {{
                issueUpdate(id: $id, input: $input) {{
                  success
                  issue {{{_ISSUE_FIELDS}}}
                }}
              }}
            """,
            LinearUpdateVariables(id=target_id, input=payload),
            operation="update Linear issue",
            idempotency_key=command.idempotency_key,
        )
        result = _mutation_record(
            _parse_native(data, LinearUpdateResult).issue_update,
            operation="update issue",
        )
        return _command_result(result, response=response)

    async def _comment_issue(
        self,
        *,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingCommentCommandPayload):
            raise _invalid_command("Linear comment payload is invalid.")
        body = command.payload.text
        try:
            data, response = await self._graphql(
                """
                  mutation EyloCommentLinearIssue($input: CommentCreateInput!) {
                    commentCreate(input: $input) {
                      success
                      comment { id body createdAt updatedAt issue { id } user { id } }
                    }
                  }
                """,
                LinearCommentVariables(
                    input=LinearCommentInput(issueId=target_id, body=body)
                ),
                operation="comment on Linear issue",
                idempotency_key=command.idempotency_key,
            )
        except SorVendorOperationError as error:
            if error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "Linear may have created the comment; reconcile before retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise
        result = _mutation_record(
            _parse_native(data, LinearCommentResult).comment_create,
            operation="create comment",
        )
        comment_id = result.id
        updated = result.updated_datetime
        return SorCommandResult(
            vendor_object_key=LinearTicketingStream.COMMENTS,
            external_id=comment_id,
            external_request_id=_request_id(response),
            source_revision=updated.isoformat(),
            response={"status": "accepted"},
        )

    async def _link_issue(
        self,
        *,
        target_id: str,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        if not isinstance(command.payload, TicketingLinkCommandPayload):
            raise _invalid_command("Linear relationship payload is invalid.")
        related_id = _required_id(
            command.payload.related_issue_external_id,
            field="Linear related issue ID",
        )
        if related_id == target_id:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "A Linear issue cannot link to itself.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        relation_kind = command.payload.relation_kind
        native_type = {
            TicketingRelationKind.BLOCKS: LinearRelationType.BLOCKS,
            TicketingRelationKind.BLOCKED_BY: LinearRelationType.BLOCKS,
            TicketingRelationKind.RELATED: LinearRelationType.RELATED,
            TicketingRelationKind.DUPLICATE: LinearRelationType.DUPLICATE,
        }.get(relation_kind)
        if native_type is None:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_COMMAND_INVALID,
                "Linear issue_link supports BLOCKS, BLOCKED_BY, RELATED, or "
                "DUPLICATE. Use issue_update for parent relationships.",
                recovery=SorRecoveryPolicy.TERMINAL,
            )
        issue_id, related_issue_id = (
            (related_id, target_id)
            if relation_kind is TicketingRelationKind.BLOCKED_BY
            else (target_id, related_id)
        )
        try:
            data, response = await self._graphql(
                """
                  mutation EyloLinkLinearIssue($input: IssueRelationCreateInput!) {
                    issueRelationCreate(input: $input) {
                      success
                      issueRelation {
                        id type createdAt updatedAt archivedAt
                        issue { id }
                        relatedIssue { id }
                      }
                    }
                  }
                """,
                LinearRelationVariables(
                    input=LinearRelationInput(
                        issueId=issue_id,
                        relatedIssueId=related_issue_id,
                        type=native_type,
                    )
                ),
                operation="link Linear issue",
                idempotency_key=command.idempotency_key,
            )
        except SorVendorOperationError as error:
            if error.code in {
                SorVendorErrorCode.VENDOR_TIMEOUT,
                SorVendorErrorCode.VENDOR_TRANSPORT_FAILED,
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
            }:
                raise SorVendorOperationError(
                    SorVendorErrorCode.VENDOR_MUTATION_OUTCOME_UNKNOWN,
                    "Linear may have created the issue relation; reconcile before "
                    "retrying.",
                    recovery=SorRecoveryPolicy.RECONCILE_REQUIRED,
                ) from error
            raise
        result = _mutation_record(
            _parse_native(data, LinearRelationResult).issue_relation_create,
            operation="create issue relation",
        )
        relation_id = result.id
        updated = result.updated_datetime
        return SorCommandResult(
            vendor_object_key=LinearTicketingStream.ISSUE_RELATIONS,
            external_id=relation_id,
            external_request_id=_request_id(response),
            source_revision=updated.isoformat(),
            response={"status": "accepted"},
        )

    async def _change_label(
        self,
        *,
        target_id: str,
        label_id: str,
        action: LinearLabelAction,
        command: SorCommandRequest,
    ) -> SorCommandResult:
        data, _response = await self._graphql(
            """
              query EyloLinearIssueLabels($id: String!) {
                issue(id: $id) { id labels { nodes { id } } }
              }
            """,
            LinearRecordVariables(id=target_id),
            operation="read Linear issue labels",
        )
        issue = _parse_native(data, LinearIssueLabelsResult).issue
        if issue is None:
            raise SorExternalRecordNotFound(
                vendor_object_key=LinearTicketingStream.ISSUES,
                external_id=target_id,
            )
        current = {label.id for label in issue.labels.nodes}
        if action is LinearLabelAction.ADD:
            current.add(label_id)
        else:
            current.discard(label_id)
        return await self._update_issue(
            target_id=target_id,
            payload=LinearIssueInput(labelIds=sorted(current)),
            command=command,
        )


def create_linear_adapter(context: SorAdapterContext) -> LinearTicketingAdapter:
    """Construct the explicit Linear ticketing adapter."""
    return LinearTicketingAdapter(context)


def _linear_payload(row: LinearTicketingRecord) -> dict[str, object | None]:
    if isinstance(row, LinearIssue):
        return {
            "identifier": row.identifier,
            "title": row.title,
            "description": row.description,
            "description_source": row.description,
            "state_name": row.state.name,
            "normalized_status": _normalized_linear_state(row.state.type),
            "priority_label": row.priority_label,
            "project_id": row.project.id if row.project is not None else None,
            "team_id": row.team.id,
            "assignee_id": row.assignee.id if row.assignee is not None else None,
            "creator_id": row.creator.id if row.creator is not None else None,
            "estimate": row.estimate,
            "label_ids": [label.id for label in row.labels.nodes],
            "parent_id": row.parent.id if row.parent is not None else None,
            "cycle_id": row.cycle.id if row.cycle is not None else None,
            "due_date": row.due_date,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "cancelled_at": row.canceled_at,
        }
    if isinstance(row, (LinearTeam, LinearProject)):
        return {
            "key": row.key if isinstance(row, LinearTeam) else row.slug_id,
            "name": row.name,
            "description": row.description,
        }
    if isinstance(row, LinearWorkflowState):
        native = _optional_string(row.type)
        return {
            "name": row.name,
            "native_category": native,
            "normalized_category": _normalized_linear_state(native),
            "position": row.position,
        }
    if isinstance(row, LinearUser):
        return {
            "name": row.name,
            "display_name": row.display_name,
            "primary_email": row.email,
            "active": row.active,
            "assignable": row.is_assignable,
            "avatar_url": row.avatar_url,
        }
    if isinstance(row, LinearLabel):
        return {
            "name": row.name,
            "description": row.description,
            "color": row.color,
            "project_external_id": row.team.id if row.team is not None else None,
            "parent_external_id": row.parent.id if row.parent is not None else None,
            "is_group": row.is_group,
        }
    if isinstance(row, LinearCycle):
        return {
            "name": row.name,
            "number": row.number,
            "project_external_id": row.team.id,
            "description": row.description,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "completed_at": row.completed_at,
            "active": row.is_active,
        }
    if isinstance(row, LinearComment):
        return {
            "issue_id": row.issue.id if row.issue is not None else None,
            "author_id": row.user.id if row.user is not None else None,
            "body": row.body,
            "body_source": row.body,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    native_type = _required_string(row.type, field="Linear relation type")
    return {
        "issue_id": row.issue.id,
        "related_issue_id": row.related_issue.id,
        "native_type": native_type,
        "canonical_type": _normalized_linear_relation(native_type).value,
    }


def _mapped_issue_fields(command: SorCommandRequest) -> Mapping[str, object]:
    if not isinstance(command.payload, TicketingMappedFieldsCommandPayload):
        raise _invalid_command("Linear issue field payload is invalid.")
    return command.payload.fields


@overload
def _linear_issue_input(
    payload: Mapping[str, object],
    *,
    operation: Literal[SorMutationOperation.CREATE],
) -> LinearIssueCreateInput: ...


@overload
def _linear_issue_input(
    payload: Mapping[str, object],
    *,
    operation: Literal[SorMutationOperation.UPDATE],
) -> LinearIssueInput: ...


def _linear_issue_input(
    payload: Mapping[str, object],
    *,
    operation: SorMutationOperation,
) -> LinearIssueInput:
    allowed = {
        "title",
        "normalized_description",
        "priority",
        "project_external_id",
        "team_external_id",
        "assignee_external_id",
        "estimate",
        "label_external_ids",
        "parent_external_id",
        "cycle_external_id",
        "due_date",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "Linear issue payload contains unsupported fields: "
            + ", ".join(sorted(unknown))
            + ".",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if operation is SorMutationOperation.CREATE and "title" not in payload:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "Creating a Linear issue requires a title.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if operation is SorMutationOperation.CREATE and "team_external_id" not in payload:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "Creating a Linear issue requires team_external_id.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if not payload:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "Updating a Linear issue requires at least one field.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    result: dict[str, object] = {}
    mappings = {
        "title": "title",
        "normalized_description": "description",
        "project_external_id": "projectId",
        "team_external_id": "teamId",
        "assignee_external_id": "assigneeId",
        "parent_external_id": "parentId",
        "cycle_external_id": "cycleId",
        "due_date": "dueDate",
    }
    for source, target in mappings.items():
        if source not in payload:
            continue
        value = payload[source]
        if source == "title":
            value = _required_string(value, field="Linear issue title")
        elif source in {"normalized_description", "due_date"}:
            value = _nullable_string(value, field=f"Linear {source}")
        else:
            value = _nullable_id(value, field=f"Linear {source}")
        result[target] = value
    if "priority" in payload:
        result["priority"] = _linear_priority(payload["priority"])
    if "estimate" in payload:
        estimate = _optional_decimal(payload["estimate"])
        if estimate is not None and estimate != estimate.to_integral_value():
            raise _invalid_command("Linear estimate must be a whole integer.")
        result["estimate"] = int(estimate) if estimate is not None else None
    if "label_external_ids" in payload:
        result["labelIds"] = list(
            _required_id(value, field="Linear label ID")
            for value in _sequence(payload["label_external_ids"], field="Linear labels")
        )
    if operation is SorMutationOperation.CREATE:
        return _parse_request(result, LinearIssueCreateInput)
    return _parse_request(result, LinearIssueInput)


def _mutation_record(
    result: LinearIssueMutation | LinearCommentMutation | LinearRelationMutation,
    *,
    operation: str,
) -> LinearMutationRecord:
    if not result.success:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
            f"Linear did not {operation}.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if isinstance(result, LinearIssueMutation):
        if result.issue is None:
            raise _invalid_response(
                "Linear returned no issue for a successful mutation."
            )
        return result.issue
    if isinstance(result, LinearCommentMutation):
        return result.comment
    return result.issue_relation


def _command_result(
    issue: LinearMutationRecord,
    *,
    response: SorJsonResponse,
) -> SorCommandResult:
    issue_id = issue.id
    updated_at = issue.updated_datetime
    return SorCommandResult(
        vendor_object_key=LinearTicketingStream.ISSUES,
        external_id=issue_id,
        external_request_id=_request_id(response),
        source_revision=updated_at.isoformat(),
        source_url=_safe_linear_url(issue.url),
        response={"status": "accepted"},
    )


def _decode_cursor(value: str | None) -> _LinearCursor:
    now = datetime.now(timezone.utc)
    if value is None:
        return _LinearCursor(floor=None, after=None, high=None, started_at=now)
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise _invalid_cursor() from error
    if not isinstance(payload, dict) or set(payload) != {
        "after",
        "floor",
        "high",
        "started_at",
        "v",
    }:
        raise _invalid_cursor()
    if payload.get("v") != LINEAR_CURSOR_VERSION:
        raise _invalid_cursor()
    try:
        floor = _optional_datetime(payload.get("floor"))
        after = _optional_string(payload.get("after"))
        high = _optional_datetime(payload.get("high"))
        started_at = _required_datetime(
            payload.get("started_at"),
            field="Linear cursor start time",
        )
    except SorVendorOperationError as error:
        raise _invalid_cursor() from error
    if after is None:
        return _LinearCursor(
            floor=floor,
            after=None,
            high=None,
            started_at=now,
        )
    if len(after) > 2_048 or high is None:
        raise _invalid_cursor()
    return _LinearCursor(
        floor=floor,
        after=after,
        high=high,
        started_at=started_at,
    )


def _encode_cursor(cursor: _LinearCursor) -> str:
    return json.dumps(
        {
            "after": cursor.after,
            "floor": _datetime_value(cursor.floor),
            "high": _datetime_value(cursor.high),
            "started_at": _datetime_value(cursor.started_at),
            "v": LINEAR_CURSOR_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _completed_cursor(
    *,
    floor: datetime | None,
    high: datetime | None,
    started_at: datetime,
) -> _LinearCursor:
    observed = high or started_at
    candidate = observed - LINEAR_RECONCILIATION_OVERLAP
    if floor is not None and floor > candidate:
        candidate = floor
    return _LinearCursor(
        floor=candidate,
        after=None,
        high=None,
        started_at=started_at,
    )


def _maximum_updated_at(
    rows: Sequence[LinearRecord],
    *,
    current: datetime | None,
) -> datetime | None:
    result = current
    for row in rows:
        updated_at = row.updated_datetime
        if result is None or updated_at > result:
            result = updated_at
    return result


def _invalid_cursor() -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_CURSOR_INVALID,
        "The Linear stream cursor is invalid.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _connection_name(stream_key: LinearTicketingStream) -> str:
    return {
        LinearTicketingStream.WORKFLOW_STATES: "workflowStates",
        LinearTicketingStream.ISSUE_LABELS: "issueLabels",
        LinearTicketingStream.ISSUE_RELATIONS: "issueRelations",
    }.get(stream_key, stream_key.value)


def _page_variables(
    stream_key: LinearTicketingStream, *, limit: int, checkpoint: _LinearCursor
) -> LinearPageVariables:
    if stream_key in _FULL_RECONCILE_STREAMS:
        return LinearPageVariables(first=limit, after=checkpoint.after)
    return LinearPageVariables(
        first=limit,
        after=checkpoint.after,
        filter=(
            LinearUpdatedFilter(
                updatedAt=LinearDateComparator(gte=_linear_datetime(checkpoint.floor))
            )
            if checkpoint.floor is not None
            else None
        ),
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            normalized = value.strip()
            return normalized or None
    return None


def verify_linear_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
    signing_secret: str,
) -> None:
    """Authenticate one raw Linear delivery before parsing or persistence."""
    signature = _header(headers, "linear-signature")
    if signature is None or len(signature) != 64:
        raise SorWebhookVerificationError("Linear webhook signature is invalid.")
    try:
        bytes.fromhex(signature)
    except ValueError as error:
        raise SorWebhookVerificationError(
            "Linear webhook signature is invalid."
        ) from error
    expected = hmac.new(
        signing_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        raise SorWebhookVerificationError("Linear webhook signature is invalid.")

    payload = _linear_webhook_body(body, verification=True)
    timestamp = payload.get("webhookTimestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise SorWebhookVerificationError("Linear webhook timestamp is invalid.")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if abs(now_ms - timestamp) > 60_000:
        raise SorWebhookVerificationError("Linear webhook timestamp is stale.")
    header_timestamp = _header(headers, "linear-timestamp")
    if header_timestamp is not None and header_timestamp != str(timestamp):
        raise SorWebhookVerificationError("Linear webhook timestamps disagree.")


def parse_linear_app_webhook(
    *,
    headers: Mapping[str, str],
    body: bytes,
) -> LinearAppWebhookDelivery:
    """Normalize one Linear app event without assigning it to a source."""
    payload = _linear_webhook_body(body, verification=False)
    delivery_id = _header(headers, "linear-delivery")
    if delivery_id is None or not 1 <= len(delivery_id) <= 512:
        raise SorWebhookPayloadError("Linear webhook delivery ID is invalid.")
    organization_id = _webhook_string(
        payload.get("organizationId"),
        field="organizationId",
    )
    action = _webhook_string(payload.get("action"), field="action")
    event_name = _webhook_string(payload.get("type"), field="type")
    data = payload.get("data")
    if data is None:
        record: Mapping[str, object] = {}
    elif isinstance(data, Mapping) and all(isinstance(key, str) for key in data):
        record = data
    else:
        raise SorWebhookPayloadError("Linear webhook data is invalid.")

    stream_key = _WEBHOOK_STREAMS.get(event_name)
    external_id = _webhook_optional_id(record.get("id"))
    if stream_key is not None and external_id is None:
        raise SorWebhookPayloadError("Linear webhook record identity is missing.")
    return LinearAppWebhookDelivery(
        organization_external_id=organization_id,
        signal=SorWebhookSignal(
            delivery_id=delivery_id,
            event_type=f"{event_name}.{action}",
            vendor_object_key=stream_key,
            external_id=external_id,
            occurred_at=_webhook_datetime(payload),
        ),
    )


def _linear_webhook_body(
    body: bytes,
    *,
    verification: bool,
) -> dict[str, object]:
    error_type = SorWebhookVerificationError if verification else SorWebhookPayloadError
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise error_type("Linear webhook body is not valid JSON.") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise error_type("Linear webhook body must be an object.")
    return value


def _webhook_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise SorWebhookPayloadError(f"Linear webhook {field} is invalid.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 256:
        raise SorWebhookPayloadError(f"Linear webhook {field} is invalid.")
    return normalized


def _webhook_optional_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SorWebhookPayloadError("Linear webhook record identity is invalid.")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 512:
        raise SorWebhookPayloadError("Linear webhook record identity is invalid.")
    return normalized


def _webhook_datetime(payload: Mapping[str, object]) -> datetime:
    value = payload.get("createdAt")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SorWebhookPayloadError(
                "Linear webhook creation time is invalid."
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise SorWebhookPayloadError(
                "Linear webhook creation time must include a timezone."
            )
        return parsed.astimezone(timezone.utc)
    timestamp = payload.get("webhookTimestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise SorWebhookPayloadError("Linear webhook timestamp is invalid.")
    try:
        return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as error:
        raise SorWebhookPayloadError("Linear webhook timestamp is invalid.") from error


def _connection_nodes(value: object, *, field: str) -> list[dict[str, object]]:
    return _object_list(_object(value, field=field).get("nodes"), field=field)


def _require_stream(value: str, *, selected: tuple[str, ...]) -> LinearTicketingStream:
    if value not in _STREAM_ENTITY or value not in selected:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_STREAM_UNSUPPORTED,
            "The requested Linear stream is not selected for this source.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return LinearTicketingStream(value)


def _required_target(command: SorCommandRequest) -> str:
    if command.target_external_id is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "This Linear action requires an existing issue.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _required_id(command.target_external_id, field="Linear issue ID")


def _linear_priority(value: object) -> LinearPriority | None:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return LinearPriority(value)
        except ValueError:
            pass
    if isinstance(value, str):
        normalized = value.strip().casefold()
        values = {
            "none": LinearPriority.NONE,
            "no priority": LinearPriority.NONE,
            "urgent": LinearPriority.URGENT,
            "high": LinearPriority.HIGH,
            "medium": LinearPriority.MEDIUM,
            "low": LinearPriority.LOW,
        }
        if normalized in values:
            return values[normalized]
    raise SorVendorOperationError(
        SorVendorErrorCode.VENDOR_COMMAND_INVALID,
        "Linear priority must be none, urgent, high, medium, low, or 0 through 4.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _linear_relation_kind(
    value: object,
    *,
    error_code: SorVendorErrorCode = SorVendorErrorCode.VENDOR_COMMAND_INVALID,
) -> TicketingRelationKind:
    if isinstance(value, TicketingRelationKind):
        return value
    if isinstance(value, str):
        try:
            return TicketingRelationKind(value.strip().upper())
        except ValueError:
            pass
    raise SorVendorOperationError(
        error_code,
        "Linear relation kind is invalid.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _normalized_linear_relation(value: str) -> TicketingRelationKind:
    try:
        native = LinearRelationType(value.strip().casefold())
    except ValueError:
        raise _invalid_response(
            "Linear returned an unsupported issue relation type."
        ) from None
    relation = {
        LinearRelationType.BLOCKS: TicketingRelationKind.BLOCKS,
        LinearRelationType.DUPLICATE: TicketingRelationKind.DUPLICATE,
        LinearRelationType.RELATED: TicketingRelationKind.RELATED,
        LinearRelationType.SIMILAR: TicketingRelationKind.RELATED,
    }[native]
    return relation


def _normalized_linear_state(value: str | None) -> TicketingWorkState | None:
    if value is None:
        return None
    try:
        native = LinearStateType(value.strip().casefold())
    except ValueError:
        return TicketingWorkState.UNKNOWN
    return {
        LinearStateType.TRIAGE: TicketingWorkState.UNSTARTED,
        LinearStateType.BACKLOG: TicketingWorkState.UNSTARTED,
        LinearStateType.UNSTARTED: TicketingWorkState.UNSTARTED,
        LinearStateType.STARTED: TicketingWorkState.STARTED,
        LinearStateType.COMPLETED: TicketingWorkState.COMPLETED,
        LinearStateType.CANCELED: TicketingWorkState.CANCELLED,
        LinearStateType.CANCELLED: TicketingWorkState.CANCELLED,
    }[native]


def _request_id(response: SorJsonResponse) -> str | None:
    for name in ("x-request-id", "x-linear-request-id"):
        values = response.header_values(name)
        if values:
            return values[0][:512]
    return None


def _safe_linear_url(value: object) -> str | None:
    text = _optional_string(value)
    if text is None or not text.startswith("https://linear.app/"):
        return None
    return text[:2_048]


def _linear_datetime(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _datetime_value(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _credential(credentials: Mapping[str, object], key: str) -> str:
    value = credentials.get(key)
    if not isinstance(value, str) or not value:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_CREDENTIALS_INVALID,
            "The Linear credential is unavailable.",
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


def _sequence(value: object, *, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            f"{field} must be a list.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return tuple(value)


def _required_id(value: object, *, field: str) -> str:
    result = _required_string(value, field=field)
    if len(result) > 512:
        raise _invalid_response(f"{field} is too long.")
    return result


def _nullable_id(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_id(value, field=field)


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response(f"{field} is missing.")
    return value.strip()


def _nullable_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            f"{field} must be text or null.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return value


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
            raise _invalid_response("Linear due date is invalid.") from error
    raise _invalid_response("Linear due date is invalid.")


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _invalid_response("Linear numeric value is invalid.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise _invalid_response("Linear numeric value is invalid.") from error
    if not result.is_finite():
        raise _invalid_response("Linear numeric value is invalid.")
    return result


def _optional_integer(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    decimal = _optional_decimal(value)
    if decimal is None or decimal != decimal.to_integral_value():
        raise _invalid_response(f"{field} is invalid.")
    return int(decimal)


def _required_boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_response(f"{field} is missing or invalid.")
    return value


def _optional_boolean(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise _invalid_response("Linear boolean value is invalid.")
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _invalid_response("Linear label IDs are invalid.")
    result = tuple(_required_id(item, field="Linear label ID") for item in value)
    if len(result) != len(set(result)):
        raise _invalid_response("Linear label IDs contain duplicates.")
    return result


def _json_value(value: object) -> SorJsonValue:
    try:
        return require_json_value(value)
    except ValueError as error:
        raise _invalid_response(
            "Linear source content is not JSON-compatible."
        ) from error


def _invalid_response(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _parse_native[ModelT: LinearNativeModel](
    value: object, model: type[ModelT]
) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _invalid_response(
            "Linear returned an invalid ticketing response."
        ) from None


def _parse_request[ModelT: LinearRequestModel](
    value: object, model: type[ModelT]
) -> ModelT:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _invalid_command("Linear request fields are invalid.") from None


def _invalid_command(message: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
        message,
        recovery=SorRecoveryPolicy.TERMINAL,
    )


__all__ = [
    "LINEAR_API_VERSION",
    "LINEAR_MANIFEST",
    "LINEAR_ORIGIN",
    "LinearTicketingAdapter",
    "create_linear_adapter",
    "parse_linear_app_webhook",
    "verify_linear_app_webhook",
]
