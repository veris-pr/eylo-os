"""Curated Freshdesk tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, JsonValue, field_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    DEFAULT_TICKET_LIMIT,
    MAX_LIST_SCAN_PAGES,
    MAX_SEARCH_PAGES,
    MAX_TICKETS,
    SEARCH_PAGE_SIZE,
    FreshdeskConversationQuery,
    FreshdeskConversationReceipt,
    FreshdeskConversationSource,
    FreshdeskConversationView,
    FreshdeskConversations,
    FreshdeskCoverage,
    FreshdeskCreateTicketRequest,
    FreshdeskMessageResult,
    FreshdeskPriorityCode,
    FreshdeskPrivateNoteReceipt,
    FreshdeskPrivateNoteRequest,
    FreshdeskReplyRequest,
    FreshdeskSearchResult,
    FreshdeskStatusCode,
    FreshdeskTicket,
    FreshdeskTicketDetail,
    FreshdeskTicketListQuery,
    FreshdeskTicketQuery,
    FreshdeskTicketSearch,
    FreshdeskTicketSearchQuery,
    FreshdeskTicketView,
    FreshdeskTickets,
    FreshdeskToolErrorCode,
    FreshdeskUpdateTicketRequest,
    parse_response,
)

MAX_BODY_CHARS = 6_000


class _FreshdeskChoice(StrEnum):
    """Normalize the existing word-based tool inputs, not raw vendor codes."""

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        return next((choice for choice in cls if choice.value == normalized), None)


class FreshdeskStatus(_FreshdeskChoice):
    """Built-in ticket statuses accepted by the curated tools."""

    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class FreshdeskPriority(_FreshdeskChoice):
    """Ticket priority names shown to the agent."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


# https://developers.freshdesk.com/api/#tickets — Ticket Properties.
_STATUS_CODES = {
    FreshdeskStatus.OPEN: FreshdeskStatusCode.OPEN,
    FreshdeskStatus.PENDING: FreshdeskStatusCode.PENDING,
    FreshdeskStatus.RESOLVED: FreshdeskStatusCode.RESOLVED,
    FreshdeskStatus.CLOSED: FreshdeskStatusCode.CLOSED,
}
_PRIORITY_CODES = {
    FreshdeskPriority.LOW: FreshdeskPriorityCode.LOW,
    FreshdeskPriority.MEDIUM: FreshdeskPriorityCode.MEDIUM,
    FreshdeskPriority.HIGH: FreshdeskPriorityCode.HIGH,
    FreshdeskPriority.URGENT: FreshdeskPriorityCode.URGENT,
}
_STATUS_NAMES = {code.value: name.value for name, code in _STATUS_CODES.items()}
_PRIORITY_NAMES = {code.value: name.value for name, code in _PRIORITY_CODES.items()}


class SearchTicketsInput(BaseModel):
    requester_email: str | None = Field(
        default=None, description="Only tickets raised by this person."
    )
    status: FreshdeskStatus | None = Field(
        default=None, description="Only tickets with this built-in status."
    )
    priority: FreshdeskPriority | None = Field(
        default=None, description="Only tickets with this priority."
    )
    limit: int = Field(default=DEFAULT_TICKET_LIMIT, ge=1, le=MAX_TICKETS)

    @field_validator("status", "priority", mode="before")
    @classmethod
    def empty_filter_is_absent(cls, value: object) -> object:
        """Retain the existing empty-string omission; whitespace stays invalid."""
        return None if value == "" else value


class GetTicketInput(BaseModel):
    ticket_id: int = Field(ge=1)
    include_conversation: bool = Field(default=True)


class CreateTicketInput(BaseModel):
    subject: str = Field(min_length=1)
    description: str = Field(min_length=1, description="Body; HTML is accepted.")
    requester_email: str = Field(min_length=1, description="Who the ticket is for.")
    priority: FreshdeskPriority = Field(default=FreshdeskPriority.MEDIUM)
    status: FreshdeskStatus = Field(default=FreshdeskStatus.OPEN)
    tags: list[str] | None = None


class ReplyInput(BaseModel):
    ticket_id: int = Field(ge=1)
    body: str = Field(min_length=1, description="Message text; HTML is accepted.")


class UpdateTicketInput(BaseModel):
    ticket_id: int = Field(ge=1)
    status: FreshdeskStatus | None = Field(
        default=None, description="The built-in status to set."
    )
    priority: FreshdeskPriority | None = Field(default=None)

    @field_validator("status", "priority", mode="before")
    @classmethod
    def empty_change_is_absent(cls, value: object) -> object:
        """An empty optional choice does not request a field update."""
        return None if value == "" else value


