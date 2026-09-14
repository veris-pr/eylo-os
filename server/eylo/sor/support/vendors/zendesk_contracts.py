"""Zendesk native wire contracts; custom values remain source-owned JSON."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)

from eylo.sor.shared.json_values import SorJsonValue

ZENDESK_IDENTIFIER_MAX_LENGTH = 512


class ZendeskTicketStatus(StrEnum):
    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    HOLD = "hold"
    SOLVED = "solved"
    CLOSED = "closed"


class ZendeskTicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ZendeskTicketType(StrEnum):
    PROBLEM = "problem"
    INCIDENT = "incident"
    QUESTION = "question"
    TASK = "task"


class ZendeskTicketWriteField(StrEnum):
    SUBJECT = "subject"
    DESCRIPTION = "description"
    REQUESTER_ID = "requester_id"
    ASSIGNEE_ID = "assignee_id"
    GROUP_ID = "group_id"
    BRAND_ID = "brand_id"
    STATUS = "status"
    PRIORITY = "priority"
    TYPE = "type"
    TAGS = "tags"
    CUSTOM_FIELDS = "custom_fields"


class ZendeskTagAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"


class ZendeskAuditEventKind(StrEnum):
    COMMENT = "Comment"


def _identifier(value: object) -> object:
    """Validate native IDs without changing their existing string/integer encoding."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Zendesk identity must be a string or integer.")
    text = str(value).strip()
    if not text or len(text) > ZENDESK_IDENTIFIER_MAX_LENGTH:
        raise ValueError("Zendesk identity is empty or too long.")
    return value


def _timestamp(value: str) -> str:
    """Retain source spelling while refusing missing timezone information."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Zendesk timestamp requires a timezone.")
    return value


ZendeskIdentifier = Annotated[int | str, BeforeValidator(_identifier)]
ZendeskTimestamp = Annotated[str, AfterValidator(_timestamp)]


def _status(value: object) -> ZendeskTicketStatus:
    if not isinstance(value, str):
        raise ValueError("Zendesk ticket status must be a string.")
    return ZendeskTicketStatus(value)


def _priority(value: object) -> ZendeskTicketPriority:
    if not isinstance(value, str):
        raise ValueError("Zendesk ticket priority must be a string.")
    return ZendeskTicketPriority(value)


def _ticket_type(value: object) -> ZendeskTicketType:
    if not isinstance(value, str):
        raise ValueError("Zendesk ticket type must be a string.")
    return ZendeskTicketType(value)


class ZendeskWriteInput(BaseModel):
    """Only supplied fields serialize; unknown write fields are never forwarded."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class ZendeskSafeUpdate(ZendeskWriteInput):
    """The vendor's guard is an inseparable flag/timestamp pair, not two policies."""

    safe_update: Literal[True] | None = None
    updated_stamp: ZendeskTimestamp | None = None

    @model_validator(mode="after")
    def paired_revision(self) -> Self:
        if (self.safe_update is not None) != (self.updated_stamp is not None):
            raise ValueError("Zendesk safe update requires its revision timestamp.")
        return self


class ZendeskCommentInput(ZendeskWriteInput):
    body: str = Field(repr=False)
    public: bool


class ZendeskCustomFieldInput(ZendeskWriteInput):
    id: ZendeskIdentifier
    value: SorJsonValue = Field(repr=False)


class ZendeskTicketFields(ZendeskSafeUpdate):
    """Writable mapping output; explicit nulls remain distinct from omitted keys."""

    subject: str | None = None
    description: str | None = Field(default=None, repr=False)
    requester_id: ZendeskIdentifier | None = None
    assignee_id: ZendeskIdentifier | None = None
    group_id: ZendeskIdentifier | None = None
    brand_id: ZendeskIdentifier | None = None
    status: Annotated[ZendeskTicketStatus, BeforeValidator(_status)] | None = None
    priority: Annotated[ZendeskTicketPriority, BeforeValidator(_priority)] | None = None
    type: Annotated[ZendeskTicketType, BeforeValidator(_ticket_type)] | None = None
    tags: list[str] | None = None
    custom_fields: list[ZendeskCustomFieldInput] | None = Field(
        default=None, repr=False
    )
    comment: ZendeskCommentInput | None = Field(default=None, repr=False)


