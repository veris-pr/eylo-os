"""Curated Zendesk tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    DEFAULT_TICKET_LIMIT,
    MAX_BODY_CHARS,
    MAX_TICKET_LIMIT,
    SEARCH_TICKETS_PATH,
    SEARCH_USERS_PATH,
    TICKETS_PATH,
    TICKET_SEARCH_TERM,
    UPDATE_METHOD,
    ZendeskAddCommentRequest,
    ZendeskCommentRequest,
    ZendeskCommentResult,
    ZendeskCommentUpdate,
    ZendeskCommentView,
    ZendeskComments,
    ZendeskCommentsQuery,
    ZendeskCreateRequest,
    ZendeskCreateTicket,
    ZendeskFoundUser,
    ZendeskInitialComment,
    ZendeskMissingUser,
    ZendeskPriority,
    ZendeskRequester,
    ZendeskSearchQuery,
    ZendeskSearchResult,
    ZendeskStatus,
    ZendeskTicket,
    ZendeskTicketDetail,
    ZendeskTicketSearch,
    ZendeskTicketView,
    ZendeskToolErrorCode,
    ZendeskUpdateRequest,
    ZendeskUpdateTicket,
    ZendeskUser,
    ZendeskUserQuery,
    ZendeskUsers,
    parse_response,
    ticket_from_response,
)


class ZendeskToolInput(BaseModel):
    """Keep historical case-insensitive choices while exposing their enums."""

    @field_validator("status", "priority", mode="before", check_fields=False)
    @classmethod
    def normalize_choice(cls, value: object) -> object:
        if value == "":
            return None
        return value.strip().casefold() if isinstance(value, str) else value


class SearchTicketsInput(ZendeskToolInput):
    text: str | None = Field(default=None, description="Free text to match.")
    status: ZendeskStatus | None = Field(
        default=None,
        description="One of new, open, pending, hold, solved, closed.",
    )
    requester_email: str | None = Field(
        default=None, description="Person who raised the ticket."
    )
    assignee_email: str | None = Field(
        default=None, description="Agent the ticket is assigned to."
    )
    tags: list[str] | None = None
    limit: StrictInt = Field(default=DEFAULT_TICKET_LIMIT, ge=1, le=MAX_TICKET_LIMIT)


class GetTicketInput(BaseModel):
    ticket_id: StrictInt = Field(ge=1)
    include_comments: StrictBool = Field(default=True)


class CreateTicketInput(ZendeskToolInput):
    subject: str = Field(min_length=1)
    description: str = Field(min_length=1, description="The first comment's body.")
    requester_email: str | None = Field(
        default=None,
        description="Person the ticket is for. Created in Zendesk if unknown.",
    )
    requester_name: str | None = Field(
        default=None, description="Used only when creating a new requester."
    )
    priority: ZendeskPriority | None = Field(
        default=None, description="low, normal, high, urgent."
    )
    tags: list[str] | None = None


class AddCommentInput(BaseModel):
    ticket_id: StrictInt = Field(ge=1)
    body: str = Field(min_length=1)
    public: StrictBool = Field(
        description=(
            "Required. True emails the comment to the customer; false leaves "
            "an internal note only other agents can see. There is no default "
            "because the difference is not recoverable."
        )
    )


class UpdateTicketInput(ZendeskToolInput):
    ticket_id: StrictInt = Field(ge=1)
    status: ZendeskStatus | None = Field(
        default=None, description="new, open, pending, hold, solved, closed."
    )
    priority: ZendeskPriority | None = Field(
        default=None, description="low, normal, high, urgent."
    )
    assignee_email: str | None = Field(default=None, description="Agent to assign to.")
    tags: list[str] | None = Field(default=None, description="Replaces existing tags.")


class FindUserInput(BaseModel):
    email: str = Field(min_length=1)


@curated_tool(
    vendor=vendor.vendor,
    name="search_tickets",
    display_name="Search Zendesk Tickets",
    description=(
        "Find tickets by status, requester, assignee, tag, or free text, "
        "without writing Zendesk's search syntax. People are named by email "
        "and resolved here. Results carry subject, status, priority, and "
        "requester."
    ),
    input_model=SearchTicketsInput,
    effect=ToolEffect.READ,
)
async def search_tickets(
    payload: SearchTicketsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    terms = [TICKET_SEARCH_TERM]
    if payload.status:
        terms.append(f"status:{payload.status.value}")
    if payload.requester_email:
        terms.append(f"requester:{payload.requester_email}")
    if payload.assignee_email:
        terms.append(f"assignee:{payload.assignee_email}")
    for tag in payload.tags or []:
        terms.append(f"tags:{tag}")
    if payload.text:
        terms.append(payload.text)

    query = " ".join(terms)
    response = await ctx.read(
        SEARCH_TICKETS_PATH,
        query=ZendeskSearchQuery(query=query, per_page=payload.limit).model_dump(
            mode="json"
        ),
    )
    body = parse_response(response, ZendeskTicketSearch)
    return ZendeskSearchResult(
        tickets=[_ticket_view(item) for item in body.results],
        count=len(body.results),
        total_matches=body.count,
        query=query,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_ticket",
    display_name="Get Zendesk Ticket",
    description=(
        "Read one ticket together with its full conversation. Each comment "
        "reports whether it was public — visible to the customer — or an "
        "internal note, which is what tells you what the customer has actually "
        "been told."
    ),
    input_model=GetTicketInput,
    effect=ToolEffect.READ,
)
async def get_ticket(
    payload: GetTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    ticket = ticket_from_response(
        await ctx.read(f"/tickets/{payload.ticket_id}.json"),
        expected_id=payload.ticket_id,
    )
    view = ZendeskTicketDetail(
        **_ticket_view(ticket).model_dump(),
        description=_clip(ticket.description),
    )

    if payload.include_comments:
        response = await ctx.read(
            f"/tickets/{payload.ticket_id}/comments.json",
            query=ZendeskCommentsQuery().model_dump(mode="json"),
        )
        comments = parse_response(response, ZendeskComments)
        view = ZendeskTicketDetail(
            **view.model_dump(exclude_unset=True),
            comments=[
                ZendeskCommentView(
                    id=comment.id,
                    author_id=comment.author_id,
                    body=_clip(comment.plain_body or comment.body),
                    public=comment.public,
                    created_at=comment.created_at,
                )
                for comment in comments.comments
            ],
        )
    return view.model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_ticket",
    display_name="Create Zendesk Ticket",
    description=(
        "Raise a ticket. The requester is given by email and is created in "
        "Zendesk if not already known, so a person's numeric id never has to "
        "be looked up first."
    ),
    input_model=CreateTicketInput,
    effect=ToolEffect.MUTATION,
)
async def create_ticket(
    payload: CreateTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    requester = None
    if payload.requester_email:
        # Zendesk creates or links the requester from this object, which is
        # why no separate user lookup is needed.
        requester = ZendeskRequester(
            email=payload.requester_email,
            name=payload.requester_name or None,
        )
    body = ZendeskCreateRequest(
        ticket=ZendeskCreateTicket(
            subject=payload.subject,
            comment=ZendeskInitialComment(body=payload.description),
            requester=requester,
            priority=payload.priority,
            tags=payload.tags or None,
        )
    )
    response = await ctx.mutate(
        TICKETS_PATH, json=body.model_dump(mode="json", exclude_none=True)
    )
    return _ticket_view(ticket_from_response(response)).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_comment",
    display_name="Comment on Zendesk Ticket",
    description=(
        "Add a comment to a ticket. Set public to true to reply to the "
        "customer — Zendesk emails them — or false to leave an internal note "
        "only agents can see. This argument is required precisely because "
        "sending a note to a customer by accident cannot be undone."
    ),
    input_model=AddCommentInput,
    effect=ToolEffect.MUTATION,
)
async def add_comment(
    payload: AddCommentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    body = ZendeskAddCommentRequest(
        ticket=ZendeskCommentUpdate(
            comment=ZendeskCommentRequest(body=payload.body, public=payload.public),
        )
    )
    response = await ctx.mutate(
        f"/tickets/{payload.ticket_id}.json",
        method=UPDATE_METHOD,
        json=body.model_dump(mode="json"),
    )
    updated = ticket_from_response(response, expected_id=payload.ticket_id)
    return ZendeskCommentResult(
        ticket_id=payload.ticket_id,
        public=payload.public,
        emailed_customer=payload.public,
        status=updated.status,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="update_ticket",
    display_name="Update Zendesk Ticket",
    description=(
        "Change a ticket's status, priority, assignee, or tags. The assignee "
        "is given by email and resolved here. Anything omitted is left alone, "
        "except tags, which replace what was there."
    ),
    input_model=UpdateTicketInput,
    effect=ToolEffect.MUTATION,
)
async def update_ticket(
    payload: UpdateTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    assignee_id = None
    if payload.assignee_email:
        user = await _user_by_email(ctx, payload.assignee_email)
        if user is None:
            raise VendorToolError(
                ZendeskToolErrorCode.ASSIGNEE_NOT_FOUND,
                "No Zendesk user matches that email.",
            )
        assignee_id = user.id
    ticket = ZendeskUpdateTicket(
        status=payload.status,
        priority=payload.priority,
        tags=payload.tags,
        assignee_id=assignee_id,
    )
    if all(
        value is None
        for value in (ticket.status, ticket.priority, ticket.tags, ticket.assignee_id)
    ):
        raise VendorToolError(
            ZendeskToolErrorCode.NO_CHANGE, "Give at least one field to change."
        )

    response = await ctx.mutate(
        f"/tickets/{payload.ticket_id}.json",
        method=UPDATE_METHOD,
        json=ZendeskUpdateRequest(ticket=ticket).model_dump(
            mode="json", exclude_none=True
        ),
    )
    updated = ticket_from_response(response, expected_id=payload.ticket_id)
    return _ticket_view(updated).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="find_user",
    display_name="Find Zendesk User",
    description=(
        "Look up a person by email, returning their id, name, role, and "
        "whether they are suspended. Other tools accept an email directly, so "
        "this is mainly for confirming who someone is."
    ),
    input_model=FindUserInput,
    effect=ToolEffect.READ,
)
async def find_user(
    payload: FindUserInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    user = await _user_by_email(ctx, payload.email)
    if user is None:
        return ZendeskMissingUser(email=payload.email).model_dump(mode="json")
    return ZendeskFoundUser(**user.model_dump()).model_dump(mode="json")


async def _user_by_email(ctx: VendorToolContext, email: str) -> ZendeskUser | None:
    response = await ctx.read(
        SEARCH_USERS_PATH, query=ZendeskUserQuery(query=email).model_dump(mode="json")
    )
    users = parse_response(response, ZendeskUsers)
    for user in users.users:
        if user.email is not None and user.email.casefold() == (
            email.strip().casefold()
        ):
            return user
    return None


def _ticket_view(ticket: ZendeskTicket) -> ZendeskTicketView:
    return ZendeskTicketView(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        requester_id=ticket.requester_id,
        assignee_id=ticket.assignee_id,
        tags=ticket.tags or [],
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        via=ticket.via.channel if ticket.via is not None else None,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


__all__ = [
    "add_comment",
    "create_ticket",
    "find_user",
    "get_ticket",
    "search_tickets",
    "update_ticket",
]
