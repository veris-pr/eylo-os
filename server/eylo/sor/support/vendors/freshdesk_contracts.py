"""Freshdesk v2 wire contracts; custom fields retain their discovered JSON shape."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)

from eylo.sor.shared.json_values import SorJsonValue, require_json_object

FRESHDESK_IDENTIFIER_MAX_LENGTH = 512
FRESHDESK_MAX_PAGE_SIZE = 100


class FreshdeskTicketStatusCode(IntEnum):
    """Freshdesk's documented numeric ticket status codes."""

    OPEN = 2
    PENDING = 3
    RESOLVED = 4
    CLOSED = 5


class FreshdeskTicketPriorityCode(IntEnum):
    """Freshdesk's documented numeric ticket priority codes."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class FreshdeskTicketWriteField(StrEnum):
    """Native fields accepted after resolving the operator's writable mapping."""

    SUBJECT = "subject"
    DESCRIPTION = "description"
    REQUESTER_ID = "requester_id"
    RESPONDER_ID = "responder_id"
    GROUP_ID = "group_id"
    EMAIL_CONFIG_ID = "email_config_id"
    STATUS = "status"
    PRIORITY = "priority"
    TYPE = "type"
    TAGS = "tags"
    CUSTOM_FIELDS = "custom_fields"


class FreshdeskTagAction(StrEnum):
    """Explicit tag mutation; not a positional add/remove boolean."""

    ADD = "add"
    REMOVE = "remove"


class FreshdeskMutationInput(BaseModel):
    """No unknown native fields; serialize only explicitly supplied values."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class FreshdeskTicketUpdate(FreshdeskMutationInput):
    """Supported partial update; omitted and explicit null text stay distinct."""

    subject: str | None = Field(default=None, repr=False)
    description: str | None = Field(default=None, repr=False)
    requester_id: int | None = None
    responder_id: int | None = None
    group_id: int | None = None
    email_config_id: int | None = None
    status: FreshdeskTicketStatusCode | None = None
    priority: FreshdeskTicketPriorityCode | None = None
    type: str | None = None
    tags: list[str] | None = Field(default=None, repr=False)
    custom_fields: dict[str, SorJsonValue] | None = Field(default=None, repr=False)


class FreshdeskTicketCreate(FreshdeskTicketUpdate):
    """Eylo requires mapped requester, status and priority; no vendor defaults."""

    subject: str | None = Field(repr=False)
    description: str | None = Field(repr=False)
    requester_id: int
    status: FreshdeskTicketStatusCode
    priority: FreshdeskTicketPriorityCode


class FreshdeskReplyInput(FreshdeskMutationInput):
    """The existing HTML reply tool; no unsupported attachment/body variants."""

    body: str = Field(repr=False)


class FreshdeskNoteInput(FreshdeskReplyInput):
    """Private notes use the vendor's boolean wire field, not platform policy."""

    private: Literal[True]


