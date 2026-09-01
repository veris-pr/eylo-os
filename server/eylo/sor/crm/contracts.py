"""Typed canonical CRM records produced by vendor adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from eylo.sor.shared.contracts import SorExternalRecord, SorLifecycleAdapter


class CrmDealState(str, Enum):
    """Bounded platform state for a CRM deal."""

    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: str | None) -> "CrmDealState | None":
        if value is None:
            return None
        try:
            return cls(value.strip().upper())
        except ValueError:
            return cls.UNKNOWN


class CrmEntityKind(StrEnum):
    """Stable canonical CRM entity vocabulary."""

    CONTACT = "contact"
    COMPANY = "company"
    DEAL = "deal"
    ACTIVITY = "activity"
    OWNER = "owner"
    PIPELINE = "pipeline"
    STAGE = "stage"


class CrmToolName(StrEnum):
    """Stable model-visible CRM tool names."""

    FIND_CUSTOMER = "crm_find_customer"
    GET_CUSTOMER = "crm_get_customer"
    GET_CUSTOMER_HISTORY = "crm_get_customer_history"
    LIST_DEALS = "crm_list_deals"
    GET_DEAL = "crm_get_deal"
    GET_DEAL_HISTORY = "crm_get_deal_history"
    DESCRIBE_CUSTOMER_FIELDS = "crm_describe_customer_fields"
    DESCRIBE_DEAL_FIELDS = "crm_describe_deal_fields"
    CREATE_CONTACT = "crm_create_contact"
    UPDATE_CONTACT = "crm_update_contact"
    CREATE_COMPANY = "crm_create_company"
    UPDATE_COMPANY = "crm_update_company"
    CREATE_DEAL = "crm_create_deal"
    UPDATE_DEAL = "crm_update_deal"
    MOVE_DEAL = "crm_move_deal"
    ADD_NOTE = "crm_add_note"
    LOG_ACTIVITY = "crm_log_activity"


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
    normalized_state: CrmDealState | None
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


__all__ = [
    "CrmActivity",
    "CrmAdapter",
    "CrmCompany",
    "CrmContact",
    "CrmDeal",
    "CrmDealState",
    "CrmEntityKind",
    "CrmToolName",
]
