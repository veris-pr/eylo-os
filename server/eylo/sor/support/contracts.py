"""Typed support records preserving customer-visible and private semantics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from eylo.sor.shared.contracts import (
    SorCanonicalPayload,
    SorCanonicalRecord,
    SorCommandPayload,
    SorExternalRecord,
    SorLifecycleAdapter,
    SorMappedFieldsCommandPayload,
)
from eylo.sor.shared.json_values import SorJsonValue


class SupportTicketState(str, Enum):
    """Bounded platform state for a customer-support ticket."""

    NEW = "NEW"
    OPEN = "OPEN"
    PENDING = "PENDING"
    HOLD = "HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "SupportTicketState | None":
        if value is None:
            return None
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class SupportEntityKind(StrEnum):
    """Stable canonical customer-support entity vocabulary."""

    TICKET = "ticket"
    CUSTOMER = "customer"
    AGENT = "agent"
    QUEUE = "queue"
    INBOX = "inbox"
    MESSAGE = "message"
    TAG = "tag"
    SLA_METRIC = "sla_metric"
    ATTACHMENT = "attachment"


class SupportToolName(StrEnum):
    """Stable model-visible customer-support tool names."""

    FIND_CUSTOMER = "support_find_customer"
    FIND_TICKET = "support_find_ticket"
    GET_TICKET = "support_get_ticket"
    GET_CUSTOMER_HISTORY = "support_get_customer_history"
    LIST_QUEUES = "support_list_queues"
    DESCRIBE_TICKET_FIELDS = "support_describe_ticket_fields"
    OPEN_TICKET = "support_open_ticket"
    UPDATE_TICKET = "support_update_ticket"
    ASSIGN_TICKET = "support_assign_ticket"
    REPLY = "support_reply"
    ADD_NOTE = "support_add_note"
    CLOSE_TICKET = "support_close_ticket"
    ADD_TAG = "support_add_tag"
    REMOVE_TAG = "support_remove_tag"


class SupportMappedFieldsCommandPayload(SorMappedFieldsCommandPayload):
    """Mapped ticket fields for one open or update command."""


class SupportAssignCommandPayload(SorCommandPayload):
    """One assignee, queue, or both for a support ticket."""

    assignee_external_id: str | None = Field(default=None, min_length=1, max_length=320)
    group_external_id: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def require_assignment(self) -> "SupportAssignCommandPayload":
        if self.assignee_external_id is None and self.group_external_id is None:
            raise ValueError("A support assignment requires an assignee or group.")
        return self


class SupportMessageCommandPayload(SorCommandPayload):
    """One customer-visible reply or private support note."""

    normalized_text: str = Field(min_length=1, max_length=100_000)


class SupportCloseCommandPayload(SorCommandPayload):
    """Vendor-neutral close options interpreted by the selected source."""

    native_status: str | None = Field(default=None, min_length=1, max_length=128)
    normalized_text: str | None = Field(default=None, min_length=1, max_length=100_000)


class SupportTagCommandPayload(SorCommandPayload):
    """One exact source tag to add or remove."""

    tag_external_id: str = Field(min_length=1, max_length=320)


SUPPORT_COMMAND_PAYLOAD_TYPES: Mapping[SupportToolName, type[SorCommandPayload]] = {
    SupportToolName.OPEN_TICKET: SupportMappedFieldsCommandPayload,
    SupportToolName.UPDATE_TICKET: SupportMappedFieldsCommandPayload,
    SupportToolName.ASSIGN_TICKET: SupportAssignCommandPayload,
    SupportToolName.REPLY: SupportMessageCommandPayload,
    SupportToolName.ADD_NOTE: SupportMessageCommandPayload,
    SupportToolName.CLOSE_TICKET: SupportCloseCommandPayload,
    SupportToolName.ADD_TAG: SupportTagCommandPayload,
    SupportToolName.REMOVE_TAG: SupportTagCommandPayload,
}


class SupportMessageVisibility(str, Enum):
    """Whether a support message is customer-visible or private."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class SupportMessageDirection(str, Enum):
    """Bounded direction of a support conversation message."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "SupportMessageDirection | None":
        if value is None:
            return None
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class SupportSlaState(str, Enum):
    """Bounded platform state for one SLA measurement."""

    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    BREACHED = "BREACHED"
    PAUSED = "PAUSED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "SupportSlaState | None":
        if value is None:
            return None
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class SupportTicketPayload(SorCanonicalPayload):
    subject: str | None = None
    normalized_description: str | None = None
    requester_external_id: str | None = None
    assignee_external_id: str | None = None
    group_external_id: str | None = None
    inbox_external_id: str | None = None
    native_status: str | None = None
    normalized_status: SupportTicketState | None = None
    priority: str | None = None
    category: str | None = None
    channel: str | None = None
    tag_external_ids: tuple[str, ...] = ()
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    sla_state: SupportSlaState | None = None


class SupportCustomerPayload(SorCanonicalPayload):
    name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    company_external_id: str | None = None
    active: bool | None = None


class SupportAgentPayload(SorCanonicalPayload):
    name: str
    primary_email: str | None = None
    active: bool | None = None
    assignable: bool | None = None
    avatar_url: str | None = None


class SupportMessagePayload(SorCanonicalPayload):
    ticket_external_id: str
    visibility: SupportMessageVisibility
    direction: SupportMessageDirection | None = None
    author_external_id: str | None = None
    normalized_text: str
    source_body: SorJsonValue = None
    body_format: str | None = None
    attachment_external_ids: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime | None = None


class SupportQueuePayload(SorCanonicalPayload):
    name: str
    description: str | None = None
    active: bool | None = None


class SupportInboxPayload(SorCanonicalPayload):
    name: str
    kind: str | None = None
    active: bool | None = None


class SupportTagPayload(SorCanonicalPayload):
    name: str


class SupportSlaMetricPayload(SorCanonicalPayload):
    ticket_external_id: str
    metric: str
    value: Decimal | None = None
    unit: str | None = None
    native_state: str | None = None
    normalized_state: SupportSlaState | None = None
    target_at: datetime | None = None
    achieved_at: datetime | None = None
    breached_at: datetime | None = None


class SupportAttachmentPayload(SorCanonicalPayload):
    ticket_external_id: str
    message_external_id: str | None = None
    name: str
    content_type: str | None = None
    size_bytes: int | None = None
    source_url: str | None = None


SupportPayload = (
    SupportTicketPayload
    | SupportCustomerPayload
    | SupportAgentPayload
    | SupportMessagePayload
    | SupportQueuePayload
    | SupportInboxPayload
    | SupportTagPayload
    | SupportSlaMetricPayload
    | SupportAttachmentPayload
)


SUPPORT_PAYLOAD_TYPES: Mapping[SupportEntityKind, type[SorCanonicalPayload]] = {
    SupportEntityKind.TICKET: SupportTicketPayload,
    SupportEntityKind.CUSTOMER: SupportCustomerPayload,
    SupportEntityKind.AGENT: SupportAgentPayload,
    SupportEntityKind.MESSAGE: SupportMessagePayload,
    SupportEntityKind.QUEUE: SupportQueuePayload,
    SupportEntityKind.INBOX: SupportInboxPayload,
    SupportEntityKind.TAG: SupportTagPayload,
    SupportEntityKind.SLA_METRIC: SupportSlaMetricPayload,
    SupportEntityKind.ATTACHMENT: SupportAttachmentPayload,
}


class SupportTicket(SorCanonicalRecord):
    external_id: str
    subject: str | None
    normalized_description: str | None
    requester_external_id: str | None
    assignee_external_id: str | None
    group_external_id: str | None
    inbox_external_id: str | None
    native_status: str | None
    normalized_status: SupportTicketState | None
    priority: str | None
    category: str | None
    channel: str | None
    tag_external_ids: tuple[str, ...]
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    sla_state: SupportSlaState | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class SupportCustomer(SorCanonicalRecord):
    external_id: str
    name: str | None
    primary_email: str | None
    primary_phone: str | None
    company_external_id: str | None
    active: bool | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class SupportAgent(SorCanonicalRecord):
    external_id: str
    name: str
    primary_email: str | None
    active: bool | None
    assignable: bool | None
    avatar_url: str | None


class SupportMessage(SorCanonicalRecord):
    external_id: str
    ticket_external_id: str
    visibility: SupportMessageVisibility
    direction: SupportMessageDirection | None
    author_external_id: str | None
    normalized_text: str
    source_body: SorJsonValue = Field(repr=False, exclude=True)
    body_format: str | None
    attachment_external_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None


class SupportQueue(SorCanonicalRecord):
    external_id: str
    name: str
    description: str | None
    active: bool | None


class SupportInbox(SorCanonicalRecord):
    external_id: str
    name: str
    kind: str | None
    active: bool | None


class SupportTag(SorCanonicalRecord):
    external_id: str
    name: str


class SupportSlaMetric(SorCanonicalRecord):
    external_id: str
    ticket_external_id: str
    metric: str
    value: Decimal | None
    unit: str | None
    native_state: str | None
    normalized_state: SupportSlaState | None
    target_at: datetime | None
    achieved_at: datetime | None
    breached_at: datetime | None


class SupportAttachment(SorCanonicalRecord):
    external_id: str
    ticket_external_id: str
    message_external_id: str | None
    name: str
    content_type: str | None
    size_bytes: int | None
    source_url: str | None


@runtime_checkable
class SupportAdapter(SorLifecycleAdapter, Protocol):
    """Support port with pure, I/O-free synchronous normalization methods."""

    def normalize_ticket(
        self,
        record: SorExternalRecord,
        payload: SupportTicketPayload,
    ) -> SupportTicket: ...

    def normalize_customer(
        self,
        record: SorExternalRecord,
        payload: SupportCustomerPayload,
    ) -> SupportCustomer: ...

    def normalize_agent(
        self,
        record: SorExternalRecord,
        payload: SupportAgentPayload,
    ) -> SupportAgent: ...

    def normalize_message(
        self,
        record: SorExternalRecord,
        payload: SupportMessagePayload,
    ) -> SupportMessage: ...

    def normalize_queue(
        self,
        record: SorExternalRecord,
        payload: SupportQueuePayload,
    ) -> SupportQueue: ...

    def normalize_inbox(
        self,
        record: SorExternalRecord,
        payload: SupportInboxPayload,
    ) -> SupportInbox: ...

    def normalize_tag(
        self,
        record: SorExternalRecord,
        payload: SupportTagPayload,
    ) -> SupportTag: ...

    def normalize_sla_metric(
        self,
        record: SorExternalRecord,
        payload: SupportSlaMetricPayload,
    ) -> SupportSlaMetric: ...

    def normalize_attachment(
        self,
        record: SorExternalRecord,
        payload: SupportAttachmentPayload,
    ) -> SupportAttachment: ...


__all__ = [
    "SUPPORT_COMMAND_PAYLOAD_TYPES",
    "SUPPORT_PAYLOAD_TYPES",
    "SupportAssignCommandPayload",
    "SupportAdapter",
    "SupportAgent",
    "SupportAgentPayload",
    "SupportAttachment",
    "SupportAttachmentPayload",
    "SupportCustomer",
    "SupportCustomerPayload",
    "SupportEntityKind",
    "SupportInbox",
    "SupportInboxPayload",
    "SupportMessage",
    "SupportMessageCommandPayload",
    "SupportMessagePayload",
    "SupportMessageDirection",
    "SupportMessageVisibility",
    "SupportPayload",
    "SupportQueue",
    "SupportQueuePayload",
    "SupportSlaMetric",
    "SupportSlaMetricPayload",
    "SupportSlaState",
    "SupportTag",
    "SupportTagPayload",
    "SupportTicket",
    "SupportCloseCommandPayload",
    "SupportMappedFieldsCommandPayload",
    "SupportTagCommandPayload",
    "SupportTicketPayload",
    "SupportTicketState",
    "SupportToolName",
]
