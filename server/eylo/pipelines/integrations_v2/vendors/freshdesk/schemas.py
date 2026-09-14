"""Freshdesk v2 wire contracts and curated results, not platform SOR entities.

Field authority: https://developers.freshdesk.com/api/ (tickets, embedding,
conversations, errors, pagination). Only consumed fields are modeled; unrelated
vendor fields are ignored. Timestamps retain their original wire representation.
"""

from enum import IntEnum, StrEnum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

DEFAULT_TICKET_LIMIT = 25
MAX_TICKETS = 100
SEARCH_PAGE_SIZE = 30
MAX_SEARCH_QUERY_CHARS = 512
MAX_SEARCH_PAGES = 10
MAX_LIST_SCAN_PAGES = 10
CONVERSATION_PAGE_SIZE = 30


class FreshdeskStatusCode(IntEnum):
    OPEN = 2
    PENDING = 3
    RESOLVED = 4
    CLOSED = 5


class FreshdeskPriorityCode(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class FreshdeskInclude(StrEnum):
    REQUESTER = "requester"


class FreshdeskConversationSource(IntEnum):
    REPLY = 0
    NOTE = 2
    TWEET = 5
    SURVEY = 6
    FACEBOOK = 7
    FORWARDED_EMAIL = 8
    PHONE = 9
    ECOMMERCE = 11


class FreshdeskCoverage(StrEnum):
    """Explain whether a bounded read exhausted its vendor query, not all tickets."""

    EXHAUSTED = "exhausted"
    RESULT_LIMIT = "result_limit"
    SCAN_LIMIT = "scan_limit"


class FreshdeskToolErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    NO_CHANGE = "no_change_requested"


class FreshdeskModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class FreshdeskRequest(FreshdeskModel):
    """Eylo constructs these fields; a misspelled outbound field is an error."""

    model_config = ConfigDict(extra="forbid", strict=True)


class FreshdeskRequester(FreshdeskModel):
    id: int = Field(ge=1)
    email: str | None = None


class FreshdeskTicket(FreshdeskModel):
    id: int = Field(ge=1)
    requester_id: int = Field(ge=1)
    subject: str | None = None
    # Preserve custom status codes; only outbound built-in choices are closed.
    status: int
    priority: int
    requester: FreshdeskRequester | None = None
    tags: list[str] | None = None
    type: str | None = None
    due_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    description_text: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def requester_belongs_to_ticket(self) -> Self:
        if self.requester is not None and self.requester.id != self.requester_id:
            raise ValueError("Embedded requester does not match ticket requester.")
        return self


class FreshdeskTickets(RootModel[list[FreshdeskTicket]]):
    model_config = ConfigDict(strict=True)


class FreshdeskTicketSearch(FreshdeskModel):
    total: int = Field(ge=0)
    results: list[FreshdeskTicket]


class FreshdeskConversationReceipt(FreshdeskModel):
    """Reply and note endpoints have different bodies but share these identifiers."""

    id: int = Field(ge=1)
    ticket_id: int = Field(ge=1)
    created_at: str | None = None


class FreshdeskConversation(FreshdeskConversationReceipt):
    private: bool
    incoming: bool
    # Unknown/new native sources remain readable without being called replies.
    source: int | None = None
    body_text: str | None = None
    body: str | None = None
    from_email: str | None = None


class FreshdeskPrivateNoteReceipt(FreshdeskConversationReceipt):
    """Do not confirm a private note when the vendor reports a public one."""

    private: bool

    @model_validator(mode="after")
    def note_is_private(self) -> Self:
        if not self.private:
            raise ValueError("Freshdesk did not confirm private note visibility.")
        return self


class FreshdeskConversations(RootModel[list[FreshdeskConversation]]):
    model_config = ConfigDict(strict=True)


class FreshdeskFieldError(FreshdeskModel):
    field: str | None = None
    message: str
    code: str


class FreshdeskErrorResponse(FreshdeskModel):
    description: str | None = None
    errors: list[FreshdeskFieldError]


class FreshdeskTicketQuery(FreshdeskRequest):
    include: FreshdeskInclude = FreshdeskInclude.REQUESTER


class FreshdeskTicketListQuery(FreshdeskTicketQuery):
    per_page: int = Field(ge=1, le=MAX_TICKETS)
    page: int = Field(default=1, ge=1, le=MAX_LIST_SCAN_PAGES)
    email: str | None = None


class FreshdeskTicketSearchQuery(FreshdeskRequest):
    query: str = Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS)
    page: int = Field(default=1, ge=1, le=MAX_SEARCH_PAGES)


class FreshdeskConversationQuery(FreshdeskRequest):
    per_page: int = CONVERSATION_PAGE_SIZE


class FreshdeskCreateTicketRequest(FreshdeskRequest):
    # Field order intentionally preserves existing outbound body fingerprints.
    subject: str
    description: str
    email: str
    status: FreshdeskStatusCode
    priority: FreshdeskPriorityCode
    tags: list[str] | None = None


class FreshdeskUpdateTicketRequest(FreshdeskRequest):
    status: FreshdeskStatusCode | None = None
    priority: FreshdeskPriorityCode | None = None


class FreshdeskReplyRequest(FreshdeskRequest):
    body: str


class FreshdeskPrivateNoteRequest(FreshdeskReplyRequest):
    # This is Freshdesk's wire predicate, not a platform visibility policy.
    private: Literal[True] = True


class FreshdeskTicketView(FreshdeskModel):
    id: int
    subject: str | None
    status: str | int
    priority: str | int
    requester_email: str | None
    tags: list[str]
    type: str | None
    due_by: str | None
    created_at: str | None
    updated_at: str | None


class FreshdeskConversationView(FreshdeskModel):
    body: str | None
    from_email: str | None = Field(serialization_alias="from")
    internal_note: bool
    sent_to_customer: bool
    created_at: str | None


class FreshdeskTicketDetail(FreshdeskTicketView):
    description: str | None
    conversation: list[FreshdeskConversationView] | None = None


class FreshdeskSearchResult(FreshdeskModel):
    tickets: list[FreshdeskTicketView]
    count: int
    coverage: FreshdeskCoverage


class FreshdeskMessageResult(FreshdeskModel):
    ticket_id: int
    conversation_id: int
    sent_to_customer: bool
    created_at: str | None


def parse_response[T: BaseModel](response: VendorResponse, schema: type[T]) -> T:
    """Validate once at the wire boundary; never expose payloads in error text.

    Mutations have already passed the outbound attempt owner before this runs.
    A schema mismatch is a tool error, not permission to send the effect again.
    """
    if not response.ok:
        raise VendorToolError(
            FreshdeskToolErrorCode.REJECTED, "Freshdesk rejected the request."
        )
    try:
        rejection = FreshdeskErrorResponse.model_validate(response.data)
    except ValidationError:
        rejection = None
    if rejection is not None and rejection.errors:
        raise VendorToolError(
            FreshdeskToolErrorCode.REJECTED, "Freshdesk rejected the request."
        )
    try:
        return schema.model_validate(response.data)
    except ValidationError as error:
        raise VendorToolError(
            FreshdeskToolErrorCode.RESPONSE_INVALID,
            "Freshdesk returned an unexpected response.",
        ) from error
