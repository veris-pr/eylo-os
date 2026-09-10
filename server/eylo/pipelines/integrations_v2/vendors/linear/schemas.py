"""Linear GraphQL selections and requests owned by the curated integration.

These are not SOR entities. Unknown vendor fields are ignored; selected fields
validate before tools resolve identities, project results, or perform mutations.
"""

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_serializer,
)

DEFAULT_ISSUE_LIMIT = 25
MAX_ISSUES = 100
IDENTITY_LOOKUP_LIMIT = 2
MAX_ERROR_MESSAGE_CHARS = 500


class LinearToolName(StrEnum):
    LIST_ISSUES = "list_issues"
    CREATE_ISSUE = "create_issue"
    REMOVE_ISSUE_LABEL = "remove_issue_label"


class LinearToolErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    ISSUE_NOT_FOUND = "issue_not_found"
    LABEL_NOT_PRESENT = "label_not_present"
    TEAM_NOT_FOUND = "team_not_found"
    TEAM_AMBIGUOUS = "team_ambiguous"
    USER_NOT_FOUND = "user_not_found"


class LinearPriority(IntEnum):
    NONE = 0
    URGENT = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Linear timestamps require a timezone.")
    return value


LinearTimestamp = Annotated[str, AfterValidator(_timestamp)]
LinearIdentifier = Annotated[str, StringConstraints(min_length=1)]


class LinearModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore", strict=True, frozen=True, hide_input_in_errors=True
    )


class LinearNamedRecord(LinearModel):
    id: LinearIdentifier
    name: str


class LinearState(LinearNamedRecord):
    # Response categories are open vendor data, not an Eylo lifecycle enum.
    type: str


class LinearUser(LinearNamedRecord):
    email: str = Field(repr=False)


class LinearTeam(LinearNamedRecord):
    key: str


class LinearConnection[NodeT: LinearModel](LinearModel):
    """Reject the complete selection when any node is malformed."""

    nodes: list[NodeT] = Field(repr=False)


class LinearIssue(LinearModel):
    id: LinearIdentifier
    identifier: str
    title: str
    description: str | None = Field(default=None, repr=False)
    url: str
    priority_label: str = Field(alias="priorityLabel")
    state: LinearState
    assignee: LinearUser | None = None
    team: LinearTeam
    labels: LinearConnection[LinearNamedRecord]
    created_at: LinearTimestamp = Field(alias="createdAt")
    updated_at: LinearTimestamp = Field(alias="updatedAt")


class LinearIssuesResult(LinearModel):
    issues: LinearConnection[LinearIssue]


class LinearIssueResult(LinearModel):
    """Explicit null means not found; a missing selection is malformed."""

    issue: LinearIssue | None


class LinearTeamsResult(LinearModel):
    teams: LinearConnection[LinearTeam]


class LinearUsersResult(LinearModel):
    users: LinearConnection[LinearUser]


class LinearMutationPayload(LinearModel):
    success: bool
    issue: LinearIssue | None


class LinearCreateResult(LinearModel):
    issue_create: LinearMutationPayload = Field(alias="issueCreate")


class LinearUpdateResult(LinearModel):
    issue_update: LinearMutationPayload = Field(alias="issueUpdate")


class LinearGraphQLError(LinearModel):
    message: str = Field(repr=False)


class LinearEnvelope(LinearModel):
    data: dict[str, JsonValue] | None = Field(default=None, repr=False)
    errors: list[LinearGraphQLError] | None = Field(default=None, repr=False)


class LinearRequest(LinearModel):
    """A misspelled outbound key is an implementation error."""

    model_config = ConfigDict(extra="forbid")


class LinearStringComparator(LinearRequest):
    eq_ignore_case: str = Field(alias="eqIgnoreCase")


class LinearTeamFilter(LinearRequest):
    name: LinearStringComparator


class LinearUserFilter(LinearRequest):
    email: LinearStringComparator


class LinearIssueFilter(LinearRequest):
    team: LinearTeamFilter | None = None
    assignee: LinearUserFilter | None = None


class LinearIssuesVariables(LinearRequest):
    first: int = Field(ge=1, le=MAX_ISSUES)
    filter: LinearIssueFilter | None

    @field_serializer("filter")
    def serialize_filter(
        self, value: LinearIssueFilter | None
    ) -> dict[str, JsonValue] | None:
        """Keep outer null while omitting unused nested filter predicates."""
        return (
            value.model_dump(mode="json", by_alias=True, exclude_none=True)
            if value
            else None
        )


class LinearTeamVariables(LinearRequest):
    name: str


class LinearUserVariables(LinearRequest):
    email: str


class LinearIssueVariables(LinearRequest):
    id: LinearIdentifier


class LinearCreateInput(LinearRequest):
    # Preserve request field order: durable transport fingerprints JSON bytes.
    title: str
    team_id: LinearIdentifier = Field(alias="teamId")
    description: str | None = Field(default=None, repr=False)
    assignee_id: LinearIdentifier | None = Field(default=None, alias="assigneeId")
    priority: LinearPriority | None = None


class LinearCreateVariables(LinearRequest):
    input: LinearCreateInput

    @field_serializer("input")
    def serialize_input(self, value: LinearCreateInput) -> dict[str, JsonValue]:
        """The existing create tool omits optional fields, never sends null."""
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)


class LinearLabelInput(LinearRequest):
    label_ids: list[LinearIdentifier] = Field(alias="labelIds")


class LinearUpdateVariables(LinearIssueVariables):
    input: LinearLabelInput


class LinearIssueView(LinearModel):
    """Stable flat tool result; vendor reference objects do not escape."""

    id: str
    identifier: str
    title: str
    description: str | None = Field(repr=False)
    url: str
    priority: str
    state: str
    assignee_name: str | None
    assignee_email: str | None = Field(repr=False)
    team_name: str
    labels: list[str]
    created_at: str
    updated_at: str


class LinearIssueListView(LinearModel):
    issues: list[LinearIssueView]
    count: int = Field(ge=0)
