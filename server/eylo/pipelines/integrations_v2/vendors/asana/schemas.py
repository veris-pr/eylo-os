"""Asana API 1.0 selected wire fields and curated tool projections."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_BODY_CHARS = 6_000
DEFAULT_PROJECT_LIMIT = 50
DEFAULT_TASK_LIMIT = 25
MAX_PAGE_LIMIT = 100
TASK_FIELDS = (
    "name,notes,completed,completed_at,due_on,created_at,modified_at,"
    "assignee.name,assignee.email,projects.name,tags.name,permalink_url"
)
PROJECT_FIELDS = "name,archived,color,notes"
STORY_FIELDS = "text,created_at,created_by.name,type"


class AsanaErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SEARCH_UNBOUNDED = "search_unbounded"
    WORKSPACE_MISSING = "workspace_missing"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    PROJECT_AMBIGUOUS = "project_ambiguous"
    PROJECT_NOT_FOUND = "project_not_found"
    TASK_INVALID = "task_invalid"


class AsanaStoryType(StrEnum):
    COMMENT = "comment"
    SYSTEM = "system"


class AsanaModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class AsanaRequest(AsanaModel):
    model_config = ConfigDict(extra="forbid")


class AsanaReadEnvelope[T](AsanaModel):
    data: T


class AsanaWriteEnvelope[T](AsanaRequest):
    data: T


class AsanaFieldQuery(AsanaRequest):
    opt_fields: str


class AsanaProjectQuery(AsanaRequest):
    workspace: str = Field(min_length=1)
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    archived: bool | None = None
    opt_fields: str


class AsanaTaskQuery(AsanaRequest):
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)
    opt_fields: str = TASK_FIELDS
    completed_since: Literal["now"] | None = None
    project: str | None = None
    assignee: str | None = None
    workspace: str | None = None


class AsanaCreateTask(AsanaRequest):
    name: str = Field(min_length=1, repr=False)
    notes: str | None = Field(default=None, repr=False)
    assignee: str | None = Field(default=None, repr=False)
    due_on: str | None = None
    projects: list[str] | None = None
    workspace: str | None = None


class AsanaCompleteTask(AsanaRequest):
    completed: Literal[True] = True


class AsanaCreateStory(AsanaRequest):
    text: str = Field(min_length=1, repr=False)


class AsanaName(AsanaModel):
    name: str


class AsanaNamedResource(AsanaName):
    gid: str = Field(min_length=1)


class AsanaResourceId(AsanaModel):
    gid: str = Field(min_length=1)


class AsanaProjectWorkspace(AsanaResourceId):
    workspace: AsanaResourceId


class AsanaProject(AsanaNamedResource):
    notes: str | None = Field(default=None, repr=False)


class AsanaUser(AsanaName):
    email: str | None = Field(default=None, repr=False)


class AsanaTask(AsanaNamedResource):
    notes: str | None = Field(default=None, repr=False)
    completed: bool
    completed_at: str | None = None
    due_on: str | None = None
    assignee: AsanaUser | None = None
    projects: list[AsanaName] = Field(default_factory=list)
    tags: list[AsanaName] = Field(default_factory=list)
    created_at: str | None = None
    modified_at: str | None = None
    permalink_url: str | None = None


class AsanaStory(AsanaResourceId):
    type: str
    text: str = Field(repr=False)
    created_at: str
    created_by: AsanaName | None


class AsanaCreatedStory(AsanaResourceId):
    created_at: str


class AsanaError(AsanaModel):
    message: str = Field(repr=False)


class AsanaErrorEnvelope(AsanaModel):
    errors: list[AsanaError] = Field(default_factory=list, repr=False)


class AsanaProjectView(AsanaModel):
    gid: str
    name: str
    notes: str | None = Field(repr=False)


class AsanaProjectsView(AsanaModel):
    workspace: str
    projects: list[AsanaProjectView]
    count: int


class AsanaCommentView(AsanaModel):
    author: str | None
    body: str | None = Field(repr=False)
    created_at: str


class AsanaTaskView(AsanaModel):
    gid: str
    name: str
    notes: str | None = Field(repr=False)
    completed: bool
    completed_at: str | None
    due_on: str | None
    assignee: str | None
    assignee_email: str | None = Field(repr=False)
    projects: list[str]
    tags: list[str]
    created_at: str | None
    modified_at: str | None
    web_link: str | None


class AsanaTaskDetailView(AsanaTaskView):
    comments: list[AsanaCommentView]


class AsanaTasksView(AsanaModel):
    project: str | None
    tasks: list[AsanaTaskView]
    count: int


class AsanaCreatedCommentView(AsanaModel):
    task_id: str
    comment_id: str
    created_at: str


WORKSPACES_RESPONSE = TypeAdapter(AsanaReadEnvelope[list[AsanaNamedResource]])
PROJECTS_RESPONSE = TypeAdapter(AsanaReadEnvelope[list[AsanaProject]])
PROJECT_WORKSPACE_RESPONSE = TypeAdapter(AsanaReadEnvelope[AsanaProjectWorkspace])
TASKS_RESPONSE = TypeAdapter(AsanaReadEnvelope[list[AsanaTask]])
TASK_RESPONSE = TypeAdapter(AsanaReadEnvelope[AsanaTask])
STORIES_RESPONSE = TypeAdapter(AsanaReadEnvelope[list[AsanaStory]])
CREATED_STORY_RESPONSE = TypeAdapter(AsanaReadEnvelope[AsanaCreatedStory])


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """Require the native envelope; never retry an invalid mutation reply."""
    if not response.ok:
        raise VendorToolError(AsanaErrorCode.REJECTED, "Asana rejected the request.")
    try:
        error = AsanaErrorEnvelope.model_validate(response.data)
        if error.errors:
            raise VendorToolError(
                AsanaErrorCode.REJECTED, "Asana rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            AsanaErrorCode.RESPONSE_INVALID,
            "Asana returned an invalid operation response.",
        ) from None


def require_task_identity(task: AsanaTask, expected_gid: str) -> None:
    if task.gid != expected_gid:
        raise VendorToolError(
            AsanaErrorCode.RESPONSE_INVALID, "Asana returned a different task."
        )
