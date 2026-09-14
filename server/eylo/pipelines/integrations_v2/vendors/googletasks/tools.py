"""Curated Google Tasks tools.

Every Tasks endpoint is addressed by a task-list id that nobody knows offhand,
so a raw flow is always two calls: list the lists, find the one called "Work",
then act. These tools accept the list *name* and resolve it, and default to the
account's first list when none is named.

Google also stores due dates as RFC 3339 timestamps while only honouring the
date part. `create_task` accepts a plain date and does that conversion, rather
than leaving a caller to discover that a time was silently discarded.
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import TASKS, vendor
from .schemas import (
    DEFAULT_TASK_PAGE_SIZE,
    LISTS_RESPONSE,
    MAX_LIST_LOOKUP_PAGES,
    MAX_NOTES_LENGTH,
    MAX_TASK_PAGE_SIZE,
    MAX_TITLE_LENGTH,
    TASKS_RESPONSE,
    TASK_RESPONSE,
    DateText,
    Task,
    TaskComplete,
    TaskCreate,
    TaskDeletedView,
    TaskList,
    TaskListView,
    TaskListsQuery,
    TaskListsView,
    TaskMutationView,
    TaskParentQuery,
    TaskStatus,
    TasksErrorCode,
    TasksQuery,
    TasksView,
    parse_response,
    rfc3339,
    task_view,
)


class ListTaskListsInput(BaseModel):
    pass


class ListTasksInput(BaseModel):
    task_list: str = Field(
        default="", description="Task list name or id. Defaults to the first list."
    )
    include_completed: StrictBool = Field(default=False)
    due_before: DateText | None = Field(
        default=None, description="Only tasks due before this date (YYYY-MM-DD)."
    )
    limit: StrictInt = Field(
        default=DEFAULT_TASK_PAGE_SIZE, ge=1, le=MAX_TASK_PAGE_SIZE
    )
    page_token: str | None = Field(
        default=None,
        min_length=1,
        description="Continue with the same list and filters.",
    )


class CreateTaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    task_list: str = Field(default="", description="Task list name or id.")
    notes: str | None = Field(
        default=None,
        max_length=MAX_NOTES_LENGTH,
        description="Longer detail on the task.",
    )
    due: DateText | None = Field(
        default=None,
        description="Due date as YYYY-MM-DD. Google records the date only.",
    )
    parent_task_id: str | None = Field(
        default=None,
        min_length=1,
        description="Make this a subtask of an existing task.",
    )


class CompleteTaskInput(BaseModel):
    task_id: str = Field(min_length=1)
    task_list: str = Field(default="", description="Task list name or id.")


class DeleteTaskInput(BaseModel):
    task_id: str = Field(min_length=1)
    task_list: str = Field(default="", description="Task list name or id.")


@curated_tool(
    vendor=vendor.vendor,
    name="list_task_lists",
    display_name="List Google Task Lists",
    description=(
        "List the account's task lists with their names and ids. Other tools "
        "accept a list name directly, so this is only needed to discover what "
        "exists."
    ),
    input_model=ListTaskListsInput,
    effect=ToolEffect.READ,
    scopes=(TASKS,),
)
async def list_task_lists(
    payload: ListTaskListsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    lists = await _task_lists(ctx)
    return TaskListsView(
        task_lists=[TaskListView(id=item.id, name=item.title) for item in lists],
        count=len(lists),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_tasks",
    display_name="List Google Tasks",
    description=(
        "List tasks in a list, addressed by name. Completed tasks are hidden "
        "unless asked for, and a due_before date narrows the result to what is "
        "coming up. Subtasks report the task they belong to. Results are paginated; "
        "pass next_page_token as page_token to continue with the same filters."
    ),
    input_model=ListTasksInput,
    effect=ToolEffect.READ,
    scopes=(TASKS,),
)
async def list_tasks(
    payload: ListTasksInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    selected = await _resolve_list(ctx, payload.task_list)
    query = TasksQuery(
        maxResults=payload.limit,
        showCompleted=payload.include_completed,
        showHidden=payload.include_completed,
        dueMax=rfc3339(payload.due_before),
        pageToken=payload.page_token,
    )
    response = await ctx.read(
        f"/lists/{quote(selected.id, safe='')}/tasks",
        query=query.model_dump(mode="json", exclude_none=True),
    )
    page = parse_response(response, TASKS_RESPONSE)
    return TasksView(
        task_list=selected.title,
        task_list_id=selected.id,
        tasks=[task_view(item) for item in page.items],
        count=len(page.items),
        next_page_token=page.nextPageToken,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_task",
    display_name="Create Google Task",
    description=(
        "Add a task to a list named rather than identified. The due date is "
        "given as a plain YYYY-MM-DD date; Google stores dates only and "
        "ignores any time of day. Give parent_task_id to create a subtask."
    ),
    input_model=CreateTaskInput,
    effect=ToolEffect.MUTATION,
    scopes=(TASKS,),
)
async def create_task(
    payload: CreateTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    selected = await _resolve_list(ctx, payload.task_list)
    body = TaskCreate(
        title=payload.title, notes=payload.notes, due=rfc3339(payload.due)
    )
    query = TaskParentQuery(parent=payload.parent_task_id)
    response = await ctx.mutate(
        f"/lists/{quote(selected.id, safe='')}/tasks",
        json=body.model_dump(mode="json", exclude_none=True),
        query=query.model_dump(mode="json", exclude_none=True),
    )
    task = parse_response(response, TASK_RESPONSE)
    if (
        task.status is not TaskStatus.NEEDS_ACTION
        or task.parent != payload.parent_task_id
        or task.title != payload.title
        or (task.due[:10] if task.due is not None else None) != payload.due
        or (task.notes or "") != (payload.notes or "")
    ):
        _invalid_acknowledgement()
    return _mutation_view(task, selected)


@curated_tool(
    vendor=vendor.vendor,
    name="complete_task",
    display_name="Complete Google Task",
    description=(
        "Mark a task as done. The list may be named rather than identified. "
        "Completing a task is reversible in the Google Tasks interface."
    ),
    input_model=CompleteTaskInput,
    effect=ToolEffect.MUTATION,
    scopes=(TASKS,),
)
async def complete_task(
    payload: CompleteTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    selected = await _resolve_list(ctx, payload.task_list)
    response = await ctx.mutate(
        f"/lists/{quote(selected.id, safe='')}/tasks/{quote(payload.task_id, safe='')}",
        method="PATCH",
        json=TaskComplete().model_dump(mode="json"),
    )
    task = parse_response(response, TASK_RESPONSE)
    if task.id != payload.task_id or task.status is not TaskStatus.COMPLETED:
        _invalid_acknowledgement()
    return _mutation_view(task, selected)


@curated_tool(
    vendor=vendor.vendor,
    name="delete_task",
    display_name="Delete Google Task",
    description=(
        "Remove a task from its list. Prefer complete_task when the work was "
        "actually done, so the record of it survives. For assigned tasks, deletion "
        "also deletes the original task in Google Docs or Chat Spaces."
    ),
    input_model=DeleteTaskInput,
    effect=ToolEffect.MUTATION,
    scopes=(TASKS,),
)
async def delete_task(
    payload: DeleteTaskInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    selected = await _resolve_list(ctx, payload.task_list)
    response = await ctx.mutate(
        f"/lists/{quote(selected.id, safe='')}/tasks/{quote(payload.task_id, safe='')}",
        method="DELETE",
    )
    if not response.ok:
        raise VendorToolError(
            TasksErrorCode.REJECTED, "Google Tasks rejected deletion."
        )
    if response.status_code not in {
        HTTPStatus.OK,
        HTTPStatus.NO_CONTENT,
    } or response.data not in (None, {}):
        _invalid_acknowledgement()
    return TaskDeletedView(
        task_id=payload.task_id, task_list=selected.title, task_list_id=selected.id
    ).model_dump(mode="json")


async def _task_lists(ctx: VendorToolContext) -> list[TaskList]:
    """Read a bounded complete list catalog; never choose from a partial catalog."""
    items: list[TaskList] = []
    seen_tokens: set[str] = set()
    page_token: str | None = None
    for _ in range(MAX_LIST_LOOKUP_PAGES):
        query = TaskListsQuery(pageToken=page_token)
        response = await ctx.read(
            "/users/@me/lists", query=query.model_dump(mode="json", exclude_none=True)
        )
        page = parse_response(response, LISTS_RESPONSE)
        items.extend(page.items)
        page_token = page.nextPageToken
        if page_token is None:
            if len({item.id for item in items}) != len(items):
                _invalid_acknowledgement()
            return items
        if page_token in seen_tokens:
            break
        seen_tokens.add(page_token)
    raise VendorToolError(
        TasksErrorCode.LIST_LOOKUP_INCOMPLETE,
        "Google Tasks list lookup did not finish within its page budget.",
    )


async def _resolve_list(ctx: VendorToolContext, task_list: str) -> TaskList:
    lists = await _task_lists(ctx)
    if not lists:
        raise VendorToolError(
            TasksErrorCode.LIST_MISSING, "This account has no task lists."
        )
    candidate = task_list.strip()
    if not candidate:
        return lists[0]
    for item in lists:
        if item.id == candidate:
            return item
    matches = [item for item in lists if item.title.casefold() == candidate.casefold()]
    if len(matches) > 1:
        raise VendorToolError(
            TasksErrorCode.LIST_AMBIGUOUS,
            "Several task lists have that name. Use a list id.",
        )
    if not matches:
        raise VendorToolError(
            TasksErrorCode.LIST_NOT_FOUND, "No matching Google task list."
        )
    return matches[0]


def _mutation_view(task: Task, selected: TaskList) -> dict[str, JsonValue]:
    return TaskMutationView(
        **task_view(task).model_dump(), task_list=selected.title
    ).model_dump(mode="json")


def _invalid_acknowledgement() -> None:
    raise VendorToolError(
        TasksErrorCode.RESPONSE_INVALID,
        "Google Tasks did not confirm the requested operation.",
    )


__all__ = [
    "complete_task",
    "create_task",
    "delete_task",
    "list_task_lists",
    "list_tasks",
]
