"""Intercom 2.11 wire contracts and curated projections, not SOR entities.

Responses validate consumed fields and ignore unrelated vendor extensions.
Requests are closed. Native open vocabularies (roles, author and part types)
remain strings; finite request choices have vendor-owned enums.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_BODY_CHARS = 6_000
MAX_PARTS = 50
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
CONTACT_LOOKUP_LIMIT = 1
SEARCH_METHOD = "POST"
CONTACT_SEARCH_PATH = "/contacts/search"
CONVERSATION_SEARCH_PATH = "/conversations/search"
ERROR_LIST_TYPE = "error.list"


class IntercomConversationState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    SNOOZED = "snoozed"

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().casefold()
        return next((state for state in cls if state.value == normalized), None)


class IntercomMessageType(StrEnum):
    COMMENT = "comment"
    NOTE = "note"


class IntercomSearchField(StrEnum):
    EMAIL = "email"
    CONTACT_IDS = "contact_ids"
    STATE = "state"


class IntercomToolErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SEARCH_UNBOUNDED = "search_unbounded"


class IntercomModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class IntercomRequest(IntercomModel):
    model_config = ConfigDict(extra="forbid")


class IntercomFilter(IntercomRequest):
    field: IntercomSearchField
    operator: Literal["="] = "="
    value: str


class IntercomFilterGroup(IntercomRequest):
    operator: Literal["AND"] = "AND"
    value: list[IntercomFilter] = Field(min_length=2, max_length=2)


class IntercomPagination(IntercomRequest):
    per_page: int = Field(ge=1, le=MAX_SEARCH_LIMIT)


class IntercomSearchRequest(IntercomRequest):
    query: IntercomFilter | IntercomFilterGroup
    pagination: IntercomPagination


class IntercomConversationQuery(IntercomRequest):
    display_as: Literal["plaintext"] = "plaintext"


class IntercomReplyRequest(IntercomRequest):
    # Field order preserves existing mutation request fingerprints.
    type: Literal["admin"] = "admin"
    admin_id: str = Field(min_length=1)
    message_type: IntercomMessageType
    body: str = Field(min_length=1, repr=False)


class IntercomReference(IntercomModel):
    id: str = Field(min_length=1)


class IntercomCompanies(IntercomModel):
    data: list[IntercomReference] = Field(default_factory=list)


class IntercomContact(IntercomReference):
    name: str | None = Field(repr=False)
    email: str = Field(repr=False)
    phone: str | None = Field(repr=False)
    role: str
    last_seen_at: int | None
    created_at: int
    companies: IntercomCompanies | None = None


class IntercomContactSearch(IntercomModel):
    data: list[IntercomContact]


class IntercomContacts(IntercomModel):
    contacts: list[IntercomReference]


class IntercomAuthor(IntercomModel):
    type: str
    name: str | None = Field(repr=False)
    email: str = Field(repr=False)


class IntercomSource(IntercomModel):
    author: IntercomAuthor
    body: str | None = Field(default=None, repr=False)


class IntercomPart(IntercomSource):
    part_type: str
    created_at: int


class IntercomParts(IntercomModel):
    conversation_parts: list[IntercomPart]
    total_count: int = Field(ge=0)


class IntercomConversation(IntercomReference):
    title: str | None = Field(repr=False)
    # Responses retain unknown native values; requests accept only known states.
    state: IntercomConversationState | str
    open: bool
    read: bool
    priority: str | None = None
    admin_assignee_id: int | None
    contacts: IntercomContacts
    created_at: int
    updated_at: int


class IntercomConversationDetail(IntercomConversation):
    source: IntercomSource
    conversation_parts: IntercomParts


class IntercomConversationSearch(IntercomModel):
    conversations: list[IntercomConversation]
    total_count: int = Field(ge=0)


class IntercomReply(IntercomReference):
    state: IntercomConversationState | str


class IntercomEnvelope(IntercomModel):
    type: str | None = None


class IntercomContactView(IntercomModel):
    id: str
    name: str | None
    email: str
    phone: str | None
    role: str
    last_seen_at: int | None
    created_at: int
    company_count: int
    found: Literal[True] = True


class IntercomMissingContact(IntercomModel):
    found: Literal[False] = False
    email: str


class IntercomConversationView(IntercomModel):
    id: str
    title: str | None
    state: IntercomConversationState | str
    open: bool
    read: bool
    priority: str | None
    assignee_id: int | None
    contact_ids: list[str]
    created_at: int
    updated_at: int


class IntercomSearchResult(IntercomModel):
    conversations: list[IntercomConversationView]
    count: int
    total_matches: int | None = None
    contact_found: Literal[False] | None = None


class IntercomMessageView(IntercomModel):
    author: IntercomAuthor
    body: str | None
    visible_to_customer: bool
    created_at: int
    is_opening_message: bool


class IntercomConversationDetailView(IntercomConversationView):
    messages: list[IntercomMessageView]
    message_count: int


class IntercomReplyResult(IntercomModel):
    conversation_id: str
    message_type: IntercomMessageType
    visible_to_customer: bool
    state: IntercomConversationState | str


def parse_response[T: BaseModel](response: VendorResponse, schema: type[T]) -> T:
    """Reject malformed replies without echoing vendor diagnostics or retrying."""
    if not response.ok:
        raise VendorToolError(
            IntercomToolErrorCode.REJECTED, "Intercom rejected the request."
        )
    try:
        envelope = IntercomEnvelope.model_validate(response.data)
        if envelope.type == ERROR_LIST_TYPE:
            raise VendorToolError(
                IntercomToolErrorCode.REJECTED, "Intercom rejected the request."
            )
        return schema.model_validate(response.data)
    except ValidationError:
        raise VendorToolError(
            IntercomToolErrorCode.RESPONSE_INVALID,
            "Intercom returned an unexpected response.",
        ) from None


def require_conversation_identity(actual_id: str, expected_id: str) -> None:
    if actual_id != expected_id:
        raise VendorToolError(
            IntercomToolErrorCode.RESPONSE_INVALID,
            "Intercom returned another conversation.",
        )
