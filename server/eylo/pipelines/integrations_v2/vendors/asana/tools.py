"""Curated Asana tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    CREATED_STORY_RESPONSE,
    DEFAULT_PROJECT_LIMIT,
    DEFAULT_TASK_LIMIT,
    MAX_BODY_CHARS,
    MAX_PAGE_LIMIT,
    PROJECTS_RESPONSE,
    PROJECT_FIELDS,
    PROJECT_WORKSPACE_RESPONSE,
    STORIES_RESPONSE,
    STORY_FIELDS,
    TASKS_RESPONSE,
    TASK_FIELDS,
    TASK_RESPONSE,
    WORKSPACES_RESPONSE,
    AsanaCommentView,
    AsanaCompleteTask,
    AsanaCreateStory,
    AsanaCreateTask,
    AsanaCreatedCommentView,
    AsanaErrorCode,
    AsanaFieldQuery,
    AsanaNamedResource,
    AsanaProjectQuery,
    AsanaProjectView,
    AsanaProjectsView,
    AsanaStoryType,
    AsanaTask,
    AsanaTaskDetailView,
    AsanaTaskQuery,
    AsanaTaskView,
    AsanaTasksView,
    AsanaWriteEnvelope,
    parse_response,
    require_task_identity,
)


class ListProjectsInput(BaseModel):
    workspace: str = Field(
        default="", description="Workspace name or gid. Defaults to the first one."
    )
    limit: StrictInt = Field(default=DEFAULT_PROJECT_LIMIT, ge=1, le=MAX_PAGE_LIMIT)


class SearchTasksInput(BaseModel):
    project: str = Field(
        default="", description="Project name or gid. Omit to search assigned work."
    )
    assignee_email: str | None = Field(
        default=None, description="Only tasks assigned to this person."
    )
    include_completed: StrictBool = Field(default=False)
    limit: StrictInt = Field(default=DEFAULT_TASK_LIMIT, ge=1, le=MAX_PAGE_LIMIT)


class GetTaskInput(BaseModel):
    task_id: str = Field(min_length=1, description="Task gid, or its permalink URL.")
    include_comments: StrictBool = Field(default=True)


class CreateTaskInput(BaseModel):
    name: str = Field(min_length=1, description="What the task is.")
    project: str = Field(default="", description="Project name or gid.")
    notes: str | None = Field(default=None, description="Longer description.")
    assignee_email: str | None = Field(default=None)
    due_on: str | None = Field(default=None, description="Due date as YYYY-MM-DD.")


class CompleteTaskInput(BaseModel):
    task_id: str = Field(min_length=1)


class AddCommentInput(BaseModel):
    task_id: str = Field(min_length=1)
    body: str = Field(min_length=1, description="Comment text.")


@curated_tool(
    vendor=vendor.vendor,
    name="list_projects",
    display_name="List Asana Projects",
    description=(
        "List the projects in a workspace, with their names and gids. Other "
        "tools accept a project name directly, so this is mainly for "
        "discovering what exists. Defaults to the first workspace the token "
        "can see."
    ),
    input_model=ListProjectsInput,
    effect=ToolEffect.READ,
)
async def list_projects(
    payload: ListProjectsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    workspace = await _resolve_workspace(ctx, payload.workspace)
    response = await ctx.read(
        "/projects",
        query=AsanaProjectQuery(
            workspace=workspace.gid,
            limit=payload.limit,
            archived=False,
            opt_fields=PROJECT_FIELDS,
        ).model_dump(mode="json"),
    )
    projects = parse_response(response, PROJECTS_RESPONSE).data
    return AsanaProjectsView(
        workspace=workspace.name,
        projects=[
            AsanaProjectView(gid=p.gid, name=p.name, notes=_clip(p.notes))
            for p in projects
        ],
        count=len(projects),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="search_tasks",
    display_name="Search Asana Tasks",
    description=(
        "List tasks in a project named rather than identified, or the tasks "
        "assigned to someone given by email. Completed work is hidden unless "
        "asked for. Each task reports its assignee, due date, and permalink."
    ),
    input_model=SearchTasksInput,
    effect=ToolEffect.READ,
)
async def search_tasks(
    payload: SearchTasksInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = None
    workspace_gid = None
    if payload.project:
        project = await _resolve_project(ctx, payload.project)
        if payload.assignee_email:
            response = await ctx.read(
                f"/projects/{quote(project.gid, safe='')}",
                query=AsanaFieldQuery(opt_fields="workspace.gid").model_dump(
                    mode="json"
                ),
            )
            resolved = parse_response(response, PROJECT_WORKSPACE_RESPONSE).data
            if resolved.gid != project.gid:
                raise VendorToolError(
                    AsanaErrorCode.RESPONSE_INVALID,
                    "Asana returned a different project.",
                )
            workspace_gid = resolved.workspace.gid
    elif payload.assignee_email:
        workspace_gid = (await _resolve_workspace(ctx, "")).gid
    else:
        raise VendorToolError(
            AsanaErrorCode.SEARCH_UNBOUNDED,
            "Give a project, or an assignee's email, to search within.",
        )
    query = AsanaTaskQuery(
        limit=payload.limit,
        completed_since=None if payload.include_completed else "now",
        project=project.gid if project else None,
        assignee=payload.assignee_email or None,
        workspace=workspace_gid,
    )
    response = await ctx.read(
        "/tasks", query=query.model_dump(mode="json", exclude_none=True)
    )
    tasks = parse_response(response, TASKS_RESPONSE).data
    return AsanaTasksView(
        project=project.name if project else None,
        tasks=[_task_view(task) for task in tasks],
        count=len(tasks),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_task",
    display_name="Get Asana Task",
    description=(
        "Read one task with the comments in the returned story page. Asana keeps "
        "comments at a separate endpoint and mixes them with automated "
        "activity records; only what people actually wrote is returned."
    ),
    input_model=GetTaskInput,
    effect=ToolEffect.READ,
)
async def get_task(
    payload: GetTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    task_gid = _task_gid(payload.task_id)
    response = await ctx.read(
        f"/tasks/{quote(task_gid, safe='')}",
        query=AsanaFieldQuery(opt_fields=TASK_FIELDS).model_dump(mode="json"),
    )
    task = parse_response(response, TASK_RESPONSE).data
    require_task_identity(task, task_gid)
    view = _task_view(task)
    if not payload.include_comments:
        return view.model_dump(mode="json")
    response = await ctx.read(
        f"/tasks/{quote(task_gid, safe='')}/stories",
        query=AsanaFieldQuery(opt_fields=STORY_FIELDS).model_dump(mode="json"),
    )
    stories = parse_response(response, STORIES_RESPONSE).data
    return AsanaTaskDetailView(
        **view.model_dump(),
        comments=[
            AsanaCommentView(
                author=story.created_by.name if story.created_by else None,
                body=_clip(story.text),
                created_at=story.created_at,
            )
            for story in stories
            if story.type == AsanaStoryType.COMMENT
        ],
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_task",
    display_name="Create Asana Task",
    description=(
        "Create a task in a project named rather than identified, optionally "
        "assigned to someone by email and due on a plain date. Asana requires "
        "a workspace when no project is given; the first available one is used."
    ),
    input_model=CreateTaskInput,
    effect=ToolEffect.MUTATION,
)
async def create_task(
    payload: CreateTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    project = await _resolve_project(ctx, payload.project) if payload.project else None
    workspace = None if project else await _resolve_workspace(ctx, "")
    body = AsanaCreateTask(
        name=payload.name,
        notes=payload.notes or None,
        assignee=payload.assignee_email or None,
        due_on=payload.due_on or None,
        projects=[project.gid] if project else None,
        workspace=workspace.gid if workspace else None,
    )
    response = await ctx.mutate(
        "/tasks",
        json=AsanaWriteEnvelope(data=body).model_dump(mode="json", exclude_none=True),
        query=AsanaFieldQuery(opt_fields=TASK_FIELDS).model_dump(mode="json"),
    )
    return _task_view(parse_response(response, TASK_RESPONSE).data).model_dump(
        mode="json"
    )


@curated_tool(
    vendor=vendor.vendor,
    name="complete_task",
    display_name="Complete Asana Task",
    description=(
        "Mark a task as done. Reversible in Asana's own interface, and the "
        "task keeps its history."
    ),
    input_model=CompleteTaskInput,
    effect=ToolEffect.MUTATION,
)
async def complete_task(
    payload: CompleteTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    task_gid = _task_gid(payload.task_id)
    response = await ctx.mutate(
        f"/tasks/{quote(task_gid, safe='')}",
        method="PUT",
        json=AsanaWriteEnvelope(data=AsanaCompleteTask()).model_dump(mode="json"),
        query=AsanaFieldQuery(opt_fields=TASK_FIELDS).model_dump(mode="json"),
    )
    task = parse_response(response, TASK_RESPONSE).data
    require_task_identity(task, task_gid)
    if not task.completed:
        raise VendorToolError(
            AsanaErrorCode.RESPONSE_INVALID, "Asana did not confirm task completion."
        )
    return _task_view(task).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_comment",
    display_name="Comment on Asana Task",
    description="Add a comment to a task. Notification delivery depends on Asana settings.",
    input_model=AddCommentInput,
    effect=ToolEffect.MUTATION,
)
async def add_comment(
    payload: AddCommentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    task_gid = _task_gid(payload.task_id)
    response = await ctx.mutate(
        f"/tasks/{quote(task_gid, safe='')}/stories",
        json=AsanaWriteEnvelope(data=AsanaCreateStory(text=payload.body)).model_dump(
            mode="json"
        ),
    )
    story = parse_response(response, CREATED_STORY_RESPONSE).data
    return AsanaCreatedCommentView(
        task_id=task_gid,
        comment_id=story.gid,
        created_at=story.created_at,
    ).model_dump(mode="json")


async def _resolve_workspace(
    ctx: VendorToolContext, workspace: str
) -> AsanaNamedResource:
    response = await ctx.read(
        "/workspaces", query=AsanaFieldQuery(opt_fields="name").model_dump(mode="json")
    )
    workspaces = parse_response(response, WORKSPACES_RESPONSE).data
    if not workspaces:
        raise VendorToolError(
            AsanaErrorCode.WORKSPACE_MISSING, "This token can see no Asana workspaces."
        )
    candidate = workspace.strip()
    if not candidate:
        return workspaces[0]
    wanted = candidate.casefold()
    for item in workspaces:
        if item.gid == candidate or item.name.casefold() == wanted:
            return item
    raise VendorToolError(
        AsanaErrorCode.WORKSPACE_NOT_FOUND,
        "No workspace matched the supplied name or gid.",
    )


async def _resolve_project(ctx: VendorToolContext, project: str) -> AsanaNamedResource:
    """Name resolution searches only the existing first-workspace page."""
    candidate = project.strip()
    if candidate.isdigit():
        return AsanaNamedResource(gid=candidate, name=candidate)
    workspace = await _resolve_workspace(ctx, "")
    response = await ctx.read(
        "/projects",
        query=AsanaProjectQuery(
            workspace=workspace.gid,
            limit=MAX_PAGE_LIMIT,
            opt_fields="name",
        ).model_dump(mode="json", exclude_none=True),
    )
    projects = parse_response(response, PROJECTS_RESPONSE).data
    wanted = candidate.casefold()
    matches = [p for p in projects if p.name.casefold() == wanted]
    if len(matches) == 1:
        return AsanaNamedResource(gid=matches[0].gid, name=matches[0].name)
    if len(matches) > 1:
        raise VendorToolError(
            AsanaErrorCode.PROJECT_AMBIGUOUS,
            "More than one project has this name. Give its gid instead.",
        )
    raise VendorToolError(
        AsanaErrorCode.PROJECT_NOT_FOUND,
        "No project matched the supplied name in the returned page.",
    )


def _task_gid(value: str) -> str:
    """Accept a gid or the existing permalink format ending in the gid."""
    candidate = value.strip().rstrip("/")
    if candidate.startswith("https://"):
        candidate = candidate.rsplit("/", 1)[-1]
    if not candidate:
        raise VendorToolError(
            AsanaErrorCode.TASK_INVALID, "Supply an Asana task gid or permalink."
        )
    return candidate


def _task_view(task: AsanaTask) -> AsanaTaskView:
    return AsanaTaskView(
        gid=task.gid,
        name=task.name,
        notes=_clip(task.notes),
        completed=task.completed,
        completed_at=task.completed_at,
        due_on=task.due_on,
        assignee=task.assignee.name if task.assignee else None,
        assignee_email=task.assignee.email if task.assignee else None,
        projects=[project.name for project in task.projects],
        tags=[tag.name for tag in task.tags],
        created_at=task.created_at,
        modified_at=task.modified_at,
        web_link=task.permalink_url,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


__all__ = [
    "add_comment",
    "complete_task",
    "create_task",
    "get_task",
    "list_projects",
    "search_tasks",
]
