"""Typed canonical CRM records produced by vendor adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from eylo.sor.shared.contracts import SorExternalRecord, SorLifecycleAdapter


@dataclass(frozen=True, slots=True)
class CrmContact:
    external_id: str
    name: str | None
    primary_email: str | None
    primary_phone: str | None
    job_title: str | None
    lifecycle_stage: str | None
    owner_external_id: str | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrmCompany:
    external_id: str
    name: str | None
    domain: str | None
    industry: str | None
    owner_external_id: str | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrmDeal:
    external_id: str
    title: str
    pipeline_external_id: str | None
    stage_external_id: str | None
    native_stage: str | None
    normalized_state: str | None
    amount: Decimal | None
    currency: str | None
    probability: Decimal | None
    expected_close_date: date | None
    owner_external_id: str | None
    contact_external_ids: tuple[str, ...]
    company_external_ids: tuple[str, ...]
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CrmActivity:
    external_id: str
    kind: str
    subject: str | None
    normalized_text: str | None
    occurred_at: datetime
    actor_external_id: str | None
    participant_external_ids: tuple[str, ...]
    related_external_ids: tuple[str, ...]
    source_url: str | None
    contact_external_ids: tuple[str, ...] = ()
    company_external_ids: tuple[str, ...] = ()
    deal_external_ids: tuple[str, ...] = ()


@runtime_checkable
class CrmAdapter(SorLifecycleAdapter, Protocol):
    """CRM port whose synchronous normalization methods are pure and I/O-free."""

    def normalize_contact(self, record: SorExternalRecord) -> CrmContact: ...

    def normalize_company(self, record: SorExternalRecord) -> CrmCompany: ...

    def normalize_deal(self, record: SorExternalRecord) -> CrmDeal: ...

    def normalize_activity(self, record: SorExternalRecord) -> CrmActivity: ...


__all__ = ["CrmActivity", "CrmAdapter", "CrmCompany", "CrmContact", "CrmDeal"]
