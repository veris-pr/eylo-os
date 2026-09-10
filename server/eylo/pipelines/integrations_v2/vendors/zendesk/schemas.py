"""Zendesk v2 wire values and curated projections, separate from SOR entities.

Only consumed native fields are modeled. Unknown response extensions are ignored;
outbound fields are closed. Dates retain their wire spelling and native status,
priority, role and channel strings remain readable when Zendesk adds values.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_BODY_CHARS = 6_000
MAX_COMMENTS = 30
DEFAULT_TICKET_LIMIT = 25
MAX_TICKET_LIMIT = 100
SEARCH_TICKETS_PATH = "/search.json"
SEARCH_USERS_PATH = "/users/search.json"
TICKETS_PATH = "/tickets.json"
TICKET_SEARCH_TERM = "type:ticket"
UPDATE_METHOD = "PUT"


class ZendeskStatus(StrEnum):
    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    HOLD = "hold"
    SOLVED = "solved"
    CLOSED = "closed"


class ZendeskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ZendeskToolErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    ASSIGNEE_NOT_FOUND = "assignee_not_found"
    NO_CHANGE = "no_change_requested"


class ZendeskModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class ZendeskRequest(ZendeskModel):
    model_config = ConfigDict(extra="forbid")


class ZendeskVia(ZendeskModel):
    channel: str | None = None


class ZendeskTicket(ZendeskModel):
    id: int = Field(ge=1)
    status: str
    requester_id: int = Field(ge=1)
    subject: str | None = Field(default=None, repr=False)
    priority: str | None = None
    assignee_id: int | None = Field(default=None, ge=1)
    tags: list[str] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    via: ZendeskVia | None = None
    description: str | None = Field(default=None, repr=False)


class ZendeskTicketEnvelope(ZendeskModel):
    ticket: ZendeskTicket


class ZendeskTicketSearch(ZendeskModel):
    results: list[ZendeskTicket]
    count: int = Field(ge=0)
    next_page: str | None = None


class ZendeskComment(ZendeskModel):
    id: int = Field(ge=1)
    author_id: int | None = Field(default=None, ge=1)
    body: str | None = Field(default=None, repr=False)
    plain_body: str | None = Field(default=None, repr=False)
    public: bool
    created_at: str | None = None


class ZendeskComments(ZendeskModel):
    comments: list[ZendeskComment]
    next_page: str | None = None


class ZendeskUser(ZendeskModel):
    id: int = Field(ge=1)
    name: str | None = Field(default=None, repr=False)
    email: str | None = Field(default=None, repr=False)
    role: str | None = None
    suspended: bool | None = None
    created_at: str | None = None


class ZendeskUsers(ZendeskModel):
    users: list[ZendeskUser]
    next_page: str | None = None


class ZendeskErrorEnvelope(ZendeskModel):
    """Diagnostics are opaque and never become agent-visible error text."""

    error: JsonValue = Field(default=None, repr=False, exclude=True)


class ZendeskSearchQuery(ZendeskRequest):
    query: str
    per_page: int = Field(ge=1, le=MAX_TICKET_LIMIT)


class ZendeskUserQuery(ZendeskRequest):
    query: str


class ZendeskCommentsQuery(ZendeskRequest):
    per_page: int = MAX_COMMENTS


class ZendeskRequester(ZendeskRequest):
    email: str
    name: str | None = None


class ZendeskInitialComment(ZendeskRequest):
    body: str = Field(repr=False)


class ZendeskCommentRequest(ZendeskInitialComment):
    # Required native predicate. Preserve the existing public tool argument.
    public: bool


class ZendeskCreateTicket(ZendeskRequest):
    # Preserve the previous field order for outbound request fingerprints.
    subject: str
    comment: ZendeskInitialComment
    requester: ZendeskRequester | None = None
    priority: ZendeskPriority | None = None
    tags: list[str] | None = None


class ZendeskUpdateTicket(ZendeskRequest):
    status: ZendeskStatus | None = None
    priority: ZendeskPriority | None = None
    tags: list[str] | None = None
    assignee_id: int | None = Field(default=None, ge=1)


class ZendeskCommentUpdate(ZendeskRequest):
    comment: ZendeskCommentRequest


class ZendeskCreateRequest(ZendeskRequest):
    ticket: ZendeskCreateTicket


class ZendeskUpdateRequest(ZendeskRequest):
    ticket: ZendeskUpdateTicket


class ZendeskAddCommentRequest(ZendeskRequest):
    ticket: ZendeskCommentUpdate


class ZendeskTicketView(ZendeskModel):
    id: int
    subject: str | None
    status: str
    priority: str | None
    requester_id: int
    assignee_id: int | None
    tags: list[str]
    created_at: str | None
    updated_at: str | None
    via: str | None


class ZendeskCommentView(ZendeskModel):
    id: int
    author_id: int | None
    body: str | None
    public: bool
    created_at: str | None


class ZendeskTicketDetail(ZendeskTicketView):
    description: str | None
    comments: list[ZendeskCommentView] | None = None


class ZendeskSearchResult(ZendeskModel):
    tickets: list[ZendeskTicketView]
    count: int
    total_matches: int
    query: str


class ZendeskCommentResult(ZendeskModel):
    ticket_id: int
    public: bool
    # Legacy result key reflects the requested visibility, not delivery evidence.
    emailed_customer: bool
    status: str


class ZendeskFoundUser(ZendeskUser):
    found: Literal[True] = True


class ZendeskMissingUser(ZendeskModel):
    found: Literal[False] = False
    email: str


def parse_response[T: BaseModel](response: VendorResponse, schema: type[T]) -> T:
    """Fail malformed replies once; never retry an accepted external mutation."""
    if not response.ok:
        raise VendorToolError(
            ZendeskToolErrorCode.REJECTED, "Zendesk rejected the request."
        )
    try:
        envelope = ZendeskErrorEnvelope.model_validate(response.data)
        if envelope.error is not None:
            raise VendorToolError(
                ZendeskToolErrorCode.REJECTED, "Zendesk rejected the request."
            )
        return schema.model_validate(response.data)
    except ValidationError:
        raise VendorToolError(
            ZendeskToolErrorCode.RESPONSE_INVALID,
            "Zendesk returned an unexpected response.",
        ) from None


def ticket_from_response(
    response: VendorResponse, *, expected_id: int | None = None
) -> ZendeskTicket:
    ticket = parse_response(response, ZendeskTicketEnvelope).ticket
    if expected_id is not None and ticket.id != expected_id:
        raise VendorToolError(
            ZendeskToolErrorCode.RESPONSE_INVALID,
            "Zendesk returned another ticket.",
        )
    return ticket
