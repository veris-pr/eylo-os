"""Curated Sentry tools with typed native responses and confirmed mutations."""

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext
from ...registry import curated_tool
from .definition import EVENT_READ, EVENT_WRITE, PROJECT_READ, vendor
from .schemas import (
    DEFAULT_PAGE_SIZE,
    EVENT_RESPONSE,
    FILTER_QUERIES,
    ISSUES_RESPONSE,
    ISSUE_RESPONSE,
    MAX_BODY_CHARS,
    MAX_FRAMES,
    MAX_PAGE_SIZE,
    ChangeIssueRequest,
    ChangeIssueView,
    ContextPair,
    Cursor,
    Event,
    ExceptionEntry,
    ExceptionValue,
    ExceptionView,
    FrameView,
    Issue,
    IssueDetail,
    IssueFilter,
    IssueId,
    IssueStatus,
    IssueView,
    IssuesQuery,
    IssuesView,
    Slug,
    SourceLine,
    invalid_response,
    next_cursor,
    parse_response,
)


class ListIssuesInput(BaseModel):
    organization: Slug = Field(description="Organization slug.")
    project: Slug = Field(description="Project slug.")
    state: IssueFilter = IssueFilter.UNRESOLVED
    text: str | None = Field(
        default=None, description="Additional native Sentry search terms."
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: Cursor | None = Field(
        default=None,
        description="Use next_cursor with the same project, filters and limit.",
    )

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value


class GetIssueInput(BaseModel):
    issue_id: IssueId
    include_stack_trace: StrictBool = True


class ChangeIssueInput(BaseModel):
    issue_id: IssueId


@curated_tool(
    vendor=vendor.vendor,
    name="list_issues",
    display_name="List Sentry Issues",
    description="List a project's issues, by default unresolved, with event counts, affected users and timestamps. Count is this page; continue with next_cursor and unchanged filters.",
    input_model=ListIssuesInput,
    effect=ToolEffect.READ,
    scopes=(PROJECT_READ, EVENT_READ),
)
async def list_issues(
    payload: ListIssuesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = IssuesQuery(
        query=" ".join(
            term for term in (FILTER_QUERIES[payload.state], payload.text) if term
        ),
        limit=payload.limit,
        cursor=payload.cursor,
    )
    path = f"/projects/{payload.organization}/{payload.project}/issues/"
    response = await ctx.read(
        path, query=query.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    issues = parse_response(response, ISSUES_RESPONSE)
    if len(issues) > payload.limit or any(
        issue.project is not None and issue.project.slug != payload.project
        for issue in issues
    ):
        invalid_response()
    continuation = next_cursor(response, path=path, previous=payload.cursor)
    return IssuesView(
        project=payload.project,
        issues=[_issue_view(issue) for issue in issues],
        count=len(issues),
        next_cursor=continuation,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_issue",
    display_name="Get Sentry Issue",
    description="Read an issue and optionally its latest event. Returns application frames innermost first (or all frames if no application frames), capped at 20, with structured source lines. Reports the most recent exception in the native exception chain that has a stack trace.",
    input_model=GetIssueInput,
    effect=ToolEffect.READ,
    scopes=(EVENT_READ,),
)
async def get_issue(
    payload: GetIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    # Existing ID-only tools retain Sentry's served legacy routes. New organization-
    # scoped routes require a deliberate public-input migration, not a guessed org.
    issue = parse_response(
        await ctx.read(f"/issues/{payload.issue_id}/"), ISSUE_RESPONSE
    )
    if issue.id != payload.issue_id:
        invalid_response()
    view = _issue_view(issue)
    if not payload.include_stack_trace:
        return view.model_dump(mode="json")
    event = parse_response(
        await ctx.read(f"/issues/{issue.id}/events/latest/"), EVENT_RESPONSE
    )
    if event.group_id != issue.id:
        invalid_response()
    exception = _exception(event)
    return IssueDetail(
        **view.model_dump(),
        last_event_at=event.date_created,
        stack_trace=_frames(exception),
        exception=ExceptionView(type=exception.type, value=_clip(exception.value))
        if exception is not None
        else None,
        tags={tag.key: tag.value for tag in event.tags},
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="resolve_issue",
    display_name="Resolve Sentry Issue",
    description="Mark an issue resolved when its underlying bug is believed fixed. Confirms the returned issue ID and status; does not guarantee future regression or notification behavior. Use ignore_issue to silence without claiming a fix.",
    input_model=ChangeIssueInput,
    effect=ToolEffect.MUTATION,
    scopes=(EVENT_WRITE,),
)
async def resolve_issue(
    payload: ChangeIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    return await _change_issue(payload, ctx, IssueStatus.RESOLVED)


@curated_tool(
    vendor=vendor.vendor,
    name="ignore_issue",
    display_name="Ignore Sentry Issue",
    description="Mark an issue ignored without claiming its bug is fixed. Confirms the returned issue ID and status. Notification and future escalation behavior remain controlled by Sentry.",
    input_model=ChangeIssueInput,
    effect=ToolEffect.MUTATION,
    scopes=(EVENT_WRITE,),
)
async def ignore_issue(
    payload: ChangeIssueInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    return await _change_issue(payload, ctx, IssueStatus.IGNORED)


async def _change_issue(
    payload: ChangeIssueInput, ctx: VendorToolContext, status: IssueStatus
) -> dict[str, JsonValue]:
    request = ChangeIssueRequest(status=status)
    issue = parse_response(
        await ctx.mutate(
            f"/issues/{payload.issue_id}/",
            method="PUT",
            json=request.model_dump(mode="json"),
        ),
        ISSUE_RESPONSE,
    )
    if issue.id != payload.issue_id or issue.status != status:
        invalid_response()
    return ChangeIssueView(
        issue_id=issue.id, status=issue.status, web_link=issue.permalink
    ).model_dump(mode="json")


def _exception(event: Event) -> ExceptionValue | None:
    values = [
        value
        for entry in event.entries
        if isinstance(entry, ExceptionEntry)
        for value in entry.data.values
    ]
    for value in reversed(values):
        if value.stacktrace is not None and value.stacktrace.frames:
            return value
    return values[-1] if values else None


def _frames(exception: ExceptionValue | None) -> list[FrameView]:
    if exception is None or exception.stacktrace is None:
        return []
    frames = list(reversed(exception.stacktrace.frames))
    application_frames = [frame for frame in frames if frame.in_app is True]
    return [
        FrameView(
            function=frame.function,
            file=frame.filename,
            line=frame.line_no,
            in_app=frame.in_app,
            context=_source_context(frame.context),
        )
        for frame in (application_frames or frames)[:MAX_FRAMES]
    ]


def _source_context(context: list[ContextPair] | None) -> list[SourceLine] | None:
    if context is None:
        return None
    result: list[SourceLine] = []
    remaining = MAX_BODY_CHARS
    for line, text in context:
        if remaining == 0:
            break
        excerpt = text[:remaining]
        result.append(SourceLine(line=line, text=excerpt))
        remaining -= len(excerpt)
    return result


def _issue_view(issue: Issue) -> IssueView:
    return IssueView(
        id=issue.id,
        title=issue.title,
        culprit=issue.culprit,
        type=issue.metadata.type,
        value=_clip(issue.metadata.value),
        status=issue.status,
        level=issue.level,
        event_count=issue.count,
        users_affected=issue.user_count,
        first_seen=issue.first_seen,
        last_seen=issue.last_seen,
        web_link=issue.permalink,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None