@curated_tool(
    vendor=vendor.vendor,
    name="search_tickets",
    display_name="Search Freshdesk Tickets",
    description=(
        "Find tickets by requester, status, or priority, all given by name "
        "rather than by the integer codes Freshdesk stores. Results report "
        "built-in status and priority as words. Requester searches and unfiltered "
        "lists use Freshdesk's recent-ticket window (past 30 days); status/priority "
        "searches use its search index, which can lag updates. Coverage reports "
        "whether the query was exhausted, the result limit was reached, or the "
        "bounded page scan stopped. A null requester email is not a known email."
    ),
    input_model=SearchTicketsInput,
    effect=ToolEffect.READ,
)
async def search_tickets(
    payload: SearchTicketsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.requester_email or not (payload.status or payload.priority):
        result = await _list_tickets(payload, ctx)
    else:
        result = await _search_ticket_index(payload, ctx)
    return result.model_dump(mode="json")


async def _search_ticket_index(
    payload: SearchTicketsInput, ctx: VendorToolContext
) -> FreshdeskSearchResult:
    clauses: list[str] = []
    if payload.status:
        clauses.append(f"status:{_STATUS_CODES[payload.status].value}")
    if payload.priority:
        clauses.append(f"priority:{_PRIORITY_CODES[payload.priority].value}")
    tickets: list[FreshdeskTicket] = []
    coverage = FreshdeskCoverage.SCAN_LIMIT
    for page in range(1, MAX_SEARCH_PAGES + 1):
        query = FreshdeskTicketSearchQuery(
            query=f'"{" AND ".join(clauses)}"', page=page
        )
        response = await ctx.read(
            "/search/tickets", query=query.model_dump(mode="json")
        )
        body = parse_response(response, FreshdeskTicketSearch)
        tickets.extend(body.results)
        if len(tickets) >= payload.limit:
            coverage = FreshdeskCoverage.RESULT_LIMIT
            break
        if (
            len(body.results) < SEARCH_PAGE_SIZE
            or page * SEARCH_PAGE_SIZE >= body.total
        ):
            coverage = FreshdeskCoverage.EXHAUSTED
            break
    selected = [_ticket_view(ticket) for ticket in tickets[: payload.limit]]
    return FreshdeskSearchResult(
        tickets=selected, count=len(selected), coverage=coverage
    )


async def _list_tickets(
    payload: SearchTicketsInput, ctx: VendorToolContext
) -> FreshdeskSearchResult:
    """Filter a bounded requester list locally; email is not a search-index field.

    Requester embedding avoids one contact lookup per ticket. Do not claim an
    empty bounded scan proves that the requester has no matching older tickets.
    """
    status = _STATUS_CODES[payload.status] if payload.status else None
    priority = _PRIORITY_CODES[payload.priority] if payload.priority else None
    page_size = MAX_TICKETS if status or priority else payload.limit
    selected: list[FreshdeskTicketView] = []
    coverage = FreshdeskCoverage.SCAN_LIMIT
    for page in range(1, MAX_LIST_SCAN_PAGES + 1):
        query = FreshdeskTicketListQuery(
            per_page=page_size,
            page=page,
            email=payload.requester_email.strip() if payload.requester_email else None,
        )
        response = await ctx.read(
            "/tickets", query=query.model_dump(mode="json", exclude_none=True)
        )
        tickets = parse_response(response, FreshdeskTickets).root
        selected.extend(
            _ticket_view(ticket)
            for ticket in tickets
            if (status is None or ticket.status == status)
            and (priority is None or ticket.priority == priority)
        )
        if len(selected) >= payload.limit:
            coverage = FreshdeskCoverage.RESULT_LIMIT
            break
        if len(tickets) < page_size:
            coverage = FreshdeskCoverage.EXHAUSTED
            break
    selected = selected[: payload.limit]
    return FreshdeskSearchResult(
        tickets=selected, count=len(selected), coverage=coverage
    )


@curated_tool(
    vendor=vendor.vendor,
    name="get_ticket",
    display_name="Get Freshdesk Ticket",
    description=(
        "Read one ticket with its requester and, optionally, its first 30 "
        "conversation entries. Each message distinguishes an internal note "
        "from an outgoing customer reply; incoming messages and public notes "
        "are not labelled as sent replies."
    ),
    input_model=GetTicketInput,
    effect=ToolEffect.READ,
)
async def get_ticket(
    payload: GetTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.read(
        f"/tickets/{payload.ticket_id}",
        query=FreshdeskTicketQuery().model_dump(mode="json"),
    )
    ticket = parse_response(response, FreshdeskTicket)
    _check_ticket_id(ticket.id, payload.ticket_id)
    view = FreshdeskTicketDetail(
        **_ticket_view(ticket).model_dump(),
        description=_clip(ticket.description_text or ticket.description),
    )
    if payload.include_conversation:
        response = await ctx.read(
            f"/tickets/{payload.ticket_id}/conversations",
            query=FreshdeskConversationQuery().model_dump(mode="json"),
        )
        conversations = parse_response(response, FreshdeskConversations).root
        entries: list[FreshdeskConversationView] = []
        for item in conversations:
            _check_ticket_id(item.ticket_id, payload.ticket_id)
            entries.append(
                FreshdeskConversationView(
                    body=_clip(item.body_text or item.body),
                    from_email=item.from_email,
                    internal_note=item.private,
                    sent_to_customer=(
                        not item.private
                        and not item.incoming
                        and item.source == FreshdeskConversationSource.REPLY
                    ),
                    created_at=item.created_at,
                )
            )
        view.conversation = entries
    return view.model_dump(mode="json", by_alias=True, exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_ticket",
    display_name="Create Freshdesk Ticket",
    description=(
        "Open a ticket on behalf of a customer given by email. Status and "
        "priority are given by name and converted to Freshdesk's codes here."
    ),
    input_model=CreateTicketInput,
    effect=ToolEffect.MUTATION,
)
async def create_ticket(
    payload: CreateTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    body = FreshdeskCreateTicketRequest(
        subject=payload.subject,
        description=payload.description,
        email=payload.requester_email.strip(),
        status=_STATUS_CODES[payload.status],
        priority=_PRIORITY_CODES[payload.priority],
        tags=payload.tags or None,
    )
    response = await ctx.mutate(
        "/tickets", json=body.model_dump(mode="json", exclude_none=True)
    )
    return _ticket_view(parse_response(response, FreshdeskTicket)).model_dump(
        mode="json"
    )


@curated_tool(
    vendor=vendor.vendor,
    name="reply_to_customer",
    display_name="Reply to Freshdesk Customer",
    description=(
        "Send a reply on a ticket. This is EMAILED TO THE CUSTOMER and cannot "
        "be unsent. To record something only colleagues should see, use "
        "add_private_note instead."
    ),
    input_model=ReplyInput,
    effect=ToolEffect.MUTATION,
)
async def reply_to_customer(
    payload: ReplyInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    body = FreshdeskReplyRequest(body=payload.body)
    response = await ctx.mutate(
        f"/tickets/{payload.ticket_id}/reply", json=body.model_dump(mode="json")
    )
    reply = parse_response(response, FreshdeskConversationReceipt)
    _check_ticket_id(reply.ticket_id, payload.ticket_id)
    return FreshdeskMessageResult(
        ticket_id=reply.ticket_id,
        conversation_id=reply.id,
        sent_to_customer=True,
        created_at=reply.created_at,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_private_note",
    display_name="Add Freshdesk Private Note",
    description=(
        "Add an internal note to a ticket. This is NOT sent to the customer "
        "and is visible only to agents. To message the customer, use "
        "reply_to_customer instead."
    ),
    input_model=ReplyInput,
    effect=ToolEffect.MUTATION,
)
async def add_private_note(
    payload: ReplyInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    body = FreshdeskPrivateNoteRequest(body=payload.body)
    response = await ctx.mutate(
        f"/tickets/{payload.ticket_id}/notes",
        json=body.model_dump(mode="json"),
    )
    note = parse_response(response, FreshdeskPrivateNoteReceipt)
    _check_ticket_id(note.ticket_id, payload.ticket_id)
    return FreshdeskMessageResult(
        ticket_id=note.ticket_id,
        conversation_id=note.id,
        sent_to_customer=False,
        created_at=note.created_at,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="update_ticket",
    display_name="Update Freshdesk Ticket",
    description=(
        "Change a ticket's status or priority, given by name. Resolving or "
        "closing a ticket may trigger Freshdesk's own satisfaction survey to "
        "the customer, depending on how the account is configured."
    ),
    input_model=UpdateTicketInput,
    effect=ToolEffect.MUTATION,
)
async def update_ticket(
    payload: UpdateTicketInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.status is None and payload.priority is None:
        raise VendorToolError(
            FreshdeskToolErrorCode.NO_CHANGE, "Give a status or a priority to change."
        )
    body = FreshdeskUpdateTicketRequest(
        status=_STATUS_CODES[payload.status] if payload.status else None,
        priority=_PRIORITY_CODES[payload.priority] if payload.priority else None,
    )
    response = await ctx.mutate(
        f"/tickets/{payload.ticket_id}",
        method="PUT",
        json=body.model_dump(mode="json", exclude_none=True),
    )
    ticket = parse_response(response, FreshdeskTicket)
    _check_ticket_id(ticket.id, payload.ticket_id)
    return _ticket_view(ticket).model_dump(mode="json")


def _ticket_view(ticket: FreshdeskTicket) -> FreshdeskTicketView:
    return FreshdeskTicketView(
        id=ticket.id,
        subject=ticket.subject,
        status=_STATUS_NAMES.get(ticket.status, ticket.status),
        priority=_PRIORITY_NAMES.get(ticket.priority, ticket.priority),
        requester_email=ticket.requester.email if ticket.requester else None,
        tags=ticket.tags or [],
        type=ticket.type,
        due_by=ticket.due_by,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _clip(value: str | None) -> str | None:
    return value[:MAX_BODY_CHARS] if value is not None else None


def _check_ticket_id(actual: int, expected: int) -> None:
    if actual != expected:
        raise VendorToolError(
            FreshdeskToolErrorCode.RESPONSE_INVALID,
            "Freshdesk returned data for another ticket.",
        )


__all__ = [
    "add_private_note",
    "create_ticket",
    "get_ticket",
    "reply_to_customer",
    "search_tickets",
    "update_ticket",
]
