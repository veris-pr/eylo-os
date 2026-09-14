"""GitLab REST v4 consumed wire contracts and curated result projections.

These are vendor types, not SOR entities. Requests are closed; responses ignore
unrelated additions while validating fields used to report identity or success.
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_BODY_CHARS = 6_000
MAX_NOTES = 20
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
# Eylo bounds username-resolution I/O; this is not a GitLab tier limit.
MAX_ASSIGNEE_LOOKUPS = 20
USER_LOOKUP_LIMIT = 2
REST_PATH = "/v4"
PROJECTS_PATH = f"{REST_PATH}/projects"
USERS_PATH = f"{REST_PATH}/users"
GRAPHQL_PATH = "/graphql"
PROJECT_GLOBAL_ID_PREFIX = "gid://gitlab/Project/"
MAX_PROJECT_REFERENCE_CHARS = 512


class GitLabGraphQLDocument(StrEnum):
    PROJECT_ID = "query EyloProject($fullPath: ID!) { project(fullPath: $fullPath) { id fullPath } }"


class _GitLabQueryChoice(StrEnum):
    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        return next((choice for choice in cls if choice.value == normalized), None)


class GitLabIssueQueryState(_GitLabQueryChoice):
    OPENED = "opened"
    CLOSED = "closed"
    ALL = "all"


class GitLabMergeRequestQueryState(_GitLabQueryChoice):
    OPENED = "opened"
    CLOSED = "closed"
    MERGED = "merged"
    ALL = "all"


class GitLabErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    PROJECT_UNAVAILABLE = "project_unavailable"
    ASSIGNEE_UNRESOLVED = "assignee_unresolved"


class GitLabModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class GitLabRequest(GitLabModel):
    model_config = ConfigDict(extra="forbid")


def project_reference(value: str) -> str:
    """Accept IDs or literal full paths, never URLs or pre-encoded route fragments."""
    value = value.strip()
    if value.isascii() and value.isdecimal():
        if int(value) > 0:
            return str(int(value))
    elif "/" in value and all(
        part not in {"", ".", ".."}
        and all(char.isalnum() or char in "_.-" for char in part)
        for part in value.split("/")
    ):
        return value
    raise ValueError("Use a positive numeric project ID or literal group/project path.")


ProjectReference = Annotated[
    str,
    Field(min_length=1, max_length=MAX_PROJECT_REFERENCE_CHARS),
    AfterValidator(project_reference),
]


class GitLabProjectVariables(GitLabRequest):
    full_path: ProjectReference = Field(serialization_alias="fullPath")


class GitLabProjectRequest(GitLabRequest):
    query: Literal[GitLabGraphQLDocument.PROJECT_ID] = GitLabGraphQLDocument.PROJECT_ID
    variables: GitLabProjectVariables


class GitLabProjectIdentity(GitLabModel):
    id: Annotated[
        str,
        Field(
            pattern=r"^gid://gitlab/Project/[1-9][0-9]*$",
            max_length=MAX_PROJECT_REFERENCE_CHARS,
        ),
    ]
    full_path: ProjectReference = Field(validation_alias="fullPath")

    @property
    def numeric_id(self) -> int:
        return int(self.id.removeprefix(PROJECT_GLOBAL_ID_PREFIX))


class GitLabProjectData(GitLabModel):
    project: GitLabProjectIdentity | None


class GitLabGraphQLError(GitLabModel):
    message: str = Field(repr=False)


class GitLabProjectResponse(GitLabModel):
    data: GitLabProjectData | None = None
    errors: list[GitLabGraphQLError] | None = None


class GitLabIssueQuery(GitLabRequest):
    per_page: int = Field(ge=1, le=MAX_LIST_LIMIT)
    order_by: Literal["updated_at"] = "updated_at"
    state: GitLabIssueQueryState | None = None
    search: str | None = None
    labels: str | None = None
    assignee_username: list[str] | None = Field(
        default=None, serialization_alias="assignee_username[]"
    )


class GitLabNotesQuery(GitLabRequest):
    per_page: int = Field(default=MAX_NOTES, ge=1, le=MAX_NOTES)
    sort: Literal["asc"] = "asc"


class GitLabMergeRequestQuery(GitLabRequest):
    per_page: int = Field(ge=1, le=MAX_LIST_LIMIT)
    order_by: Literal["updated_at"] = "updated_at"
    state: GitLabMergeRequestQueryState | None = None
    target_branch: str | None = None


class GitLabUserQuery(GitLabRequest):
    username: str = Field(min_length=1)
    per_page: int = Field(default=USER_LOOKUP_LIMIT, ge=1, le=USER_LOOKUP_LIMIT)


class GitLabCreateIssueRequest(GitLabRequest):
    title: str = Field(min_length=1)
    description: str | None = Field(default=None, repr=False)
    labels: str | None = None
    assignee_id: int | None = Field(default=None, ge=1)
    assignee_ids: list[Annotated[int, Field(ge=1)]] | None = Field(
        default=None, min_length=2, max_length=MAX_ASSIGNEE_LOOKUPS
    )

    @model_validator(mode="after")
    def exclusive_assignees(self) -> Self:
        if self.assignee_id is not None and self.assignee_ids is not None:
            raise ValueError("Use one assignee selector, not both.")
        return self


class GitLabNoteRequest(GitLabRequest):
    body: str = Field(min_length=1, repr=False)


class GitLabUser(GitLabModel):
    username: str


class GitLabResolvedUser(GitLabUser):
    id: int = Field(ge=1)


class GitLabMilestone(GitLabModel):
    title: str


class GitLabIssue(GitLabModel):
    iid: int = Field(ge=1)
    project_id: int = Field(ge=1)
    title: str
    state: str
    author: GitLabUser | None
    labels: list[str]
    assignees: list[GitLabUser]
    milestone: GitLabMilestone | None
    due_date: str | None
    created_at: str
    updated_at: str
    closed_at: str | None
    web_url: str
    description: str | None = Field(default=None, repr=False)


class GitLabNote(GitLabModel):
    id: int = Field(ge=1)
    author: GitLabUser | None
    body: str = Field(repr=False)
    created_at: str
    system: bool


class GitLabCreatedNote(GitLabNote):
    project_id: int = Field(ge=1)
    noteable_iid: int = Field(ge=1)
    noteable_type: Literal["Issue"]


class GitLabMergeRequest(GitLabModel):
    iid: int = Field(ge=1)
    project_id: int = Field(ge=1)
    title: str
    state: str
    author: GitLabUser | None
    source_branch: str
    target_branch: str
    draft: bool
    merged_at: str | None
    created_at: str
    updated_at: str
    web_url: str


class GitLabMergeRequestDetail(GitLabMergeRequest):
    description: str | None = Field(repr=False)
    detailed_merge_status: str | None = None
    merge_status: str
    has_conflicts: bool


class GitLabChange(GitLabModel):
    new_path: str
    new_file: bool
    deleted_file: bool
    renamed_file: bool


class GitLabChanges(GitLabModel):
    iid: int = Field(ge=1)
    project_id: int = Field(ge=1)
    changes: list[GitLabChange]


class GitLabErrorEnvelope(GitLabModel):
    # GitLab validation errors can be field-keyed objects, not just strings.
    message: JsonValue = Field(default=None, repr=False)
    error: JsonValue = Field(default=None, repr=False)
    id: int | None = None
    iid: int | None = None


class GitLabCommentView(GitLabModel):
    author: str | None
    body: str | None = Field(repr=False)
    created_at: str


class GitLabIssueView(GitLabModel):
    """Validated builder; requested details are added before JSON serialization."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)
    iid: int
    title: str
    state: str
    author: str | None
    labels: list[str]
    assignees: list[str]
    milestone: str | None
    due_date: str | None
    created_at: str
    updated_at: str
    closed_at: str | None
    web_link: str
    description: str | None = Field(default=None, repr=False)
    comments: list[GitLabCommentView] | None = None


