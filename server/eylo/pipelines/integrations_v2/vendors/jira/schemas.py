"""Consumed Jira Cloud v3 wire contracts and agent-facing projections.

Native custom fields remain outside the selected view. Unknown ADF node kinds
retain their child/text structure; this is a text projection, not an ADF editor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

DEFAULT_SEARCH_LIMIT = 25
MAX_SEARCH_LIMIT = 100
SEARCH_FIELDS = ("summary", "status", "assignee", "issuetype", "created", "updated")


class JiraErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SEARCH_TOO_BROAD = "search_too_broad"
    ISSUE_TYPE_NOT_FOUND = "issue_type_not_found"
    USER_NOT_FOUND = "user_not_found"


class JiraAdfNodeKind(StrEnum):
    TEXT = "text"
    PARAGRAPH = "paragraph"


class JiraModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class JiraRequest(JiraModel):
    model_config = ConfigDict(extra="forbid")


class JiraSearchRequest(JiraRequest):
    jql: str = Field(min_length=1, repr=False)
    maxResults: int = Field(ge=1, le=MAX_SEARCH_LIMIT)
    fields: list[str]


class JiraProjectQuery(JiraRequest):
    expand: Literal["issueTypes"] = "issueTypes"


class JiraUserQuery(JiraRequest):
    query: str = Field(min_length=1, repr=False)


class JiraAdfText(JiraRequest):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, repr=False)


class JiraAdfParagraph(JiraRequest):
    type: Literal["paragraph"] = "paragraph"
    content: list[JiraAdfText] | None = Field(default=None, repr=False)


class JiraAdfDocument(JiraRequest):
    type: Literal["doc"] = "doc"
    version: Literal[1] = 1
    content: list[JiraAdfParagraph] = Field(repr=False)


class JiraAdfNode(JiraModel):
    type: str = Field(min_length=1)
    text: str | None = Field(default=None, repr=False)
    content: list[JiraAdfNode] = Field(default_factory=list, repr=False)

    @model_validator(mode="after")
    def require_text(self) -> Self:
        if self.type == JiraAdfNodeKind.TEXT and not self.text:
            raise ValueError("An ADF text node requires non-empty text.")
        return self


class JiraAdfReadDocument(JiraModel):
    type: Literal["doc"]
    version: Literal[1]
    content: list[JiraAdfNode] = Field(repr=False)


class JiraIdReference(JiraRequest):
    id: str = Field(min_length=1)


class JiraCreateFields(JiraRequest):
    project: JiraIdReference
    issuetype: JiraIdReference
    summary: str = Field(min_length=1, repr=False)
    description: JiraAdfDocument | None = Field(default=None, repr=False)
    labels: list[str] | None = None
    assignee: JiraIdReference | None = None


class JiraCreateRequest(JiraRequest):
    fields: JiraCreateFields


class JiraCommentRequest(JiraRequest):
    body: JiraAdfDocument = Field(repr=False)


class JiraNamedValue(JiraModel):
    name: str | None = None


class JiraUser(JiraModel):
    displayName: str | None = None
    emailAddress: str | None = Field(default=None, repr=False)


class JiraResolvedUser(JiraUser):
    accountId: str = Field(min_length=1)


class JiraIssueFields(JiraModel):
    # Visibility and field selection can omit fields independently of identity.
    summary: str | None = Field(default=None, repr=False)
    status: JiraNamedValue | None = None
    assignee: JiraUser | None = None
    issuetype: JiraNamedValue | None = None
    created: str | None = None
    # Jira's published IssueBean examples also contain integer updated values.
    # Preserve that representation; do not guess a timestamp unit or timezone.
    updated: str | int | None = None
    description: JiraAdfReadDocument | str | None = Field(default=None, repr=False)


class JiraIssue(JiraModel):
    id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    fields: JiraIssueFields


class JiraSearchResponse(JiraModel):
    issues: list[JiraIssue]
    isLast: bool | None = None
    nextPageToken: str | None = Field(default=None, repr=False)


class JiraIssueType(JiraModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class JiraProject(JiraModel):
    id: str = Field(min_length=1)
    issueTypes: list[JiraIssueType]


class JiraCreatedIssue(JiraModel):
    id: str = Field(min_length=1)
    key: str = Field(min_length=1)


class JiraCreatedComment(JiraModel):
    id: str = Field(min_length=1)
    created: str


class JiraErrorEnvelope(JiraModel):
    errorMessages: list[str] = Field(default_factory=list, repr=False)
    errors: dict[str, str] = Field(default_factory=dict, repr=False)


class JiraIssueView(JiraModel):
    key: str
    id: str
    summary: str | None = Field(repr=False)
    status: str | None
    type: str | None
    assignee_name: str | None
    assignee_email: str | None = Field(repr=False)
    created: str | None
    updated: str | int | None


class JiraIssueDetailView(JiraIssueView):
    description: str | None = Field(repr=False)


class JiraSearchView(JiraModel):
    jql: str = Field(repr=False)
    issues: list[JiraIssueView]
    count: int


class JiraCreatedIssueView(JiraModel):
    key: str
    id: str
    summary: str = Field(repr=False)


class JiraCreatedCommentView(JiraModel):
    id: str
    issue_key: str
    created: str


ISSUE_RESPONSE = TypeAdapter(JiraIssue)
SEARCH_RESPONSE = TypeAdapter(JiraSearchResponse)
PROJECT_RESPONSE = TypeAdapter(JiraProject)
USERS_RESPONSE = TypeAdapter(list[JiraResolvedUser])
CREATED_ISSUE_RESPONSE = TypeAdapter(JiraCreatedIssue)
CREATED_COMMENT_RESPONSE = TypeAdapter(JiraCreatedComment)


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """Validate once; an invalid post-write reply never authorizes another send."""
    if not response.ok:
        raise VendorToolError(JiraErrorCode.REJECTED, "Jira rejected the request.")
    try:
        if isinstance(response.data, dict):
            error = JiraErrorEnvelope.model_validate(response.data)
            if error.errorMessages or error.errors:
                raise VendorToolError(
                    JiraErrorCode.REJECTED, "Jira rejected the request."
                )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            JiraErrorCode.RESPONSE_INVALID,
            "Jira returned an invalid operation response.",
        ) from None
