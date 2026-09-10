"""Native Linear Ticketing requests and replies, separate from canonical SOR data."""

from datetime import date, datetime, timezone
from enum import IntEnum, StrEnum
from typing import Annotated, ClassVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    model_validator,
)

MAX_PAGE_RECORDS = 200
_MAX_IDENTIFIER_CHARS = 512
_GRAPHQL_INTEGER_MIN = -2_147_483_648
_GRAPHQL_INTEGER_MAX = 2_147_483_647


class LinearTicketingStream(StrEnum):
    """Closed vendor stream vocabulary owned by the Ticketing adapter."""

    ISSUES = "issues"
    TEAMS = "teams"
    PROJECTS = "projects"
    WORKFLOW_STATES = "workflow_states"
    USERS = "users"
    ISSUE_LABELS = "issue_labels"
    CYCLES = "cycles"
    COMMENTS = "comments"
    ISSUE_RELATIONS = "issue_relations"


class LinearRelationType(StrEnum):
    """Native relation input values; endpoint direction is handled by the adapter."""

    BLOCKS = "blocks"
    DUPLICATE = "duplicate"
    RELATED = "related"
    SIMILAR = "similar"


class LinearPriority(IntEnum):
    """Native priority codes, serialized as GraphQL integer values."""

    NONE = 0
    URGENT = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class LinearStateType(StrEnum):
    """Known native categories; unknown response strings are retained separately."""

    TRIAGE = "triage"
    BACKLOG = "backlog"
    UNSTARTED = "unstarted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELED = "canceled"
    CANCELLED = "cancelled"


class LinearLabelAction(StrEnum):
    """An explicit update action, not a boolean mode flag."""

    ADD = "add"
    REMOVE = "remove"


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Linear Ticketing timestamps require a timezone.")
    return parsed.astimezone(timezone.utc)


def _validate_timestamp(value: str) -> str:
    _timestamp(value)
    return value


def _validate_date(value: str) -> str:
    date.fromisoformat(value)
    return value


LinearIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=_MAX_IDENTIFIER_CHARS
    ),
]
# Preserve exact timestamp/number representation in mapped payloads and hashes.
LinearTimestamp = Annotated[str, AfterValidator(_validate_timestamp)]
LinearDate = Annotated[str, AfterValidator(_validate_date)]
LinearNumber = int | FiniteFloat


class LinearNativeModel(BaseModel):
    """Strict consumed fields; additional vendor selections are forward-compatible."""

    model_config = ConfigDict(
        extra="ignore", strict=True, frozen=True, hide_input_in_errors=True
    )


class LinearReference(LinearNativeModel):
    """An ID-only nested query selection."""

    id: LinearIdentifier


class LinearStateReference(LinearReference):
    """Selected native state label; its category remains open vendor data."""

    name: str
    type: str


class LinearLabelNodes(LinearNativeModel):
    """Label identities selected by issue reads and label-update preparation."""

    nodes: list[LinearReference]


class LinearRecord(LinearReference):
    """Shared native metadata; a concrete record owns its stream identity."""

    stream: ClassVar[LinearTicketingStream]
    created_at: LinearTimestamp = Field(alias="createdAt")
    updated_at: LinearTimestamp = Field(alias="updatedAt")
    archived_at: LinearTimestamp | None = Field(default=None, alias="archivedAt")
    url: str | None = None

    @property
    def created_datetime(self) -> datetime:
        return _timestamp(self.created_at)

    @property
    def updated_datetime(self) -> datetime:
        return _timestamp(self.updated_at)

    @property
    def archived_datetime(self) -> datetime | None:
        return _timestamp(self.archived_at) if self.archived_at is not None else None


