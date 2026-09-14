"""Typed canonical CRM records produced by vendor adapters."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from eylo.sor.shared.contracts import (
    SorCanonicalPayload,
    SorCanonicalRecord,
    SorCommandPayload,
    SorExternalRecord,
    SorLifecycleAdapter,
    SorMappedFieldsCommandPayload,
)
from eylo.sor.shared.json_values import SorJsonValue


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


class CrmMappedFieldsCommandPayload(SorMappedFieldsCommandPayload):
    """Mapped CRM fields for one create, update, or activity command."""


class CrmMoveDealCommandPayload(SorCommandPayload):
    """One exact source stage selected for a deal move."""

    stage_external_id: str = Field(min_length=1, max_length=320)


class CrmNoteCommandPayload(SorCommandPayload):
    """Plain-text note attached to one CRM record."""

    normalized_text: str = Field(min_length=1, max_length=100_000)


CRM_COMMAND_PAYLOAD_TYPES: Mapping[CrmToolName, type[SorCommandPayload]] = {
    CrmToolName.CREATE_CONTACT: CrmMappedFieldsCommandPayload,
    CrmToolName.UPDATE_CONTACT: CrmMappedFieldsCommandPayload,
    CrmToolName.CREATE_COMPANY: CrmMappedFieldsCommandPayload,
    CrmToolName.UPDATE_COMPANY: CrmMappedFieldsCommandPayload,
    CrmToolName.CREATE_DEAL: CrmMappedFieldsCommandPayload,
    CrmToolName.UPDATE_DEAL: CrmMappedFieldsCommandPayload,
    CrmToolName.MOVE_DEAL: CrmMoveDealCommandPayload,
    CrmToolName.ADD_NOTE: CrmNoteCommandPayload,
    CrmToolName.LOG_ACTIVITY: CrmMappedFieldsCommandPayload,
}


class CrmContactPayload(SorCanonicalPayload):
    """Mapped contact fields before source identity is attached."""

    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    primary_email: str | None = None
    primary_phone: str | None = None
    job_title: str | None = None
    lifecycle_stage: str | None = None
    owner_external_id: str | None = None


class CrmCompanyPayload(SorCanonicalPayload):
    """Mapped company fields before source identity is attached."""

    name: str | None = None
    domain: str | None = None
    industry: str | None = None
    owner_external_id: str | None = None


class CrmDealPayload(SorCanonicalPayload):
    """Mapped deal fields before source identity is attached."""

    title: str
    pipeline_external_id: str | None = None
    stage_external_id: str | None = None
    native_stage: str | None = None
    normalized_state: CrmDealState | None = None
    amount: Decimal | None = None
    currency: str | None = None
    probability: Decimal | None = None
    expected_close_date: date | None = None
    owner_external_id: str | None = None
    contact_external_ids: tuple[str, ...] = ()
    company_external_ids: tuple[str, ...] = ()


class CrmActivityPayload(SorCanonicalPayload):
    """Mapped activity fields before vendor-specific normalization."""

    kind: str | None = None
    subject: str | None = None
    normalized_text: str | None = None
    occurred_at: datetime | None = None
    actor_external_id: str | None = None
    participant_external_ids: tuple[str, ...] = ()
    related_external_ids: tuple[str, ...] = ()
    contact_external_ids: tuple[str, ...] = ()
    company_external_ids: tuple[str, ...] = ()
    deal_external_ids: tuple[str, ...] = ()


CrmPayload = CrmContactPayload | CrmCompanyPayload | CrmDealPayload | CrmActivityPayload


CRM_PAYLOAD_TYPES: Mapping[CrmEntityKind, type[SorCanonicalPayload]] = {
    CrmEntityKind.CONTACT: CrmContactPayload,
    CrmEntityKind.COMPANY: CrmCompanyPayload,
    CrmEntityKind.DEAL: CrmDealPayload,
    CrmEntityKind.ACTIVITY: CrmActivityPayload,
}


class CrmContact(SorCanonicalRecord):
    external_id: str
    name: str | None
    primary_email: str | None
    primary_phone: str | None
    job_title: str | None
    lifecycle_stage: str | None
    owner_external_id: str | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class CrmCompany(SorCanonicalRecord):
    external_id: str
    name: str | None
    domain: str | None
    industry: str | None
    owner_external_id: str | None
    source_updated_at: datetime | None
    source_url: str | None
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class CrmDeal(SorCanonicalRecord):
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
    custom_fields: dict[str, SorJsonValue] = Field(default_factory=dict)


class CrmActivity(SorCanonicalRecord):
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

    def normalize_contact(
        self,
        record: SorExternalRecord,
        payload: CrmContactPayload,
    ) -> CrmContact: ...

    def normalize_company(
        self,
        record: SorExternalRecord,
        payload: CrmCompanyPayload,
    ) -> CrmCompany: ...

    def normalize_deal(
        self,
        record: SorExternalRecord,
        payload: CrmDealPayload,
    ) -> CrmDeal: ...

    def normalize_activity(
        self,
        record: SorExternalRecord,
        payload: CrmActivityPayload,
    ) -> CrmActivity: ...


__all__ = [
    "CRM_COMMAND_PAYLOAD_TYPES",
    "CRM_PAYLOAD_TYPES",
    "CrmActivity",
    "CrmActivityPayload",
    "CrmAdapter",
    "CrmCompany",
    "CrmCompanyPayload",
    "CrmContact",
    "CrmContactPayload",
    "CrmDeal",
    "CrmDealPayload",
    "CrmDealState",
    "CrmEntityKind",
    "CrmMappedFieldsCommandPayload",
    "CrmMoveDealCommandPayload",
    "CrmNoteCommandPayload",
    "CrmToolName",
    "CrmPayload",
]
