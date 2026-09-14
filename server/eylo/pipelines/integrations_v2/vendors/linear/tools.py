"""Curated Linear tools.

These are the shape the whole V2 effort exists for. `create_issue` accepts the
team *name* and assignee *email* an agent already has from the conversation and
resolves them to Linear ids itself; `remove_issue_label` reads the issue,
computes the remaining labels, and writes them back. Each is one tool call
where the raw API would have cost two or three plus the model's reasoning about
intermediate JSON.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from . import client
from .definition import vendor
from .schemas import (
    DEFAULT_ISSUE_LIMIT,
    IDENTITY_LOOKUP_LIMIT,
    MAX_ISSUES,
    LinearCreateInput,
    LinearCreateResult,
    LinearCreateVariables,
    LinearIssue,
    LinearIssueFilter,
    LinearIssueListView,
    LinearIssueResult,
    LinearIssueVariables,
    LinearIssueView,
    LinearIssuesResult,
    LinearIssuesVariables,
    LinearLabelInput,
    LinearPriority,
    LinearStringComparator,
    LinearTeamFilter,
    LinearTeamVariables,
    LinearTeamsResult,
    LinearToolErrorCode,
    LinearToolName,
    LinearUpdateResult,
    LinearUpdateVariables,
    LinearUserFilter,
    LinearUserVariables,
    LinearUsersResult,
)
from .scopes import ISSUES_CREATE, READ, WRITE

_ISSUE_FIELDS = """
  id
  identifier
  title
  description
  url
  priority
  priorityLabel
  state { id name type }
  assignee { id name email }
  team { id name key }
  labels { nodes { id name } }
  createdAt
  updatedAt
