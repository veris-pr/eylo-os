"""GitHub REST wire contracts and curated results, separate from SOR entities.

Validate consumed response fields; ignore unrelated vendor additions. Keep native
open vocabularies as strings and request choices as enums. Request field order
and omission preserve persisted mutation fingerprints.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_BODY_CHARS = 6_000
MAX_COMMENTS = 20
MAX_FILES = 50
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50
LEGACY_BASE_BRANCH = "main"
SEARCH_PATH = "/search/issues"


class GitHubQueryState(StrEnum):
    """ALL is a query option, not an issue or pull request lifecycle state."""

    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        return next((state for state in cls if state.value == normalized), None)


class GitHubReviewState(StrEnum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


class GitHubToolErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SEARCH_UNBOUNDED = "search_unbounded"
    REPOSITORY_INVALID = "repository_invalid"


class GitHubModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class GitHubRequest(GitHubModel):
    model_config = ConfigDict(extra="forbid")


class GitHubSearchQuery(GitHubRequest):
    q: str
    per_page: int = Field(ge=1, le=MAX_LIST_LIMIT)
    sort: Literal["updated"] = "updated"


class GitHubPageQuery(GitHubRequest):
    per_page: int = Field(ge=1, le=MAX_LIST_LIMIT)


class GitHubPullsQuery(GitHubRequest):
    state: GitHubQueryState
    per_page: int = Field(ge=1, le=MAX_LIST_LIMIT)
    sort: Literal["updated"] = "updated"
    direction: Literal["desc"] = "desc"
    base: str | None = None


class GitHubCreateIssueRequest(GitHubRequest):
    title: str = Field(min_length=1)
    body: str | None = Field(default=None, repr=False)
    labels: list[str] | None = None
    assignees: list[str] | None = None


class GitHubCommentRequest(GitHubRequest):
    body: str = Field(min_length=1, repr=False)


class GitHubCreatePullRequest(GitHubRequest):
    title: str = Field(min_length=1)
    head: str = Field(min_length=1)
    base: str
    draft: bool
    body: str | None = Field(default=None, repr=False)


class GitHubUser(GitHubModel):
    login: str


class GitHubLabel(GitHubModel):
    name: str | None = None


class GitHubPullReference(GitHubModel):
    html_url: str | None


class GitHubIssue(GitHubModel):
    number: int = Field(ge=1)
    title: str
    state: str
    user: GitHubUser | None
    labels: list[GitHubLabel | str]
    assignees: list[GitHubUser] | None = None
    comments: int = Field(ge=0)
    created_at: str
    updated_at: str
    closed_at: str | None
    html_url: str
    body: str | None = Field(default=None, repr=False)
    pull_request: GitHubPullReference | None = None


class GitHubIssueSearch(GitHubModel):
    items: list[GitHubIssue]
    total_count: int = Field(ge=0)


class GitHubComment(GitHubModel):
    id: int = Field(ge=1)
    user: GitHubUser | None
    body: str | None = Field(default=None, repr=False)
    created_at: str
    html_url: str


class GitHubBranch(GitHubModel):
    ref: str


class GitHubPull(GitHubModel):
    number: int = Field(ge=1)
    title: str
    state: str
    user: GitHubUser | None
    head: GitHubBranch
    base: GitHubBranch
    draft: bool | None = None
    merged_at: str | None
    created_at: str
    updated_at: str
    html_url: str


class GitHubPullDetail(GitHubPull):
    body: str | None = Field(repr=False)
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changed_files: int = Field(ge=0)
    mergeable: bool | None


class GitHubFile(GitHubModel):
    filename: str
    status: str
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)


class GitHubReview(GitHubModel):
    user: GitHubUser | None
    state: str
    submitted_at: str | None = None


class GitHubErrorEnvelope(GitHubModel):
    message: str | None = Field(default=None, repr=False)
    id: int | None = None
    number: int | None = None


class GitHubCommentView(GitHubModel):
    id: int
    author: str | None
    body: str | None = Field(repr=False)
    created_at: str
    web_link: str


class GitHubIssueView(GitHubModel):
    """Validated result builder; optional detail is populated before serialization."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    number: int
    title: str
    state: str
    author: str | None
    labels: list[str | None]
    assignees: list[str]
    comment_count: int
    created_at: str
    updated_at: str
    closed_at: str | None
    web_link: str
    is_pull_request: bool
    body: str | None = Field(default=None, repr=False)
    comments: list[GitHubCommentView] | None = None


class GitHubSearchResult(GitHubModel):
    issues: list[GitHubIssueView]
    count: int
    total_matches: int
    query: str


class GitHubReviewView(GitHubModel):
    reviewer: str | None
    state: str
    submitted_at: str | None


class GitHubPullView(GitHubModel):
    """Validated result builder; omitted pages remain absent, not empty successes."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    number: int
    title: str
    state: str
    author: str | None
    head_branch: str
    base_branch: str
    draft: bool | None
    merged: bool
    merged_at: str | None
    created_at: str
    updated_at: str
    web_link: str
    body: str | None = Field(default=None, repr=False)
    additions: int | None = None
    deletions: int | None = None
    changed_files: int | None = None
    mergeable: bool | None = None
    files: list[GitHubFile] | None = None
    reviews: list[GitHubReviewView] | None = None
    approved: bool | None = None


class GitHubPullsResult(GitHubModel):
    repository: str
    pull_requests: list[GitHubPullView]
    count: int


ISSUE_RESPONSE = TypeAdapter(GitHubIssue)
ISSUE_SEARCH_RESPONSE = TypeAdapter(GitHubIssueSearch)
COMMENT_RESPONSE = TypeAdapter(GitHubComment)
COMMENTS_RESPONSE = TypeAdapter(list[GitHubComment])
PULL_RESPONSE = TypeAdapter(GitHubPull)
PULL_DETAIL_RESPONSE = TypeAdapter(GitHubPullDetail)
PULLS_RESPONSE = TypeAdapter(list[GitHubPull])
FILES_RESPONSE = TypeAdapter(list[GitHubFile])
REVIEWS_RESPONSE = TypeAdapter(list[GitHubReview])


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """Validate after the single receipt-owning send; never retry a mutation.

    Native diagnostics can contain private repository data. Expose only fixed
    error text, not Pydantic input excerpts or GitHub's raw error message.
    """
    if not response.ok:
        raise VendorToolError(
            GitHubToolErrorCode.REJECTED, "GitHub rejected the request."
        )
    try:
        if isinstance(response.data, dict):
            envelope = GitHubErrorEnvelope.model_validate(response.data)
            if (
                envelope.message is not None
                and envelope.id is None
                and envelope.number is None
            ):
                raise VendorToolError(
                    GitHubToolErrorCode.REJECTED, "GitHub rejected the request."
                )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            GitHubToolErrorCode.RESPONSE_INVALID,
            "GitHub returned an invalid response for this operation.",
        ) from None


def require_number(actual: int, requested: int) -> None:
    if actual != requested:
        raise VendorToolError(
            GitHubToolErrorCode.RESPONSE_INVALID,
            "GitHub returned a different issue or pull request.",
        )
