"""Curated Jira tools.

`create_issue` is the composition that earns its keep: an agent supplies a
project key and an issue type by name, and the tool resolves both, converts the
description into Atlassian Document Format, and creates the issue. Done through
the raw API requires project/type resolution and an optional user lookup before
the single write. Native responses are validated before result projection.
"""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import READ_JIRA_USER, READ_JIRA_WORK, WRITE_JIRA_WORK, vendor
from .schemas import (
    CREATED_COMMENT_RESPONSE,
    CREATED_ISSUE_RESPONSE,
    DEFAULT_SEARCH_LIMIT,
    ISSUE_RESPONSE,
    MAX_SEARCH_LIMIT,
    PROJECT_RESPONSE,
    SEARCH_FIELDS,
    SEARCH_RESPONSE,
    USERS_RESPONSE,
    JiraAdfDocument,
    JiraAdfNode,
    JiraAdfNodeKind,
    JiraAdfParagraph,
    JiraAdfReadDocument,
    JiraAdfText,
    JiraCommentRequest,
    JiraCreateFields,
    JiraCreateRequest,
    JiraCreatedCommentView,
    JiraCreatedIssueView,
    JiraErrorCode,
    JiraIdReference,
    JiraIssue,
    JiraIssueDetailView,
    JiraIssueView,
    JiraProjectQuery,
    JiraSearchRequest,
    JiraSearchView,
    JiraUserQuery,
    parse_response,
)


class SearchIssuesInput(BaseModel):
    jql: str | None = Field(
        default=None,
        description="Raw JQL. Omit it and use the simple filters below instead.",
    )
    project_key: str | None = Field(
        default=None, description="Project key such as PLT."
    )
    text: str | None = Field(
        default=None, description="Free text matched against summary and description."
    )
    status: str | None = Field(default=None, description="Status name such as 'Done'.")
    assignee_email: str | None = Field(default=None)
    limit: StrictInt = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)


class GetIssueInput(BaseModel):
    issue_key: str = Field(min_length=1, description="Issue key such as PLT-123.")


class CreateIssueInput(BaseModel):
    project_key: str = Field(min_length=1, description="Project key such as PLT.")
    summary: str = Field(min_length=1, description="Issue summary.")
    issue_type: str = Field(
        default="Task",
        description="Issue type name such as Task, Bug, or Story.",
    )
    description: str | None = Field(
        default=None, description="Issue description as plain text."
    )
    assignee_email: str | None = Field(default=None)
    labels: list[str] | None = Field(default=None)


class AddCommentInput(BaseModel):
    issue_key: str = Field(min_length=1, description="Issue key such as PLT-123.")
    body: str = Field(min_length=1, description="Comment text as plain text.")