class LinearIssue(LinearRecord):
    """Issue fields consumed by sync and exact-record reads."""

    stream = LinearTicketingStream.ISSUES
    identifier: str
    title: str
    description: str | None = Field(default=None, repr=False)
    url: str
    priority_label: str = Field(alias="priorityLabel")
    estimate: LinearNumber | None = None
    state: LinearStateReference
    team: LinearReference
    project: LinearReference | None = None
    assignee: LinearReference | None = None
    creator: LinearReference | None = None
    parent: LinearReference | None = None
    cycle: LinearReference | None = None
    labels: LinearLabelNodes
    due_date: LinearDate | None = Field(default=None, alias="dueDate")
    started_at: LinearTimestamp | None = Field(default=None, alias="startedAt")
    completed_at: LinearTimestamp | None = Field(default=None, alias="completedAt")
    canceled_at: LinearTimestamp | None = Field(default=None, alias="canceledAt")


class LinearTeam(LinearRecord):
    """A team is a native record, not a canonical project type alias."""

    stream = LinearTicketingStream.TEAMS
    key: str
    name: str
    description: str | None = Field(default=None, repr=False)


class LinearProject(LinearRecord):
    """Native project fields selected by the sync query."""

    stream = LinearTicketingStream.PROJECTS
    slug_id: str = Field(alias="slugId")
    name: str
    description: str = Field(repr=False)
    url: str


class LinearWorkflowState(LinearRecord):
    """Native floating-point order and open state category."""

    stream = LinearTicketingStream.WORKFLOW_STATES
    name: str
    type: str
    position: LinearNumber
    team: LinearReference


class LinearUser(LinearRecord):
    """Selected account fields, not an Eylo contact or member."""

    stream = LinearTicketingStream.USERS
    name: str
    display_name: str = Field(alias="displayName")
    email: str = Field(repr=False)
    active: bool
    is_assignable: bool = Field(alias="isAssignable")
    avatar_url: str | None = Field(default=None, alias="avatarUrl")
    url: str


class LinearLabel(LinearRecord):
    """A label may be global or owned by a team and nested under another label."""

    stream = LinearTicketingStream.ISSUE_LABELS
    name: str
    description: str | None = Field(default=None, repr=False)
    color: str
    is_group: bool = Field(alias="isGroup")
    team: LinearReference | None = None
    parent: LinearReference | None = None


class LinearCycle(LinearRecord):
    """Native cycle numbers are GraphQL floats; canonical integer policy is separate."""

    stream = LinearTicketingStream.CYCLES
    name: str | None = None
    number: LinearNumber
    description: str | None = Field(default=None, repr=False)
    starts_at: LinearTimestamp = Field(alias="startsAt")
    ends_at: LinearTimestamp = Field(alias="endsAt")
    completed_at: LinearTimestamp | None = Field(default=None, alias="completedAt")
    is_active: bool = Field(alias="isActive")
    team: LinearReference


class LinearComment(LinearRecord):
    """Native comments may have neither an issue nor a surviving user."""

    stream = LinearTicketingStream.COMMENTS
    body: str = Field(repr=False)
    issue: LinearReference | None = None
    user: LinearReference | None = None


class LinearIssueRelation(LinearRecord):
    """Directed native relation whose endpoints are required by Linear."""

    stream = LinearTicketingStream.ISSUE_RELATIONS
    type: str
    issue: LinearReference
    related_issue: LinearReference = Field(alias="relatedIssue")


class LinearPageInfo(LinearNativeModel):
    """A partial forward page requires a non-empty continuation cursor."""

    has_next_page: bool = Field(alias="hasNextPage")
    end_cursor: str | None = Field(default=None, alias="endCursor")

    @model_validator(mode="after")
    def require_continuation(self) -> "LinearPageInfo":
        if self.has_next_page and not (self.end_cursor or "").strip():
            raise ValueError("A partial Linear page requires an end cursor.")
        return self


class LinearConnection[RecordT: LinearRecord](LinearNativeModel):
    """Validate every selected node before projecting any part of the page."""

    nodes: list[RecordT] = Field(repr=False)
    page_info: LinearPageInfo = Field(alias="pageInfo")


