"""Google Tasks v1 wire contracts and curated projections; no platform policy."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from ...contracts import VendorResponse, VendorToolError

MAX_LIST_PAGE_SIZE = 1000
MAX_LIST_LOOKUP_PAGES = 3
MAX_TASK_PAGE_SIZE = 100
DEFAULT_TASK_PAGE_SIZE = 50
MAX_TITLE_LENGTH = 1024
MAX_NOTES_LENGTH = 8192


class TasksErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    LIST_MISSING = "task_list_missing"
    LIST_NOT_FOUND = "task_list_not_found"
    LIST_AMBIGUOUS = "task_list_ambiguous"
    LIST_LOOKUP_INCOMPLETE = "task_list_lookup_incomplete"


class TaskStatus(StrEnum):
    NEEDS_ACTION = "needsAction"
    COMPLETED = "completed"


def calendar_date(value: str) -> str:
    """Accept the advertised date syntax, not silently truncated timestamps."""
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Use YYYY-MM-DD for a Google Tasks date.")
    return value


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Google Tasks timestamps require a timezone.")
    return value


DateText = Annotated[str, AfterValidator(calendar_date)]
TimestampText = Annotated[str, AfterValidator(timestamp)]
Identifier = Annotated[str, Field(min_length=1)]
NativeStatus = Annotated[
    TaskStatus,
    BeforeValidator(
        lambda value: TaskStatus(value) if isinstance(value, str) else value
    ),
]


class TasksModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class TasksRequest(TasksModel):
    model_config = ConfigDict(extra="forbid")


class TaskList(TasksModel):
    id: Identifier
    title: str


class TaskListsPage(TasksModel):
    kind: Literal["tasks#taskLists"]
    items: list[TaskList] = Field(default_factory=list)
    nextPageToken: Identifier | None = None


class Task(TasksModel):
    kind: Literal["tasks#task"]
    id: Identifier
    title: str
    status: NativeStatus
    notes: str | None = Field(default=None, repr=False)
    due: TimestampText | None = None
    completed: TimestampText | None = None
    parent: Identifier | None = None
    updated: TimestampText | None = None


class TasksPage(TasksModel):
    kind: Literal["tasks#tasks"]
    items: list[Task] = Field(default_factory=list)
    nextPageToken: Identifier | None = None


class TaskListsQuery(TasksRequest):
    maxResults: int = Field(default=MAX_LIST_PAGE_SIZE, ge=1, le=MAX_LIST_PAGE_SIZE)
    pageToken: Identifier | None = None


class TasksQuery(TasksRequest):
    maxResults: int = Field(ge=1, le=MAX_TASK_PAGE_SIZE)
    showCompleted: bool
    showHidden: bool
    dueMax: TimestampText | None = None
    pageToken: Identifier | None = None


class TaskCreate(TasksRequest):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    status: Literal[TaskStatus.NEEDS_ACTION] = TaskStatus.NEEDS_ACTION
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH, repr=False)
    due: TimestampText | None = None


class TaskParentQuery(TasksRequest):
    parent: Identifier | None = None


class TaskComplete(TasksRequest):
    status: Literal[TaskStatus.COMPLETED] = TaskStatus.COMPLETED


class TaskListView(TasksModel):
    id: str
    name: str


class TaskListsView(TasksModel):
    task_lists: list[TaskListView]
    count: int


class TaskView(TasksModel):
    id: str
    title: str
    notes: str | None = Field(repr=False)
    due: str | None
    completed: bool
    completed_at: str | None
    parent_task_id: str | None
    updated_at: str | None


class TaskMutationView(TaskView):
    task_list: str


class TasksView(TasksModel):
    task_list: str
    task_list_id: str
    tasks: list[TaskView]
    count: int
    next_page_token: str | None


class TaskDeletedView(TasksModel):
    task_id: str
    task_list: str
    task_list_id: str
    deleted: Literal[True] = True


class TasksApiError(TasksModel):
    code: int | None = None
    message: str | None = Field(default=None, repr=False)


class TasksErrorEnvelope(TasksModel):
    error: TasksApiError | None = None


TASK_RESPONSE = TypeAdapter(Task)
TASKS_RESPONSE = TypeAdapter(TasksPage)
LISTS_RESPONSE = TypeAdapter(TaskListsPage)


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            TasksErrorCode.REJECTED, "Google Tasks rejected the request."
        )
    try:
        if TasksErrorEnvelope.model_validate(response.data).error is not None:
            raise VendorToolError(
                TasksErrorCode.REJECTED, "Google Tasks rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            TasksErrorCode.RESPONSE_INVALID,
            "Google Tasks returned an invalid operation response.",
        ) from None


def task_view(task: Task) -> TaskView:
    return TaskView(
        id=task.id,
        title=task.title,
        notes=task.notes,
        due=task.due[:10] if task.due is not None else None,
        completed=task.status is TaskStatus.COMPLETED,
        completed_at=task.completed,
        parent_task_id=task.parent,
        updated_at=task.updated,
    )


def rfc3339(value: str | None) -> str | None:
    return f"{calendar_date(value)}T00:00:00.000Z" if value is not None else None