def _identifier(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("Freshdesk identity must be an integer or string.")
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise ValueError("Freshdesk identity must be an integer or string.")
    return value.strip()


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Freshdesk timestamp must be an ISO timestamp.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Freshdesk timestamp requires a timezone.")
    return parsed.astimezone(timezone.utc)


FreshdeskIdentifier = Annotated[
    str,
    BeforeValidator(_identifier),
    Field(min_length=1, max_length=FRESHDESK_IDENTIFIER_MAX_LENGTH),
]
FreshdeskTimestamp = Annotated[datetime, BeforeValidator(_timestamp)]


class FreshdeskMutationRecord(BaseModel):
    """Consumed identity/revision only; unrelated native fields remain ignored."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )

    id: FreshdeskIdentifier
    updated_at: FreshdeskTimestamp | None = None


type FreshdeskWriteInput = (
    FreshdeskTicketUpdate | FreshdeskReplyInput | FreshdeskNoteInput
)


def _native_identifier(value: object) -> object:
    normalized = _identifier(value)
    if not normalized or len(normalized) > FRESHDESK_IDENTIFIER_MAX_LENGTH:
        raise ValueError("Freshdesk identity is empty or too long.")
    return value


def _native_timestamp(value: str) -> str:
    _timestamp(value)
    return value


FreshdeskNativeIdentifier = Annotated[int | str, BeforeValidator(_native_identifier)]
FreshdeskNativeTimestamp = Annotated[str, AfterValidator(_native_timestamp)]


class FreshdeskNativeModel(BaseModel):
    """Validate consumed native fields without discarding future source content."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="allow", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def json_response(cls, value: object) -> object:
        """Validate retained extras without overriding Pydantic's internal storage."""
        if isinstance(value, cls):
            return value
        return require_json_object(value)


class FreshdeskNativeRecord(FreshdeskNativeModel):
    """Preserve native identity representation until canonical projection."""

    id: FreshdeskNativeIdentifier

    @property
    def external_id(self) -> str:
        return _identifier(self.id)


class FreshdeskDatedRecord(FreshdeskNativeRecord):
    """Source timestamps retain their spelling; watermarks parse them explicitly."""

    created_at: FreshdeskNativeTimestamp | None = None
    updated_at: FreshdeskNativeTimestamp | None = None


class FreshdeskTicketStats(FreshdeskNativeModel):
    """Consumed stats expansion, not an invented complete SLA response."""

    first_responded_at: FreshdeskNativeTimestamp | None = None
    resolved_at: FreshdeskNativeTimestamp | None = None
    closed_at: FreshdeskNativeTimestamp | None = None


class FreshdeskTicket(FreshdeskDatedRecord):
    """Ticket fields consumed by projection, child expansion and mutation preflight."""

    subject: str | None = None
    description: str | None = Field(default=None, repr=False)
    description_text: str | None = Field(default=None, repr=False)
    requester_id: FreshdeskNativeIdentifier | None = None
    responder_id: FreshdeskNativeIdentifier | None = None
    group_id: FreshdeskNativeIdentifier | None = None
    email_config_id: FreshdeskNativeIdentifier | None = None
    status: int | str | None = None
    priority: int | str | None = None
    source: int | str | None = None
    type: str | None = None
    tags: list[str] | None = None
    stats: FreshdeskTicketStats | None = None
    custom_fields: dict[str, SorJsonValue] | None = Field(default=None, repr=False)
    fr_due_by: FreshdeskNativeTimestamp | None = None
    due_by: FreshdeskNativeTimestamp | None = None
    fr_escalated: bool | None = None
    is_escalated: bool | None = None


class FreshdeskAvatar(FreshdeskNativeModel):
    """The nested avatar URL consumed from an agent contact."""

    avatar_url: str | None = None


class FreshdeskAgentContact(FreshdeskNativeModel):
    """Embedded contact does not require a separately selected contact ID."""

    name: str | None = None
    email: str | None = None
    active: bool | None = None
    avatar: FreshdeskAvatar | None = None


class FreshdeskAgent(FreshdeskNativeRecord):
    """Agent verification and directory projection share one native structure."""

    contact: FreshdeskAgentContact | None = None
    name: str | None = None
    email: str | None = None
    active: bool | None = None
    occasional: bool | None = None


class FreshdeskContact(FreshdeskDatedRecord):
    """Customer fields and discovered custom values."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    company_id: FreshdeskNativeIdentifier | None = None
    active: bool | None = None
    custom_fields: dict[str, SorJsonValue] | None = Field(default=None, repr=False)


class FreshdeskGroup(FreshdeskDatedRecord):
    """Support queue projection from a native group."""

    name: str | None = None
    description: str | None = None
    deleted: bool | None = None


class FreshdeskEmailConfig(FreshdeskNativeRecord):
    """Native inbox label and availability."""

    name: str | None = None
    reply_email: str | None = None
    email: str | None = None
    active: bool | None = None


class FreshdeskAttachment(FreshdeskNativeRecord):
    """Conversation attachment metadata; file contents are not fetched here."""

    name: str | None = None
    content_type: str | None = None
    size: int | None = None
    attachment_url: str | None = None


class FreshdeskConversation(FreshdeskDatedRecord):
    """Native conversation plus retained extra JSON for source-body inspection."""

    body: str | None = Field(default=None, repr=False)
    body_text: str | None = Field(default=None, repr=False)
    private: bool | None = None
    incoming: bool | None = None
    user_id: FreshdeskNativeIdentifier | None = None
    from_email: str | None = None
    attachments: list[FreshdeskAttachment] | None = Field(default=None, repr=False)


class FreshdeskCompany(FreshdeskDatedRecord):
    """Company properties remain discovered data, separate from known metadata."""

    custom_fields: dict[str, SorJsonValue] | None = Field(default=None, repr=False)


class FreshdeskCustomRecord(FreshdeskNativeModel):
    """Native custom-object envelope; data keys belong to the source schema."""

    display_id: FreshdeskNativeIdentifier
    created_time: int | FiniteFloat | None = None
    updated_time: int | FiniteFloat | None = None
    data: dict[str, SorJsonValue] = Field(repr=False)


class FreshdeskFieldDefinition(FreshdeskNativeModel):
    """Native discovered field, including optional visibility/edit predicates."""

    name: str | None = None
    label: str | None = None
    type: str | None = None
    default: bool | None = None
    required_for_agents: bool | None = None
    agents_can_edit: bool | None = None
    required: bool | None = None
    deleted: bool | None = None
    visible: bool | None = None
    choices: SorJsonValue = Field(default=None, repr=False)


class FreshdeskCustomSchema(FreshdeskNativeRecord):
    """One dynamically discovered custom-object schema."""

    name: str | None = None
    deleted: bool | None = None
    fields: list[FreshdeskFieldDefinition] | None = None


class FreshdeskCustomSchemas(FreshdeskNativeModel):
    """The custom-object discovery envelope."""

    schemas: list[FreshdeskCustomSchema] | None = None


class FreshdeskLink(FreshdeskNativeModel):
    """Some native continuation links are objects rather than strings."""

    href: str | None = None


class FreshdeskLinks(FreshdeskNativeModel):
    """Only next controls forward iteration; other links remain native metadata."""

    next: FreshdeskLink | str | None = None


class FreshdeskCustomRecords(FreshdeskNativeModel):
    """Custom-record page; continuation still passes the existing path fence."""

    records: list[FreshdeskCustomRecord] | None = None
    links: FreshdeskLinks | None = Field(default=None, alias="_links")


class FreshdeskFieldChoice(FreshdeskNativeModel):
    """Consumed label alternatives inside discovered list-form choices."""

    value: str | None = None
    label: str | None = None


class FreshdeskConversationRow(FreshdeskMutationInput):
    """Parent identity belongs to the expansion, not injected native JSON keys."""

    ticket_id: str
    conversation: FreshdeskConversation = Field(repr=False)


class FreshdeskAttachmentRow(FreshdeskMutationInput):
    """Two explicit owners for an expanded attachment."""

    ticket_id: str
    conversation_id: str
    attachment: FreshdeskAttachment = Field(repr=False)


class FreshdeskTag(FreshdeskMutationInput):
    """Derived tag identity from native ticket tag arrays."""

    name: str


class FreshdeskSlaMetricKind(StrEnum):
    FIRST_RESPONSE = "first_response"
    RESOLUTION = "resolution"


class FreshdeskSlaMetricState(StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    BREACHED = "breached"


class FreshdeskSlaMetricRow(FreshdeskMutationInput):
    """Derived metric carries typed evidence rather than underscore-prefixed keys."""

    ticket_id: str
    metric: FreshdeskSlaMetricKind
    state: FreshdeskSlaMetricState
    target_at: FreshdeskNativeTimestamp | None
    achieved_at: FreshdeskNativeTimestamp | None
    breached_at: FreshdeskNativeTimestamp | None
    updated_at: FreshdeskNativeTimestamp | None


class FreshdeskInclude(StrEnum):
    STATS = "stats"


class FreshdeskSortField(StrEnum):
    UPDATED_AT = "updated_at"


class FreshdeskSortDirection(StrEnum):
    ASC = "asc"


class FreshdeskPageQuery(FreshdeskMutationInput):
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=FRESHDESK_MAX_PAGE_SIZE)


class FreshdeskUpdatedQuery(FreshdeskPageQuery):
    updated_since: FreshdeskNativeTimestamp
    include: FreshdeskInclude | None = None
    order_by: FreshdeskSortField | None = None
    order_type: FreshdeskSortDirection | None = None


class FreshdeskTicketQuery(FreshdeskMutationInput):
    include: FreshdeskInclude


class FreshdeskCustomPageQuery(FreshdeskMutationInput):
    page_size: int = Field(ge=1, le=FRESHDESK_MAX_PAGE_SIZE)


type FreshdeskReadRecord = (
    FreshdeskTicket
    | FreshdeskContact
    | FreshdeskAgent
    | FreshdeskGroup
    | FreshdeskEmailConfig
    | FreshdeskCompany
    | FreshdeskCustomRecord
    | FreshdeskConversationRow
    | FreshdeskAttachmentRow
    | FreshdeskTag
    | FreshdeskSlaMetricRow
)
