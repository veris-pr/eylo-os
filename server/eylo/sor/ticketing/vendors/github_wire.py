"""GitHub-native operation contracts, independent of canonical ticketing policy."""

from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    field_validator,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue


class GitHubResponse(BaseModel):
    """Validate consumed native fields; ignore unrelated vendor additions."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class GitHubViewer(GitHubResponse):
    login: str
    name: str | None = None


class GitHubRecord(GitHubResponse):
    created_at: str | None = None
    updated_at: str | None = None
    html_url: str | None = None


class GitHubRepository(GitHubRecord):
    full_name: str
    description: str | None = None


class GitHubUser(GitHubRecord):
    login: str
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    suspended_at: str | None = None


class GitHubUserReference(GitHubResponse):
    login: str | None = None


class GitHubLabelReference(GitHubResponse):
    name: str


class GitHubMilestoneReference(GitHubResponse):
    number: int


class GitHubLabel(GitHubRecord):
    name: str
    description: str | None = None
    color: str | None = None


class GitHubMilestone(GitHubRecord):
    number: int
    title: str
    state: str | None = None
    description: str | None = None
    due_on: str | None = None
    closed_at: str | None = None


class GitHubIssue(GitHubRecord):
    number: int
    title: str
    state: str
    state_reason: str | None = None
    body: str | None = Field(default=None, repr=False)
    user: GitHubUserReference | None = None
    assignee: GitHubUserReference | None = None
    milestone: GitHubMilestoneReference | None = None
    labels: list[GitHubLabelReference] | None = None
    closed_at: str | None = None


class GitHubCommentLocation(GitHubResponse):
    """Only parent identity is needed before excluding out-of-scope PR comments."""

    issue_url: str


class GitHubComment(GitHubRecord):
    id: int
    issue_url: str
    body: str = Field(repr=False)
    user: GitHubUserReference | None = None


class GitHubRecordState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"


class GitHubStateReason(StrEnum):
    COMPLETED = "completed"
    NOT_PLANNED = "not_planned"
    REOPENED = "reopened"


class GitHubSort(StrEnum):
    UPDATED = "updated"


class GitHubSortDirection(StrEnum):
    ASCENDING = "asc"


GITHUB_REST_PAGE_LIMIT = 100


class GitHubListQuery(BaseModel):
    """Serialize only explicitly chosen endpoint parameters, never implicit filters."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    per_page: int = Field(ge=1, le=GITHUB_REST_PAGE_LIMIT)
    page: int = Field(ge=1)
    state: GitHubRecordState | None = None
    sort: GitHubSort | None = None
    direction: GitHubSortDirection | None = None
    since: str | None = None


type GitHubRestRecord = (
    GitHubRepository
    | GitHubUser
    | GitHubLabel
    | GitHubMilestone
    | GitHubIssue
    | GitHubComment
)


class GitHubGraphQLErrorType(StrEnum):
    RATE_LIMITED = "RATE_LIMITED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"


class GitHubGraphQLError(GitHubResponse):
    # Unknown vendor errors retain the established generic failure outcome.
    type: str | None = None


class GitHubGraphQLEnvelope(GitHubResponse):
    """Classify errors before validating operation-specific data or partial results."""

    errors: list[GitHubGraphQLError] | None = None
    data: SorJsonValue = Field(default=None, repr=False)


class GitHubRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class GitHubGraphQLRequest(GitHubRequest):
    """Generated alias variables are strings, not an arbitrary JSON request bag."""

    query: str
    variables: dict[str, str]


class GitHubIssueWrite(GitHubRequest):
    """Use exclude_unset, not exclude_none: explicit nulls clear existing fields."""

    title: str | None = None
    body: str | None = Field(default=None, repr=False)
    assignees: list[str] | None = None
    labels: list[str] | None = None
    milestone: int | None = None
    state: Literal[GitHubRecordState.OPEN, GitHubRecordState.CLOSED] | None = None
    state_reason: GitHubStateReason | None = None


class GitHubIssueWriteResult(GitHubRecord):
    # Updates may retain the known target; creates require returned identity.
    number: int | None = None


class GitHubCommentWrite(GitHubRequest):
    body: str = Field(repr=False)


class GitHubCommentWriteResult(GitHubRecord):
    id: int


class GitHubLabelWrite(GitHubRequest):
    labels: list[str]


class GitHubLabelAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"


class GitHubGraphQLRepository(GitHubResponse):
    nameWithOwner: str
    description: str | None = None
    url: str | None = None
    updatedAt: str | None = None


class GitHubRepositoryBatch(RootModel[dict[str, GitHubGraphQLRepository | None]]):
    """Generated repo aliases are dynamic; their selected native fields are not."""

    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)


class GitHubIssueKind(StrEnum):
    ISSUE = "Issue"
    PULL_REQUEST = "PullRequest"


class GitHubIssueClassification(GitHubResponse):
    typename: GitHubIssueKind = Field(alias="__typename")

    @field_validator("typename", mode="before")
    @classmethod
    def parse_kind(cls, value: object) -> GitHubIssueKind:
        if not isinstance(value, str):
            raise ValueError("GitHub issue kind must be text.")
        return GitHubIssueKind(value.strip())


class GitHubIssueClassifications(
    RootModel[dict[str, GitHubIssueClassification | None]]
):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)


class GitHubIssueClassificationData(GitHubResponse):
    repository: GitHubIssueClassifications


def parse_response[T: BaseModel](value: object, model: type[T]) -> T:
    """Contain native validation details at the adapter's safe error boundary."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "GitHub returned invalid response fields.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def parse_request[T: BaseModel](value: object, model: type[T]) -> T:
    """Validate translated command fields before the vendor side effect."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "The GitHub request contains invalid fields.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
