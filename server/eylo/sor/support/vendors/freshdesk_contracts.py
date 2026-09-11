"""Freshdesk v2 mutation wire contracts; custom fields remain discovered JSON."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from eylo.sor.shared.json_values import SorJsonValue

FRESHDESK_IDENTIFIER_MAX_LENGTH = 512


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


class FreshdeskTicketTags(FreshdeskMutationRecord):
    """Read-before-write tag state; null/missing both mean no tags."""

    tags: list[str] | None = Field(default=None, repr=False)


type FreshdeskWriteInput = FreshdeskTicketUpdate | FreshdeskReplyInput | FreshdeskNoteInput
