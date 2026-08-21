"""Typed support records preserving customer-visible and private semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from eylo.sor.shared.contracts import SorExternalRecord, SorLifecycleAdapter


@dataclass(frozen=True, slots=True)
class SupportTicket:
    external_id: str
    subject: str | None
    normalized_description: str | None
    requester_external_id: str | None
    assignee_external_id: str | None
    group_external_id: str | None
    inbox_external_id: str | None
    native_status: str | None
    normalized_status: str | None
    priority: str | None
    category: str | None
    channel: str | None
    tag_external_ids: tuple[str, ...]
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    sla_state: str | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupportCustomer:
    external_id: str
    name: str | None
    primary_email: str | None
    primary_phone: str | None
    company_external_id: str | None
    active: bool | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SupportAgent:
    external_id: str
    name: str
    primary_email: str | None
    active: bool | None
    assignable: bool | None
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class SupportMessage:
    external_id: str
    ticket_external_id: str
    visibility: str
    direction: str | None
    author_external_id: str | None
    normalized_text: str
    source_body: object | None
    body_format: str | None
    attachment_external_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class SupportQueue:
    external_id: str
    name: str
    description: str | None
    active: bool | None


@dataclass(frozen=True, slots=True)
class SupportInbox:
    external_id: str
    name: str
    kind: str | None
    active: bool | None


@dataclass(frozen=True, slots=True)
class SupportTag:
    external_id: str
    name: str


@dataclass(frozen=True, slots=True)
class SupportSlaMetric:
    external_id: str
    ticket_external_id: str
    metric: str
    value: Decimal | None
    unit: str | None
    native_state: str | None
    normalized_state: str | None
    target_at: datetime | None
    achieved_at: datetime | None
    breached_at: datetime | None


@dataclass(frozen=True, slots=True)
class SupportAttachment:
    external_id: str
    ticket_external_id: str
    message_external_id: str | None
    name: str
    content_type: str | None
    size_bytes: int | None
    source_url: str | None


@runtime_checkable
class SupportAdapter(SorLifecycleAdapter, Protocol):
    """Support-specific normalization port layered on shared lifecycle."""

    def normalize_ticket(self, record: SorExternalRecord) -> SupportTicket: ...

    def normalize_customer(self, record: SorExternalRecord) -> SupportCustomer: ...

    def normalize_agent(self, record: SorExternalRecord) -> SupportAgent: ...

    def normalize_message(self, record: SorExternalRecord) -> SupportMessage: ...

    def normalize_queue(self, record: SorExternalRecord) -> SupportQueue: ...

    def normalize_inbox(self, record: SorExternalRecord) -> SupportInbox: ...

    def normalize_tag(self, record: SorExternalRecord) -> SupportTag: ...

    def normalize_sla_metric(self, record: SorExternalRecord) -> SupportSlaMetric: ...

    def normalize_attachment(self, record: SorExternalRecord) -> SupportAttachment: ...


__all__ = [
    "SupportAdapter",
    "SupportAgent",
    "SupportAttachment",
    "SupportCustomer",
    "SupportInbox",
    "SupportMessage",
    "SupportQueue",
    "SupportSlaMetric",
    "SupportTag",
    "SupportTicket",
]
