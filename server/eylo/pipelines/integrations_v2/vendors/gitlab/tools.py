"""Compose GitLab v4 issues, bounded notes and merge-request change summaries.

Project paths require encoded slashes; the shared transport currently refuses
those paths, so named-project live acceptance remains open. Numeric IDs use the
same typed flow. Merge status is not an approval or merge-permission decision.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StringConstraints,
)

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    CHANGES_RESPONSE,
    CREATED_NOTE_RESPONSE,
    DEFAULT_LIST_LIMIT,
    ISSUES_RESPONSE,
    ISSUE_RESPONSE,
    MAX_ASSIGNEE_LOOKUPS,
    MAX_BODY_CHARS,
    MAX_LIST_LIMIT,
    MERGE_REQUESTS_RESPONSE,
    MERGE_REQUEST_RESPONSE,
    NOTES_RESPONSE,
    USERS_PATH,
    USERS_RESPONSE,
    GitLabCommentView,
    GitLabCreateIssueRequest,
    GitLabCreatedNoteView,
    GitLabErrorCode,
    GitLabFileView,
    GitLabIssue,
    GitLabIssueListView,
    GitLabIssueQuery,
    GitLabIssueQueryState,
    GitLabIssueView,
    GitLabMergeRequest,
    GitLabMergeRequestQuery,
    GitLabMergeRequestQueryState,
    GitLabMergeRequestView,
    GitLabMergeRequestsView,
    GitLabNoteRequest,
    GitLabNotesQuery,
    GitLabUserQuery,
    parse_response,
    require_identity,
)

GitLabUsername = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SearchIssuesInput(BaseModel):
    project: str = Field(
        min_length=1, description="Project path such as acme/api, or its numeric id."
    )
    text: str | None = Field(default=None, description="Free text to match.")
    state: GitLabIssueQueryState = Field(
        default=GitLabIssueQueryState.OPENED,
        description="Issue state to search; all omits the state filter.",
    )
    labels: list[str] | None = None
    assignee_username: str | None = None
    limit: StrictInt = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class GetIssueInput(BaseModel):
    project: str = Field(min_length=1)
    issue_iid: StrictInt = Field(
        ge=1, description="Issue number as shown in the project."
    )
    include_comments: StrictBool = Field(default=True)


class CreateIssueInput(BaseModel):
    project: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = Field(default=None, description="Markdown body.")
    labels: list[str] | None = None
    assignee_usernames: list[GitLabUsername] | None = Field(
        default=None,
        max_length=MAX_ASSIGNEE_LOOKUPS,
        description="Up to 20 usernames, resolved before creation. Every username must resolve uniquely.",
    )


class AddCommentInput(BaseModel):
    project: str = Field(min_length=1)
    issue_iid: StrictInt = Field(ge=1)
    body: str = Field(min_length=1, description="Markdown comment.")


class ListMergeRequestsInput(BaseModel):
    project: str = Field(min_length=1)
    state: GitLabMergeRequestQueryState = Field(
        default=GitLabMergeRequestQueryState.OPENED,
        description="Merge request state to list; all omits the state filter.",
    )
    target_branch: str | None = None
    limit: StrictInt = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class GetMergeRequestInput(BaseModel):
    project: str = Field(min_length=1)
    merge_request_iid: StrictInt = Field(ge=1)
    include_changes: StrictBool = Field(default=True)


@curated_tool(
    vendor=vendor.vendor,
    name="search_issues",
    display_name="Search GitLab Issues",
    description=(
        "Find issues in a project by state, label, assignee, or free text. The "
        "project is named the way it appears in its URL — acme/api — and the "
        "encoding GitLab requires is handled here."
    ),
    input_model=SearchIssuesInput,
    effect=ToolEffect.READ,
)
async def search_issues(
    payload: SearchIssuesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = GitLabIssueQuery(
        per_page=payload.limit,
        state=payload.state if payload.state is not GitLabIssueQueryState.ALL else None,
        search=payload.text or None,
        labels=",".join(payload.labels) if payload.labels else None,
        assignee_username=[payload.assignee_username]
        if payload.assignee_username
        else None,
    )
    response = await ctx.read(
        f"/projects/{_project(payload.project)}/issues",
        query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
    issues = parse_response(response, ISSUES_RESPONSE)
    return GitLabIssueListView(
        project=payload.project,
        issues=[_issue_view(issue) for issue in issues],
        count=len(issues),
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_issue",
    display_name="Get GitLab Issue",
    description=(
        "Read one issue with human comments from its first 20 notes, ordered "
        "oldest first. System activity is excluded. Bodies are clipped to "
        "6000 characters; this is not a complete discussion export."
    ),
    input_model=GetIssueInput,
    effect=ToolEffect.READ,
)
async def get_issue(
    payload: GetIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = _project(payload.project)
    issue = parse_response(
        await ctx.read(f"/projects/{project}/issues/{payload.issue_iid}"),
        ISSUE_RESPONSE,
    )
    require_identity(
        actual_iid=issue.iid,
        requested_iid=payload.issue_iid,
        actual_project_id=issue.project_id,
        project=project,
    )
    view = _issue_view(issue)
    view.description = _clip(issue.description)
    if payload.include_comments:
        notes = await ctx.read(
            f"/projects/{project}/issues/{payload.issue_iid}/notes",
            query=GitLabNotesQuery().model_dump(mode="json"),
        )
        view.comments = [
            GitLabCommentView(
                author=note.author.username if note.author else None,
                body=_clip(note.body),
                created_at=note.created_at,
            )
            for note in parse_response(notes, NOTES_RESPONSE)
            if not note.system
        ]
    return view.model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_issue",
    display_name="Create GitLab Issue",
    description=(
        "Open an issue with a title, markdown description, labels, and "
        "assignees given by username. Resolves up to 20 usernames before the "
        "write; unresolved or ambiguous usernames refuse creation. Multiple "
        "assignees depend on the GitLab tier. Returns the issue's project-scoped "
        "number and web link."
    ),
    input_model=CreateIssueInput,
    effect=ToolEffect.MUTATION,
)
async def create_issue(
    payload: CreateIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = _project(payload.project)
    assignee_ids = await _resolve_assignees(payload.assignee_usernames or [], ctx)
    body = GitLabCreateIssueRequest(
        title=payload.title,
        description=payload.description or None,
        labels=",".join(payload.labels) if payload.labels else None,
        assignee_id=assignee_ids[0] if len(assignee_ids) == 1 else None,
        assignee_ids=assignee_ids if len(assignee_ids) > 1 else None,
    )
    response = await ctx.mutate(
        f"/projects/{project}/issues",
        json=body.model_dump(mode="json", exclude_none=True),
    )
    return _issue_view(parse_response(response, ISSUE_RESPONSE)).model_dump(
        mode="json", exclude_unset=True
    )


@curated_tool(
    vendor=vendor.vendor,
    name="add_comment",
    display_name="Comment on GitLab Issue",
    description="Add a markdown comment to an issue. Notification delivery depends on GitLab settings.",
    input_model=AddCommentInput,
    effect=ToolEffect.MUTATION,
)
async def add_comment(
    payload: AddCommentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = _project(payload.project)
    response = await ctx.mutate(
        f"/projects/{project}/issues/{payload.issue_iid}/notes",
        json=GitLabNoteRequest(body=payload.body).model_dump(mode="json"),
    )
    note = parse_response(response, CREATED_NOTE_RESPONSE)
    require_identity(
        actual_iid=note.noteable_iid,
        requested_iid=payload.issue_iid,
        actual_project_id=note.project_id,
        project=project,
    )
    return GitLabCreatedNoteView(
        id=note.id,
        issue_iid=note.noteable_iid,
        author=note.author.username if note.author else None,
        created_at=note.created_at,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_merge_requests",
    display_name="List GitLab Merge Requests",
    description=(
        "List a project's merge requests, optionally narrowed to those "
        "targeting one branch. Each entry reports its branches, draft state, "
        "and whether it has merged."
    ),
    input_model=ListMergeRequestsInput,
    effect=ToolEffect.READ,
)
async def list_merge_requests(
    payload: ListMergeRequestsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = GitLabMergeRequestQuery(
        per_page=payload.limit,
        state=payload.state
        if payload.state is not GitLabMergeRequestQueryState.ALL
        else None,
        target_branch=payload.target_branch or None,
    )
    response = await ctx.read(
        f"/projects/{_project(payload.project)}/merge_requests",
        query=query.model_dump(mode="json", exclude_none=True),
    )
    requests = parse_response(response, MERGE_REQUESTS_RESPONSE)
    return GitLabMergeRequestsView(
        project=payload.project,
        merge_requests=[_merge_request_view(item) for item in requests],
        count=len(requests),
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_merge_request",
    display_name="Get GitLab Merge Request",
    description=(
        "Read a merge request together with the files it changes and whether "
        "it can merge cleanly. GitLab splits the summary and the diff across "
        "two endpoints; both are fetched here."
    ),
    input_model=GetMergeRequestInput,
    effect=ToolEffect.READ,
)
async def get_merge_request(
    payload: GetMergeRequestInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = _project(payload.project)
    request = parse_response(
        await ctx.read(
            f"/projects/{project}/merge_requests/{payload.merge_request_iid}"
        ),
        MERGE_REQUEST_RESPONSE,
    )
    require_identity(
        actual_iid=request.iid,
        requested_iid=payload.merge_request_iid,
        actual_project_id=request.project_id,
        project=project,
    )
    view = _merge_request_view(request)
    view.description = _clip(request.description)
    view.merge_status = request.detailed_merge_status or request.merge_status
    view.has_conflicts = request.has_conflicts

    if payload.include_changes:
        changes = parse_response(
            await ctx.read(
                f"/projects/{project}/merge_requests/{payload.merge_request_iid}/changes"
            ),
            CHANGES_RESPONSE,
        )
        require_identity(
            actual_iid=changes.iid,
            requested_iid=payload.merge_request_iid,
            actual_project_id=changes.project_id,
            project=project,
        )
        view.files = [
            GitLabFileView(
                path=item.new_path,
                new_file=item.new_file,
                deleted_file=item.deleted_file,
                renamed_file=item.renamed_file,
            )
            for item in changes.changes
        ]
        view.changed_files = len(changes.changes)
    return view.model_dump(mode="json", exclude_unset=True)


def _project(value: str) -> str:
    """Encode one project segment; the shared transport still owns path policy."""
    candidate = value.strip().strip("/")
    if candidate.startswith("https://"):
        parts = [part for part in candidate.split("/") if part]
        candidate = "/".join(parts[2:]) if len(parts) > 2 else ""
    if not candidate:
        raise VendorToolError(
            GitLabErrorCode.PROJECT_INVALID,
            "Use a GitLab project as group/name or numeric ID.",
        )
    if candidate.isdigit():
        return candidate
    return quote(candidate, safe="")


async def _resolve_assignees(usernames: list[str], ctx: VendorToolContext) -> list[int]:
    """Resolve every unique username before creation; never send partial assignments."""
    resolved: list[int] = []
    seen: set[str] = set()
    for username in usernames:
        normalized = username.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        response = await ctx.read(
            USERS_PATH, query=GitLabUserQuery(username=username).model_dump(mode="json")
        )
        users = parse_response(response, USERS_RESPONSE)
        if len(users) != 1 or users[0].username.casefold() != normalized:
            raise VendorToolError(
                GitLabErrorCode.ASSIGNEE_UNRESOLVED,
                "An assignee username did not resolve uniquely; no issue was created.",
            )
        resolved.append(users[0].id)
    return resolved


def _issue_view(issue: GitLabIssue) -> GitLabIssueView:
    return GitLabIssueView(
        iid=issue.iid,
        title=issue.title,
        state=issue.state,
        author=issue.author.username if issue.author else None,
        labels=issue.labels,
        assignees=[a.username for a in issue.assignees],
        milestone=issue.milestone.title if issue.milestone else None,
        due_date=issue.due_date,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        closed_at=issue.closed_at,
        web_link=issue.web_url,
    )


def _merge_request_view(request: GitLabMergeRequest) -> GitLabMergeRequestView:
    return GitLabMergeRequestView(
        iid=request.iid,
        title=request.title,
        state=request.state,
        author=request.author.username if request.author else None,
        source_branch=request.source_branch,
        target_branch=request.target_branch,
        draft=request.draft,
        merged=request.state == GitLabMergeRequestQueryState.MERGED,
        merged_at=request.merged_at,
        created_at=request.created_at,
        updated_at=request.updated_at,
        web_link=request.web_url,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


__all__ = [
    "add_comment",
    "create_issue",
    "get_issue",
    "get_merge_request",
    "list_merge_requests",
    "search_issues",
]
