"""Zendesk ticket mutation wire contracts; custom values remain source-owned JSON."""

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


class ZendeskMutationResponse(BaseModel):
    """Consume identity evidence; other vendor response fields stay in the adapter."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class ZendeskTicketResult(ZendeskMutationResponse):
    id: ZendeskIdentifier
    updated_at: ZendeskTimestamp | None = None


class ZendeskTicketResponse(ZendeskMutationResponse):
    ticket: ZendeskTicketResult


class ZendeskAuditEvent(ZendeskMutationResponse):
    """Non-comment events remain valid; only exact comment evidence is selected."""

    type: str | None = None
    id: ZendeskIdentifier | None = None
    public: bool | None = None


class ZendeskAudit(ZendeskMutationResponse):
    events: list[ZendeskAuditEvent]


class ZendeskCommentResponse(ZendeskMutationResponse):
    audit: ZendeskAudit