class GitLabIssueListView(GitLabModel):
    project: str
    issues: list[GitLabIssueView]
    count: int


class GitLabCreatedNoteView(GitLabModel):
    id: int
    issue_iid: int
    author: str | None
    created_at: str


class GitLabFileView(GitLabModel):
    path: str
    new_file: bool
    deleted_file: bool
    renamed_file: bool


class GitLabMergeRequestView(GitLabModel):
    """Validated builder; omitted change retrieval is not an empty change set."""

    model_config = ConfigDict(frozen=False, validate_assignment=True)
    iid: int
    title: str
    state: str
    author: str | None
    source_branch: str
    target_branch: str
    draft: bool
    merged: bool
    merged_at: str | None
    created_at: str
    updated_at: str
    web_link: str
    description: str | None = Field(default=None, repr=False)
    merge_status: str | None = None
    has_conflicts: bool | None = None
    files: list[GitLabFileView] | None = None
    changed_files: int | None = None


class GitLabMergeRequestsView(GitLabModel):
    project: str
    merge_requests: list[GitLabMergeRequestView]
    count: int


ISSUE_RESPONSE = TypeAdapter(GitLabIssue)
ISSUES_RESPONSE = TypeAdapter(list[GitLabIssue])
NOTES_RESPONSE = TypeAdapter(list[GitLabNote])
CREATED_NOTE_RESPONSE = TypeAdapter(GitLabCreatedNote)
MERGE_REQUESTS_RESPONSE = TypeAdapter(list[GitLabMergeRequest])
MERGE_REQUEST_RESPONSE = TypeAdapter(GitLabMergeRequestDetail)
CHANGES_RESPONSE = TypeAdapter(GitLabChanges)
USERS_RESPONSE = TypeAdapter(list[GitLabResolvedUser])
PROJECT_RESPONSE = TypeAdapter(GitLabProjectResponse)


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """Keep native diagnostics private; parsing never repeats a write."""
    if not response.ok:
        raise VendorToolError(GitLabErrorCode.REJECTED, "GitLab rejected the request.")
    try:
        if isinstance(response.data, dict):
            envelope = GitLabErrorEnvelope.model_validate(response.data)
            if (
                (envelope.message is not None or envelope.error is not None)
                and envelope.id is None
                and envelope.iid is None
            ):
                raise VendorToolError(
                    GitLabErrorCode.REJECTED, "GitLab rejected the request."
                )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            GitLabErrorCode.RESPONSE_INVALID,
            "GitLab returned an invalid response for this operation.",
        ) from None


def require_identity(
    *, actual_iid: int, requested_iid: int, actual_project_id: int, project: int
) -> None:
    if actual_iid != requested_iid or actual_project_id != project:
        raise VendorToolError(
            GitLabErrorCode.RESPONSE_INVALID, "GitLab returned a different resource."
        )