type LinearTicketingRecord = (
    LinearIssue
    | LinearTeam
    | LinearProject
    | LinearWorkflowState
    | LinearUser
    | LinearLabel
    | LinearCycle
    | LinearComment
    | LinearIssueRelation
)
type LinearTicketingPage = (
    LinearConnection[LinearIssue]
    | LinearConnection[LinearTeam]
    | LinearConnection[LinearProject]
    | LinearConnection[LinearWorkflowState]
    | LinearConnection[LinearUser]
    | LinearConnection[LinearLabel]
    | LinearConnection[LinearCycle]
    | LinearConnection[LinearComment]
    | LinearConnection[LinearIssueRelation]
)

RECORD_MODELS: dict[LinearTicketingStream, type[LinearTicketingRecord]] = {
    LinearTicketingStream.ISSUES: LinearIssue,
    LinearTicketingStream.TEAMS: LinearTeam,
    LinearTicketingStream.PROJECTS: LinearProject,
    LinearTicketingStream.WORKFLOW_STATES: LinearWorkflowState,
    LinearTicketingStream.USERS: LinearUser,
    LinearTicketingStream.ISSUE_LABELS: LinearLabel,
    LinearTicketingStream.CYCLES: LinearCycle,
    LinearTicketingStream.COMMENTS: LinearComment,
    LinearTicketingStream.ISSUE_RELATIONS: LinearIssueRelation,
}
PAGE_MODELS: dict[LinearTicketingStream, type[LinearTicketingPage]] = {
    LinearTicketingStream.ISSUES: LinearConnection[LinearIssue],
    LinearTicketingStream.TEAMS: LinearConnection[LinearTeam],
    LinearTicketingStream.PROJECTS: LinearConnection[LinearProject],
    LinearTicketingStream.WORKFLOW_STATES: LinearConnection[LinearWorkflowState],
    LinearTicketingStream.USERS: LinearConnection[LinearUser],
    LinearTicketingStream.ISSUE_LABELS: LinearConnection[LinearLabel],
    LinearTicketingStream.CYCLES: LinearConnection[LinearCycle],
    LinearTicketingStream.COMMENTS: LinearConnection[LinearComment],
    LinearTicketingStream.ISSUE_RELATIONS: LinearConnection[LinearIssueRelation],
}


class LinearWorkspace(LinearReference):
    """Workspace label selected for credential verification."""

    name: str


class LinearWorkspaceResult(LinearNativeModel):
    """Only the organization projection is consumed from verification."""

    organization: LinearWorkspace


class LinearIssueLabels(LinearReference):
    """Narrow read used before adding or removing an issue label."""

    labels: LinearLabelNodes


class LinearIssueLabelsResult(LinearNativeModel):
    """An explicit null issue is not found; missing selection is malformed."""

    issue: LinearIssueLabels | None


class LinearMutationRecord(LinearReference):
    """Only identity/revision fields consumed from a mutation's entity result."""

    updated_at: LinearTimestamp = Field(alias="updatedAt")
    url: str | None = None

    @property
    def updated_datetime(self) -> datetime:
        return _timestamp(self.updated_at)


class LinearIssueMutation(LinearNativeModel):
    """Issue payload permits null; success is checked before consuming the record."""

    success: bool
    issue: LinearMutationRecord | None


class LinearCommentMutation(LinearNativeModel):
    """The consumed comment mutation reply."""

    success: bool
    comment: LinearMutationRecord


class LinearRelationMutation(LinearNativeModel):
    """The consumed relation mutation reply."""

    success: bool
    issue_relation: LinearMutationRecord = Field(alias="issueRelation")


class LinearCreateResult(LinearNativeModel):
    """Native issue-create result key."""

    issue_create: LinearIssueMutation = Field(alias="issueCreate")


