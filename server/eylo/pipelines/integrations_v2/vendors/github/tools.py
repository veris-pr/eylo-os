"""Curated GitHub tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import REPO, vendor
from .schemas import (
    COMMENTS_RESPONSE,
    COMMENT_RESPONSE,
    DEFAULT_LIST_LIMIT,
    FILES_RESPONSE,
    ISSUE_RESPONSE,
    ISSUE_SEARCH_RESPONSE,
    LEGACY_BASE_BRANCH,
    MAX_BODY_CHARS,
    MAX_COMMENTS,
    MAX_FILES,
    MAX_LIST_LIMIT,
    PULLS_RESPONSE,
    PULL_DETAIL_RESPONSE,
    PULL_RESPONSE,
    REVIEWS_RESPONSE,
    SEARCH_PATH,
    GitHubComment,
    GitHubCommentRequest,
    GitHubCommentView,
    GitHubCreateIssueRequest,
    GitHubCreatePullRequest,
    GitHubIssue,
    GitHubIssueView,
    GitHubPageQuery,
    GitHubPull,
    GitHubPullView,
    GitHubPullsQuery,
    GitHubPullsResult,
    GitHubQueryState,
    GitHubReviewState,
    GitHubReviewView,
    GitHubSearchQuery,
    GitHubSearchResult,
    GitHubToolErrorCode,
    parse_response,
    require_number,
)


class SearchIssuesInput(BaseModel):
    repository: str = Field(
        default="",
        description="Repository as owner/name. Omit to search everything visible.",
    )
    text: str | None = Field(default=None, description="Free text to match.")
    state: GitHubQueryState = Field(
        default=GitHubQueryState.OPEN,
        description="Issue state to search; all omits the state filter.",
    )
    labels: list[str] | None = Field(default=None, description="All must be present.")
    assignee: str | None = Field(default=None, description="GitHub username.")
    author: str | None = Field(default=None, description="GitHub username.")
    include_pull_requests: StrictBool = Field(
        default=False,
        description="GitHub counts pull requests as issues; this keeps them out.",
    )
    limit: StrictInt = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class GetIssueInput(BaseModel):
    repository: str = Field(min_length=1, description="Repository as owner/name.")
    number: StrictInt = Field(ge=1, description="Issue number as shown in its URL.")
    include_comments: StrictBool = Field(default=True)


class CreateIssueInput(BaseModel):
    repository: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str | None = Field(default=None, description="Markdown description.")
    labels: list[str] | None = None
    assignees: list[str] | None = Field(default=None, description="GitHub usernames.")


class AddCommentInput(BaseModel):
    repository: str = Field(min_length=1)
    number: StrictInt = Field(ge=1, description="Issue or pull request number.")
    body: str = Field(min_length=1, description="Markdown comment.")


class ListPullRequestsInput(BaseModel):
    repository: str = Field(min_length=1)
    state: GitHubQueryState = Field(
        default=GitHubQueryState.OPEN, description="Pull request state to list."
    )
    base_branch: str | None = Field(
        default=None, description="Only requests targeting this branch."
    )
    limit: StrictInt = Field(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT)


class GetPullRequestInput(BaseModel):
    repository: str = Field(min_length=1)
    number: StrictInt = Field(ge=1)
    include_files: StrictBool = Field(default=True)
    include_reviews: StrictBool = Field(default=True)


class CreatePullRequestInput(BaseModel):
    repository: str = Field(min_length=1)
    title: str = Field(min_length=1)
    head_branch: str = Field(min_length=1, description="Branch holding the changes.")
    base_branch: str = Field(
        default=LEGACY_BASE_BRANCH, description="Branch to merge into."
    )
    body: str | None = None
    draft: StrictBool = Field(default=False)


@curated_tool(
    vendor=vendor.vendor,
    name="search_issues",
    display_name="Search GitHub Issues",
    description=(
        "Find issues by repository, state, label, assignee, author, or free "
        "text, without writing GitHub's search syntax. Pull requests are "
        "excluded unless asked for, since GitHub otherwise returns them mixed "
        "in with issues."
    ),
    input_model=SearchIssuesInput,
    effect=ToolEffect.READ,
    scopes=(REPO,),
)
async def search_issues(
    payload: SearchIssuesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    terms: list[str] = []
    if payload.repository:
        terms.append(f"repo:{_repository(payload.repository)}")
    if not payload.include_pull_requests:
        terms.append("is:issue")
    if payload.state is not GitHubQueryState.ALL:
        terms.append(f"state:{payload.state.value}")
    for label in payload.labels or []:
        terms.append(f'label:"{label}"')
    if payload.assignee:
        terms.append(f"assignee:{payload.assignee}")
    if payload.author:
        terms.append(f"author:{payload.author}")
    if payload.text:
        terms.append(payload.text)
    if not terms:
        raise VendorToolError(
            GitHubToolErrorCode.SEARCH_UNBOUNDED,
            "Give at least a repository or some text to search for.",
        )

    query = " ".join(terms)
    response = await ctx.read(
        SEARCH_PATH,
        query=GitHubSearchQuery(q=query, per_page=payload.limit).model_dump(
            mode="json"
        ),
    )
    body = parse_response(response, ISSUE_SEARCH_RESPONSE)
    return GitHubSearchResult(
        issues=[_issue_view(item) for item in body.items],
        count=len(body.items),
        total_matches=body.total_count,
        query=query,
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_issue",
    display_name="Get GitHub Issue",
    description=(
        "Read one issue with up to the first 20 comments. Bodies are clipped "
        "to 6000 characters. Labels, assignees, and state are included."
    ),
    input_model=GetIssueInput,
    effect=ToolEffect.READ,
    scopes=(REPO,),
)
async def get_issue(
    payload: GetIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    issue = parse_response(
        await ctx.read(f"/repos/{repository}/issues/{payload.number}"), ISSUE_RESPONSE
    )
    require_number(issue.number, payload.number)
    view = _issue_view(issue)
    view.body = _clip(issue.body)
    if payload.include_comments:
        response = await ctx.read(
            f"/repos/{repository}/issues/{payload.number}/comments",
            query=GitHubPageQuery(per_page=MAX_COMMENTS).model_dump(mode="json"),
        )
        view.comments = [
            _comment_view(item) for item in parse_response(response, COMMENTS_RESPONSE)
        ]
    return view.model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_issue",
    display_name="Create GitHub Issue",
    description=(
        "Open an issue with a title, markdown body, labels, and assignees. "
        "Returns the new issue's number and web link."
    ),
    input_model=CreateIssueInput,
    effect=ToolEffect.MUTATION,
    scopes=(REPO,),
)
async def create_issue(
    payload: CreateIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    body = GitHubCreateIssueRequest(
        title=payload.title,
        body=payload.body or None,
        labels=payload.labels or None,
        assignees=payload.assignees or None,
    )
    response = await ctx.mutate(
        f"/repos/{repository}/issues",
        json=body.model_dump(mode="json", exclude_none=True),
    )
    return _issue_view(parse_response(response, ISSUE_RESPONSE)).model_dump(
        mode="json", exclude_unset=True
    )


@curated_tool(
    vendor=vendor.vendor,
    name="add_comment",
    display_name="Comment on GitHub Issue",
    description=(
        "Add a markdown comment to an issue or pull request. GitHub numbers "
        "both in one sequence, so the same tool serves either."
    ),
    input_model=AddCommentInput,
    effect=ToolEffect.MUTATION,
    scopes=(REPO,),
)
async def add_comment(
    payload: AddCommentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    response = await ctx.mutate(
        f"/repos/{repository}/issues/{payload.number}/comments",
        json=GitHubCommentRequest(body=payload.body).model_dump(mode="json"),
    )
    return _comment_view(parse_response(response, COMMENT_RESPONSE)).model_dump(
        mode="json"
    )


@curated_tool(
    vendor=vendor.vendor,
    name="list_pull_requests",
    display_name="List GitHub Pull Requests",
    description=(
        "List a repository's pull requests, optionally narrowed to those "
        "targeting one branch. Each entry reports its branches, draft state, "
        "and whether it has merged."
    ),
    input_model=ListPullRequestsInput,
    effect=ToolEffect.READ,
    scopes=(REPO,),
)
async def list_pull_requests(
    payload: ListPullRequestsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    query = GitHubPullsQuery(
        state=payload.state, per_page=payload.limit, base=payload.base_branch or None
    )
    response = await ctx.read(
        f"/repos/{repository}/pulls",
        query=query.model_dump(mode="json", exclude_none=True),
    )
    items = parse_response(response, PULLS_RESPONSE)
    return GitHubPullsResult(
        repository=repository,
        pull_requests=[_pull_view(item) for item in items],
        count=len(items),
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="get_pull_request",
    display_name="Get GitHub Pull Request",
    description=(
        "Read a pull request with up to the first 50 changed files and first "
        "20 reviews. Its body is clipped to 6000 characters. The approved "
        "flag means an approval occurs in that page, not that current branch "
        "protection or merge requirements are satisfied."
    ),
    input_model=GetPullRequestInput,
    effect=ToolEffect.READ,
    scopes=(REPO,),
)
async def get_pull_request(
    payload: GetPullRequestInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    pull = parse_response(
        await ctx.read(f"/repos/{repository}/pulls/{payload.number}"),
        PULL_DETAIL_RESPONSE,
    )
    require_number(pull.number, payload.number)
    view = _pull_view(pull)
    view.body = _clip(pull.body)
    view.additions = pull.additions
    view.deletions = pull.deletions
    view.changed_files = pull.changed_files
    view.mergeable = pull.mergeable

    if payload.include_files:
        response = await ctx.read(
            f"/repos/{repository}/pulls/{payload.number}/files",
            query=GitHubPageQuery(per_page=MAX_FILES).model_dump(mode="json"),
        )
        files = parse_response(response, FILES_RESPONSE)
        view.files = files
    if payload.include_reviews:
        response = await ctx.read(
            f"/repos/{repository}/pulls/{payload.number}/reviews",
            query=GitHubPageQuery(per_page=MAX_COMMENTS).model_dump(mode="json"),
        )
        reviews = parse_response(response, REVIEWS_RESPONSE)
        view.reviews = [
            GitHubReviewView(
                reviewer=item.user.login if item.user else None,
                state=item.state,
                submitted_at=item.submitted_at,
            )
            for item in reviews
        ]
        view.approved = any(
            item.state.upper() == GitHubReviewState.APPROVED for item in reviews
        )
    return view.model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_pull_request",
    display_name="Create GitHub Pull Request",
    description=(
        "Open a pull request from one branch into another. Both branches must "
        "already exist. Returns the new pull request's number and web link."
    ),
    input_model=CreatePullRequestInput,
    effect=ToolEffect.MUTATION,
    scopes=(REPO,),
)
async def create_pull_request(
    payload: CreatePullRequestInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    repository = _repository(payload.repository)
    body = GitHubCreatePullRequest(
        title=payload.title,
        head=payload.head_branch,
        base=payload.base_branch,
        draft=payload.draft,
        body=payload.body or None,
    )
    response = await ctx.mutate(
        f"/repos/{repository}/pulls",
        json=body.model_dump(mode="json", exclude_none=True),
    )
    return _pull_view(parse_response(response, PULL_RESPONSE)).model_dump(
        mode="json", exclude_unset=True
    )


def _repository(value: str) -> str:
    """Accept owner/name and pasted repository URLs; the HTTP layer pins origin."""
    candidate = value.strip().strip("/")
    if candidate.startswith("https://"):
        parts = [part for part in candidate.split("/") if part]
        candidate = "/".join(parts[-2:]) if len(parts) >= 2 else ""
    pieces = candidate.split("/")
    if len(pieces) != 2 or not all(piece.strip() for piece in pieces):
        raise VendorToolError(
            GitHubToolErrorCode.REPOSITORY_INVALID,
            "Use a repository as owner/name, e.g. acme/api.",
        )
    return f"{pieces[0]}/{pieces[1]}"


def _issue_view(issue: GitHubIssue) -> GitHubIssueView:
    return GitHubIssueView(
        number=issue.number,
        title=issue.title,
        state=issue.state,
        author=issue.user.login if issue.user else None,
        labels=[
            label if isinstance(label, str) else label.name for label in issue.labels
        ],
        assignees=[assignee.login for assignee in issue.assignees or []],
        comment_count=issue.comments,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        closed_at=issue.closed_at,
        web_link=issue.html_url,
        is_pull_request="pull_request" in issue.model_fields_set,
    )


def _pull_view(pull: GitHubPull) -> GitHubPullView:
    return GitHubPullView(
        number=pull.number,
        title=pull.title,
        state=pull.state,
        author=pull.user.login if pull.user else None,
        head_branch=pull.head.ref,
        base_branch=pull.base.ref,
        draft=pull.draft,
        merged=pull.merged_at is not None,
        merged_at=pull.merged_at,
        created_at=pull.created_at,
        updated_at=pull.updated_at,
        web_link=pull.html_url,
    )


def _comment_view(comment: GitHubComment) -> GitHubCommentView:
    return GitHubCommentView(
        id=comment.id,
        author=comment.user.login if comment.user else None,
        body=_clip(comment.body),
        created_at=comment.created_at,
        web_link=comment.html_url,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


__all__ = [
    "add_comment",
    "create_issue",
    "create_pull_request",
    "get_issue",
    "get_pull_request",
    "list_pull_requests",
    "search_issues",
]