"""


class ListIssuesInput(BaseModel):
    team_name: str | None = Field(
        default=None,
        description="Restrict to one team by its name, for example 'Platform'.",
    )
    assignee_email: str | None = Field(
        default=None,
        description="Restrict to issues assigned to this person's email address.",
    )
    limit: int = Field(
        default=DEFAULT_ISSUE_LIMIT,
        ge=1,
        le=MAX_ISSUES,
        description="Maximum number of issues to return.",
    )


class CreateIssueInput(BaseModel):
    title: str = Field(min_length=1, description="Issue title.")
    team_name: str = Field(
        min_length=1,
        description="Name of the team the issue belongs to, for example 'Platform'.",
    )
    description: str | None = Field(
        default=None,
        description="Issue body in Markdown.",
    )
    assignee_email: str | None = Field(
        default=None,
        description="Email address of the person to assign the issue to.",
    )
    priority: int | None = Field(
        default=None,
        ge=LinearPriority.NONE.value,
        le=LinearPriority.LOW.value,
        description="0 none, 1 urgent, 2 high, 3 medium, 4 low.",
    )


class RemoveIssueLabelInput(BaseModel):
    issue_id: str = Field(
        min_length=1,
        description="Issue id or identifier such as 'PLT-123'.",
    )
    label_name: str = Field(
        min_length=1,
        description="Name of the label to remove from the issue.",
    )


@curated_tool(
    vendor=vendor.vendor,
    name=LinearToolName.LIST_ISSUES,
    display_name="List Linear Issues",
    description=(
        "List non-archived Linear issues, optionally narrowed to one team by "
        "name or one assignee by email address. Returns issues with their "
        "state, assignee, team, and labels already resolved, so no follow-up "
        "lookup is needed."
    ),
    input_model=ListIssuesInput,
    effect=ToolEffect.READ,
    scopes=(READ,),
)
async def list_issues(
    payload: ListIssuesInput,
    ctx: VendorToolContext,
) -> dict[str, JsonValue]:
    filters = LinearIssueFilter(
        team=(
            LinearTeamFilter(
                name=LinearStringComparator(eqIgnoreCase=payload.team_name)
            )
            if payload.team_name
            else None
        ),
        assignee=(
            LinearUserFilter(
                email=LinearStringComparator(eqIgnoreCase=payload.assignee_email)
            )
            if payload.assignee_email
            else None
        ),
    )

    document = f"""
      query Issues($first: Int, $filter: IssueFilter) {{
        issues(first: $first, filter: $filter) {{
          nodes {{{_ISSUE_FIELDS}}}
        }}
      }}
    """
    data = await client.query(
        ctx,
        document,
        LinearIssuesVariables(
            first=payload.limit,
            filter=filters if payload.team_name or payload.assignee_email else None,
        ),
        response_model=LinearIssuesResult,
    )
    issues = [_issue_view(node) for node in data.issues.nodes]
    return LinearIssueListView(issues=issues, count=len(issues)).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name=LinearToolName.CREATE_ISSUE,
    display_name="Create Linear Issue",
    description=(
        "Create a Linear issue from a team name and, optionally, an assignee "
        "email address. Both are resolved to Linear ids automatically, so the "
        "team and person can be named the way a person would say them rather "
        "than looked up first."
    ),
    input_model=CreateIssueInput,
    effect=ToolEffect.MUTATION,
    scopes=(ISSUES_CREATE,),
)
async def create_issue(
    payload: CreateIssueInput,
    ctx: VendorToolContext,
) -> dict[str, JsonValue]:
    team_id = await _resolve_team_id(ctx, payload.team_name)
    assignee_id = (
        await _resolve_user_id(ctx, payload.assignee_email)
        if payload.assignee_email
        else None
    )

    document = f"""
      mutation IssueCreate($input: IssueCreateInput!) {{
        issueCreate(input: $input) {{
          success
          issue {{{_ISSUE_FIELDS}}}
        }}
      }}
    """
    issue_input = LinearCreateInput(
        title=payload.title,
        teamId=team_id,
        description=payload.description,
        assigneeId=assignee_id,
        priority=LinearPriority(payload.priority)
        if payload.priority is not None
        else None,
    )
    data = await client.mutate(
        ctx,
        document,
        LinearCreateVariables(input=issue_input),
        response_model=LinearCreateResult,
    )
    result = data.issue_create
    if not result.success:
        raise VendorToolError(
            LinearToolErrorCode.REJECTED, "Linear did not create the issue."
        )
    return _issue_view(result.issue).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name=LinearToolName.REMOVE_ISSUE_LABEL,
    display_name="Remove Label From Linear Issue",
    description=(
        "Remove one label from a Linear issue by label name. Reads the issue's "
        "current labels, removes the named one, and writes the remainder back "
        "in a single step. Reports clearly when the issue does not carry that "
        "label rather than silently succeeding."
    ),
    input_model=RemoveIssueLabelInput,
    effect=ToolEffect.MUTATION,
    scopes=(WRITE,),
)
async def remove_issue_label(
    payload: RemoveIssueLabelInput,
    ctx: VendorToolContext,
) -> dict[str, JsonValue]:
    document = f"""
      query Issue($id: String!) {{
        issue(id: $id) {{{_ISSUE_FIELDS}}}
      }}
    """
    data = await client.query(
        ctx,
        document,
        LinearIssueVariables(id=payload.issue_id),
        response_model=LinearIssueResult,
    )
    issue = data.issue
    if issue is None:
        raise VendorToolError(
            LinearToolErrorCode.ISSUE_NOT_FOUND, "Linear issue was not found."
        )

    labels = issue.labels.nodes
    wanted = payload.label_name.strip().casefold()
    remaining = [label for label in labels if label.name.strip().casefold() != wanted]
    if len(remaining) == len(labels):
        raise VendorToolError(
            LinearToolErrorCode.LABEL_NOT_PRESENT,
            f"Issue does not carry the label '{payload.label_name}'.",
        )

    update = f"""
      mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {{
        issueUpdate(id: $id, input: $input) {{
          success
          issue {{{_ISSUE_FIELDS}}}
        }}
      }}
    """
    updated = await client.mutate(
        ctx,
        update,
        LinearUpdateVariables(
            id=issue.id,
            input=LinearLabelInput(labelIds=[label.id for label in remaining]),
        ),
        response_model=LinearUpdateResult,
    )
    result = updated.issue_update
    if not result.success:
        raise VendorToolError(
            LinearToolErrorCode.REJECTED, "Linear did not update the issue."
        )
    return _issue_view(result.issue).model_dump(mode="json")


async def _resolve_team_id(ctx: VendorToolContext, team_name: str) -> str:
    document = f"""
      query Teams($name: String!) {{
        teams(filter: {{ name: {{ eqIgnoreCase: $name }} }}, first: {IDENTITY_LOOKUP_LIMIT}) {{
          nodes {{ id name key }}
        }}
      }}
    """
    data = await client.query(
        ctx,
        document,
        LinearTeamVariables(name=team_name),
        response_model=LinearTeamsResult,
    )
    teams = data.teams.nodes
    if not teams:
        raise VendorToolError(
            LinearToolErrorCode.TEAM_NOT_FOUND, f"No Linear team named '{team_name}'."
        )
    if len(teams) > 1:
        raise VendorToolError(
            LinearToolErrorCode.TEAM_AMBIGUOUS,
            f"More than one Linear team matches '{team_name}'.",
        )
    return teams[0].id


async def _resolve_user_id(ctx: VendorToolContext, email: str) -> str:
    document = f"""
      query Users($email: String!) {{
        users(filter: {{ email: {{ eqIgnoreCase: $email }} }}, first: {IDENTITY_LOOKUP_LIMIT}) {{
          nodes {{ id name email }}
        }}
      }}
    """
    data = await client.query(
        ctx,
        document,
        LinearUserVariables(email=email),
        response_model=LinearUsersResult,
    )
    users = data.users.nodes
    if not users:
        raise VendorToolError(
            LinearToolErrorCode.USER_NOT_FOUND, f"No Linear user with email '{email}'."
        )
    return users[0].id


def _issue_view(issue: LinearIssue | None) -> LinearIssueView:
    """Project one Linear issue into the flat shape agents actually use."""
    if issue is None:
        raise VendorToolError(
            LinearToolErrorCode.RESPONSE_INVALID,
            "Linear returned no issue for the operation.",
        )
    return LinearIssueView(
        id=issue.id,
        identifier=issue.identifier,
        title=issue.title,
        description=issue.description,
        url=issue.url,
        priority=issue.priority_label,
        state=issue.state.name,
        assignee_name=issue.assignee.name if issue.assignee is not None else None,
        assignee_email=issue.assignee.email if issue.assignee is not None else None,
        team_name=issue.team.name,
        labels=[label.name for label in issue.labels.nodes],
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )


__all__ = ["create_issue", "list_issues", "remove_issue_label"]