class ZendeskTicketRequest(ZendeskWriteInput):
    ticket: ZendeskTicketFields


class ZendeskTagsRequest(ZendeskSafeUpdate):
    tags: list[str]


class ZendeskResponse(BaseModel):
    """Validate consumed native fields; tolerate unrelated vendor extensions."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class ZendeskTicketResult(ZendeskResponse):
    id: ZendeskIdentifier
    updated_at: ZendeskTimestamp | None = None


class ZendeskTicketResponse(ZendeskResponse):
    ticket: ZendeskTicketResult


class ZendeskAuditEvent(ZendeskResponse):
    """Non-comment events remain valid; only exact comment evidence is selected."""

    type: str | None = None
    id: ZendeskIdentifier | None = None
    public: bool | None = None


class ZendeskAudit(ZendeskResponse):
    events: list[ZendeskAuditEvent]


class ZendeskCommentResponse(ZendeskResponse):
    audit: ZendeskAudit


ZENDESK_EXPORT_PAGE_SIZE = 1_000
ZENDESK_LIST_PAGE_SIZE = 100
ZENDESK_SYSTEM_ACTOR_ID = "-1"


class ZendeskUserRole(StrEnum):
    END_USER = "end-user"
    AGENT = "agent"
    ADMIN = "admin"


class ZendeskSupportTypeScope(StrEnum):
    ALL = "all"


class ZendeskInclude(StrEnum):
    COMMENT_EVENTS = "comment_events"


class ZendeskSort(StrEnum):
    CREATED_DESCENDING = "-created_at"


class ZendeskRecord(ZendeskResponse):
    """Record identity and optional native timestamps; wire spelling is preserved."""

    id: ZendeskIdentifier
    created_at: ZendeskTimestamp | None = None
    updated_at: ZendeskTimestamp | None = None


class ZendeskVia(ZendeskResponse):
    channel: str | None = None


class ZendeskCustomFieldValue(ZendeskResponse):
    id: ZendeskIdentifier
    value: SorJsonValue = Field(default=None, repr=False)


class ZendeskTicket(ZendeskRecord):
    """Read-side native states remain open; write-side choices are separately closed."""

    subject: str | None = None
    description: str | None = Field(default=None, repr=False)
    requester_id: ZendeskIdentifier | None = None
    assignee_id: ZendeskIdentifier | None = None
    group_id: ZendeskIdentifier | None = None
    brand_id: ZendeskIdentifier | None = None
    status: str | None = None
    priority: str | None = None
    type: str | None = None
    via: ZendeskVia | None = None
    tags: list[str]
    custom_fields: list[ZendeskCustomFieldValue] | None = Field(
        default=None, repr=False
    )
    solved_at: ZendeskTimestamp | None = None
    closed_at: ZendeskTimestamp | None = None


class ZendeskPhoto(ZendeskResponse):
    content_url: str | None = None


class ZendeskUser(ZendeskRecord):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    organization_id: ZendeskIdentifier | None = None
    role: str | None = None
    suspended: bool | None = None
    active: bool | None = None
    photo: ZendeskPhoto | None = None
    user_fields: dict[str, SorJsonValue] | None = Field(default=None, repr=False)


class ZendeskGroup(ZendeskRecord):
    name: str | None = None
    description: str | None = None
    deleted: bool | None = None
    url: str | None = None


class ZendeskBrand(ZendeskRecord):
    name: str | None = None
    active: bool | None = None
    url: str | None = None


class ZendeskAttachment(ZendeskResponse):
    id: ZendeskIdentifier
    file_name: str | None = None
    name: str | None = None
    content_type: str | None = None
    size: int | None = None
    content_url: str | None = None


class ZendeskTicketChildEvent(ZendeskResponse):
    """Only comment events are expanded; other native event kinds remain valid."""

    id: ZendeskIdentifier | None = None
    type: str | None = None
    event_type: str | None = None
    created_at: ZendeskTimestamp | None = None
    updated_at: ZendeskTimestamp | None = None
    public: bool | None = None
    author_id: ZendeskIdentifier | None = None
    html_body: str | None = Field(default=None, repr=False)
    plain_body: str | None = Field(default=None, repr=False)
    body: str | None = Field(default=None, repr=False)
    attachments: list[ZendeskAttachment] | None = None


class ZendeskComment(ZendeskTicketChildEvent):
    id: ZendeskIdentifier


class ZendeskTicketEvent(ZendeskResponse):
    ticket_id: ZendeskIdentifier
    child_events: list[ZendeskTicketChildEvent] | None = None


class ZendeskTag(ZendeskResponse):
    name: str


class ZendeskMetricBasis(StrEnum):
    BUSINESS = "business"
    CALENDAR = "calendar"


class ZendeskMetricUnit(StrEnum):
    MINUTES = "minutes"
    SECONDS = "seconds"


class ZendeskMetricName(StrEnum):
    AGENT_WAIT_TIME = "agent_wait_time"
    FIRST_RESOLUTION_TIME = "first_resolution_time"
    FULL_RESOLUTION_TIME = "full_resolution_time"
    ON_HOLD_TIME = "on_hold_time"
    REPLY_TIME = "reply_time"
    REPLY_TIME_IN_SECONDS = "reply_time_in_seconds"
    REQUESTER_WAIT_TIME = "requester_wait_time"


class ZendeskMetricMeasurement(ZendeskResponse):
    business: int | FiniteFloat | str | None = None
    calendar: int | FiniteFloat | str | None = None


class ZendeskTicketMetric(ZendeskRecord):
    ticket_id: ZendeskIdentifier
    solved_at: ZendeskTimestamp | None = None
    url: str | None = None
    agent_wait_time_in_minutes: ZendeskMetricMeasurement | None = None
    first_resolution_time_in_minutes: ZendeskMetricMeasurement | None = None
    full_resolution_time_in_minutes: ZendeskMetricMeasurement | None = None
    on_hold_time_in_minutes: ZendeskMetricMeasurement | None = None
    reply_time_in_minutes: ZendeskMetricMeasurement | None = None
    reply_time_in_seconds: ZendeskMetricMeasurement | None = None
    requester_wait_time_in_minutes: ZendeskMetricMeasurement | None = None

    def measurements(
        self,
    ) -> tuple[
        tuple[ZendeskMetricName, ZendeskMetricUnit, ZendeskMetricMeasurement | None],
        ...,
    ]:
        """Explicit native fields avoid a second dictionary-based schema."""
        return (
            (
                ZendeskMetricName.AGENT_WAIT_TIME,
                ZendeskMetricUnit.MINUTES,
                self.agent_wait_time_in_minutes,
            ),
            (
                ZendeskMetricName.FIRST_RESOLUTION_TIME,
                ZendeskMetricUnit.MINUTES,
                self.first_resolution_time_in_minutes,
            ),
            (
                ZendeskMetricName.FULL_RESOLUTION_TIME,
                ZendeskMetricUnit.MINUTES,
                self.full_resolution_time_in_minutes,
            ),
            (
                ZendeskMetricName.ON_HOLD_TIME,
                ZendeskMetricUnit.MINUTES,
                self.on_hold_time_in_minutes,
            ),
            (
                ZendeskMetricName.REPLY_TIME,
                ZendeskMetricUnit.MINUTES,
                self.reply_time_in_minutes,
            ),
            (
                ZendeskMetricName.REPLY_TIME_IN_SECONDS,
                ZendeskMetricUnit.SECONDS,
                self.reply_time_in_seconds,
            ),
            (
                ZendeskMetricName.REQUESTER_WAIT_TIME,
                ZendeskMetricUnit.MINUTES,
                self.requester_wait_time_in_minutes,
            ),
        )


class ZendeskCommentRow(ZendeskWriteInput):
    """Parent identity comes from export/exact context, never hidden native keys."""

    ticket_id: str
    comment: ZendeskComment = Field(repr=False)


class ZendeskAttachmentRow(ZendeskWriteInput):
    ticket_id: str
    comment_id: str
    attachment: ZendeskAttachment


class ZendeskMetricRow(ZendeskWriteInput):
    source: ZendeskTicketMetric
    metric: ZendeskMetricName
    basis: ZendeskMetricBasis
    unit: ZendeskMetricUnit
    value: str


class ZendeskTicketReadResponse(ZendeskResponse):
    ticket: ZendeskTicket


class ZendeskUserResponse(ZendeskResponse):
    user: ZendeskUser


class ZendeskGroupResponse(ZendeskResponse):
    group: ZendeskGroup


class ZendeskBrandResponse(ZendeskResponse):
    brand: ZendeskBrand


class ZendeskAttachmentResponse(ZendeskResponse):
    attachment: ZendeskAttachment


class ZendeskMetricResponse(ZendeskResponse):
    ticket_metric: ZendeskTicketMetric | list[ZendeskTicketMetric]


class ZendeskExportResponse(ZendeskResponse):
    end_of_stream: bool
    after_cursor: str | None = None


class ZendeskTicketExport(ZendeskExportResponse):
    tickets: list[ZendeskTicket]


class ZendeskUserExport(ZendeskExportResponse):
    users: list[ZendeskUser]


class ZendeskEventExport(ZendeskResponse):
    ticket_events: list[ZendeskTicketEvent]
    end_time: int
    end_of_stream: bool


class ZendeskPageMeta(ZendeskResponse):
    has_more: bool
    after_cursor: str | None = None


class ZendeskPage(ZendeskResponse):
    meta: ZendeskPageMeta


class ZendeskGroupsPage(ZendeskPage):
    groups: list[ZendeskGroup]


class ZendeskBrandsPage(ZendeskPage):
    brands: list[ZendeskBrand]


class ZendeskTagsPage(ZendeskPage):
    tags: list[ZendeskTag | str]


class ZendeskMetricsPage(ZendeskPage):
    ticket_metrics: list[ZendeskTicketMetric]


class ZendeskCommentsPage(ZendeskPage):
    comments: list[ZendeskComment]


class ZendeskFieldOption(ZendeskResponse):
    value: str | None = None


class ZendeskTicketField(ZendeskResponse):
    id: ZendeskIdentifier
    title: str | None = None
    type: str | None = None
    removable: bool | None = None
    required: bool | None = None
    agent_can_edit: bool | None = None
    agent_description: str | None = None
    description: str | None = None
    custom_field_options: list[ZendeskFieldOption] | None = None


class ZendeskTicketFieldsResponse(ZendeskResponse):
    ticket_fields: list[ZendeskTicketField] | None = None
    ticket_field: list[ZendeskTicketField] | None = None


class ZendeskExportQuery(ZendeskWriteInput):
    per_page: int = Field(ge=1, le=ZENDESK_EXPORT_PAGE_SIZE)
    start_time: int | None = None
    cursor: str | None = None
    exclude_deleted: bool | None = None
    support_type_scope: ZendeskSupportTypeScope | None = None

    @model_validator(mode="after")
    def export_position(self) -> Self:
        if (self.start_time is None) == (self.cursor is None):
            raise ValueError("Zendesk export requires exactly one position.")
        return self


class ZendeskEventQuery(ZendeskWriteInput):
    include: ZendeskInclude
    per_page: int = Field(ge=1, le=ZENDESK_EXPORT_PAGE_SIZE)
    start_time: int
    support_type_scope: ZendeskSupportTypeScope


class ZendeskPageQuery(ZendeskWriteInput):
    size: int = Field(serialization_alias="page[size]", ge=1, le=ZENDESK_LIST_PAGE_SIZE)
    after: str | None = Field(default=None, serialization_alias="page[after]")
    sort: ZendeskSort | None = None


type ZendeskReadRecord = (
    ZendeskTicket
    | ZendeskUser
    | ZendeskGroup
    | ZendeskBrand
    | ZendeskTag
    | ZendeskCommentRow
    | ZendeskAttachmentRow
    | ZendeskMetricRow
)