@curated_tool(
    vendor=vendor.vendor,
    name="search_issues",
    display_name="Search Jira Issues",
    description=(
        "Search Jira issues. Supply raw JQL, or use the simple filters "
        "(project key, free text, status, assignee email) and the JQL is built "
        "for you. Returns issues with status, assignee, and type resolved."
    ),
    input_model=SearchIssuesInput,
    effect=ToolEffect.READ,
    scopes=(READ_JIRA_WORK,),
)
async def search_issues(
    payload: SearchIssuesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    jql = payload.jql.strip() if payload.jql else _build_jql(payload)
    if not jql:
        raise VendorToolError(
            JiraErrorCode.SEARCH_TOO_BROAD,
            "Supply JQL or at least one filter; an unbounded search is refused.",
        )
    response = await ctx.read(
        "/search/jql",
        method="POST",
        json=JiraSearchRequest(
            jql=jql, maxResults=payload.limit, fields=list(SEARCH_FIELDS)
        ).model_dump(mode="json"),
    )
    body = parse_response(response, SEARCH_RESPONSE)
    return JiraSearchView(
        jql=jql,
        issues=[_issue_view(issue) for issue in body.issues],
        count=len(body.issues),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_issue",
    display_name="Get Jira Issue",
    description=(
        "Read one Jira issue by key, including its description as plain text "
        "rather than Atlassian Document Format."
    ),
    input_model=GetIssueInput,
    effect=ToolEffect.READ,
    scopes=(READ_JIRA_WORK,),
)
async def get_issue(
    payload: GetIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.read(f"/issue/{quote(payload.issue_key, safe='')}")
    issue = parse_response(response, ISSUE_RESPONSE)
    return JiraIssueDetailView(
        **_issue_view(issue).model_dump(),
        description=_adf_to_text(issue.fields.description),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_issue",
    display_name="Create Jira Issue",
    description=(
        "Create a Jira issue from a project key and an issue type name. The "
        "project and type are resolved automatically, the description is "
        "converted to Atlassian Document Format, and an assignee email is "
        "looked up if supplied. Assignment requires one exact visible email "
        "match; hidden, missing or ambiguous email refuses creation."
    ),
    input_model=CreateIssueInput,
    effect=ToolEffect.MUTATION,
    scopes=(WRITE_JIRA_WORK, READ_JIRA_WORK, READ_JIRA_USER),
)
async def create_issue(
    payload: CreateIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project_id, type_id = await _resolve_project_and_type(
        ctx, payload.project_key, payload.issue_type
    )
    fields = JiraCreateFields(
        project=JiraIdReference(id=project_id),
        issuetype=JiraIdReference(id=type_id),
        summary=payload.summary,
        description=_text_to_adf(payload.description) if payload.description else None,
        labels=payload.labels or None,
        assignee=(
            JiraIdReference(id=await _resolve_account_id(ctx, payload.assignee_email))
            if payload.assignee_email
            else None
        ),
    )
    response = await ctx.mutate(
        "/issue",
        method="POST",
        json=JiraCreateRequest(fields=fields).model_dump(
            mode="json", exclude_none=True
        ),
    )
    created = parse_response(response, CREATED_ISSUE_RESPONSE)
    return JiraCreatedIssueView(
        key=created.key, id=created.id, summary=payload.summary
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_comment",
    display_name="Comment On Jira Issue",
    description=(
        "Add a comment to a Jira issue. Plain text is converted to Atlassian "
        "Document Format, which the raw API requires."
    ),
    input_model=AddCommentInput,
    effect=ToolEffect.MUTATION,
    scopes=(WRITE_JIRA_WORK,),
)
async def add_comment(
    payload: AddCommentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.mutate(
        f"/issue/{quote(payload.issue_key, safe='')}/comment",
        method="POST",
        json=JiraCommentRequest(body=_text_to_adf(payload.body)).model_dump(
            mode="json", exclude_none=True
        ),
    )
    created = parse_response(response, CREATED_COMMENT_RESPONSE)
    return JiraCreatedCommentView(
        id=created.id, issue_key=payload.issue_key, created=created.created
    ).model_dump(mode="json")


async def _resolve_project_and_type(
    ctx: VendorToolContext, project_key: str, issue_type: str
) -> tuple[str, str]:
    """One call resolves both: Jira returns issue types inside the project."""
    response = await ctx.read(
        f"/project/{quote(project_key.strip().upper(), safe='')}",
        query=JiraProjectQuery().model_dump(mode="json"),
    )
    project = parse_response(response, PROJECT_RESPONSE)
    wanted = issue_type.strip().casefold()
    matches = [entry for entry in project.issueTypes if entry.name.casefold() == wanted]
    if len(matches) == 1:
        return project.id, matches[0].id
    raise VendorToolError(
        JiraErrorCode.ISSUE_TYPE_NOT_FOUND,
        "The project did not return one matching issue type.",
    )


async def _resolve_account_id(ctx: VendorToolContext, email: str) -> str:
    response = await ctx.read(
        "/user/search", query=JiraUserQuery(query=email).model_dump(mode="json")
    )
    users = parse_response(response, USERS_RESPONSE)
    matches = [
        user
        for user in users
        if user.emailAddress
        and user.emailAddress.casefold() == email.strip().casefold()
    ]
    if len(matches) == 1:
        return matches[0].accountId
    raise VendorToolError(
        JiraErrorCode.USER_NOT_FOUND,
        "Jira did not return one user with the exact visible email; no issue was created.",
    )


def _build_jql(payload: SearchIssuesInput) -> str:
    clauses: list[str] = []
    if payload.project_key:
        clauses.append(f'project = "{_jql_value(payload.project_key.strip().upper())}"')
    if payload.status:
        clauses.append(f'status = "{_jql_value(payload.status.strip())}"')
    if payload.assignee_email:
        clauses.append(f'assignee = "{_jql_value(payload.assignee_email.strip())}"')
    if payload.text:
        clauses.append(f'text ~ "{_jql_value(payload.text.strip())}"')
    return " AND ".join(clauses) + (" ORDER BY updated DESC" if clauses else "")


def _jql_value(value: str) -> str:
    """Quote simple-filter data; explicit raw JQL remains an advanced input."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _issue_view(issue: JiraIssue) -> JiraIssueView:
    fields = issue.fields
    return JiraIssueView(
        key=issue.key,
        id=issue.id,
        summary=fields.summary,
        status=fields.status.name if fields.status else None,
        type=fields.issuetype.name if fields.issuetype else None,
        assignee_name=fields.assignee.displayName if fields.assignee else None,
        assignee_email=fields.assignee.emailAddress if fields.assignee else None,
        created=fields.created,
        updated=fields.updated,
    )


def _text_to_adf(text: str) -> JiraAdfDocument:
    """Preserve line boundaries in Jira v3's required rich-text envelope."""
    return JiraAdfDocument(
        content=[
            JiraAdfParagraph(content=[JiraAdfText(text=line)])
            if line
            else JiraAdfParagraph()
            for line in text.split("\n")
        ]
    )


def _adf_to_text(document: JiraAdfReadDocument | str | None) -> str | None:
    """Project text and paragraph breaks; non-text media/attributes are not prose."""
    if document is None or isinstance(document, str):
        return document
    parts: list[str] = []

    def walk(node: JiraAdfNode) -> None:
        if node.type == JiraAdfNodeKind.TEXT and node.text is not None:
            parts.append(node.text)
        for child in node.content:
            walk(child)
        if node.type == JiraAdfNodeKind.PARAGRAPH:
            parts.append("\n")

    for node in document.content:
        walk(node)
    return "".join(parts).strip() or None


__all__ = ["add_comment", "create_issue", "get_issue", "search_issues"]