class LinearUpdateResult(LinearNativeModel):
    """Native issue-update result key."""

    issue_update: LinearIssueMutation = Field(alias="issueUpdate")


class LinearCommentResult(LinearNativeModel):
    """Native comment-create result key."""

    comment_create: LinearCommentMutation = Field(alias="commentCreate")


class LinearRelationResult(LinearNativeModel):
    """Native relation-create result key."""

    issue_relation_create: LinearRelationMutation = Field(alias="issueRelationCreate")


class LinearRequestModel(LinearNativeModel):
    """Known request keys only; omission and explicit null remain distinct."""

    model_config = ConfigDict(extra="forbid")


class LinearRecordVariables(LinearRequestModel):
    """Exact identity for a read operation."""

    id: LinearIdentifier


class LinearDateComparator(LinearRequestModel):
    """Native lower-bound comparison used for incremental reads."""

    gte: LinearTimestamp


class LinearUpdatedFilter(LinearRequestModel):
    """Updated-at filter, absent entirely for unfilterable relation streams."""

    updated_at: LinearDateComparator = Field(alias="updatedAt")


class LinearPageVariables(LinearRequestModel):
    """Forward page variables; exclude-unset serialization preserves omitted filter."""

    first: int = Field(ge=1, le=MAX_PAGE_RECORDS)
    after: str | None
    filter: LinearUpdatedFilter | None = None


class LinearIssueInput(LinearRequestModel):
    """Supported issue-write fields, leaving unspecified fields untouched."""

    title: str | None = None
    description: str | None = None
    priority: LinearPriority | None = None
    estimate: int | None = Field(
        default=None, ge=_GRAPHQL_INTEGER_MIN, le=_GRAPHQL_INTEGER_MAX
    )
    project_id: LinearIdentifier | None = Field(default=None, alias="projectId")
    team_id: LinearIdentifier | None = Field(default=None, alias="teamId")
    assignee_id: LinearIdentifier | None = Field(default=None, alias="assigneeId")
    parent_id: LinearIdentifier | None = Field(default=None, alias="parentId")
    cycle_id: LinearIdentifier | None = Field(default=None, alias="cycleId")
    state_id: LinearIdentifier | None = Field(default=None, alias="stateId")
    due_date: LinearDate | None = Field(default=None, alias="dueDate")
    label_ids: list[LinearIdentifier] | None = Field(default=None, alias="labelIds")

    @model_validator(mode="after")
    def require_fields(self) -> "LinearIssueInput":
        if not self.model_fields_set:
            raise ValueError("A Linear issue write requires fields.")
        return self


class LinearIssueCreateInput(LinearIssueInput):
    """Linear requires a team; Eylo's existing create tool also requires a title."""

    title: str
    team_id: LinearIdentifier = Field(alias="teamId")


class LinearCreateVariables(LinearRequestModel):
    """Native create operation input."""

    input: LinearIssueCreateInput


class LinearUpdateVariables(LinearRecordVariables):
    """Native update operation target and partial field set."""

    input: LinearIssueInput


class LinearCommentInput(LinearRequestModel):
    """The issue and body required by Eylo's issue-comment tool."""

    issue_id: LinearIdentifier = Field(alias="issueId")
    body: str


class LinearCommentVariables(LinearRequestModel):
    """Native comment-create input."""

    input: LinearCommentInput


class LinearRelationInput(LinearRequestModel):
    """Native relation endpoints and kind after canonical direction translation."""

    issue_id: LinearIdentifier = Field(alias="issueId")
    related_issue_id: LinearIdentifier = Field(alias="relatedIssueId")
    type: LinearRelationType


class LinearRelationVariables(LinearRequestModel):
    """Native relation-create input."""

    input: LinearRelationInput


type LinearVariables = (
    LinearRecordVariables
    | LinearPageVariables
    | LinearCreateVariables
    | LinearUpdateVariables
    | LinearCommentVariables
    | LinearRelationVariables
)
