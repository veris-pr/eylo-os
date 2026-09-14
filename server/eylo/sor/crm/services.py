"""Canonical CRM projection policy independent of vendor payloads."""

from __future__ import annotations

from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel, SorRecordModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorProjectionError

from .contracts import CrmActivity, CrmCompany, CrmContact, CrmDeal, CrmEntityKind
from .models import CrmActivityModel, CrmCompanyModel, CrmContactModel, CrmDealModel

CrmRecordModel = TypeVar("CrmRecordModel", bound=SorProfileRecordModel)


class CrmProjectionService:
    """Persist mapping-approved typed CRM fields beside shared identities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = SorRepository(session)

    async def upsert_contact(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        contact: CrmContact,
    ) -> CrmContactModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.CONTACT,
            vendor_external_id=contact.external_id,
        )
        _validate_contact(contact)
        values: dict[str, object] = {
            "name": contact.name,
            "primary_email": contact.primary_email,
            "primary_phone": contact.primary_phone,
            "job_title": contact.job_title,
            "lifecycle_stage": contact.lifecycle_stage,
            "owner_external_id": contact.owner_external_id,
        }
        row = await self._upsert(
            CrmContactModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.CONTACT,
            values=values,
        )
        _update_search(
            record,
            contact.name,
            contact.primary_email,
            contact.primary_phone,
            contact.job_title,
            contact.lifecycle_stage,
        )
        await self.session.flush()
        return row

    async def upsert_company(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        company: CrmCompany,
    ) -> CrmCompanyModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.COMPANY,
            vendor_external_id=company.external_id,
        )
        _validate_company(company)
        values: dict[str, object] = {
            "name": company.name,
            "domain": company.domain,
            "industry": company.industry,
            "owner_external_id": company.owner_external_id,
        }
        row = await self._upsert(
            CrmCompanyModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.COMPANY,
            values=values,
        )
        _update_search(record, company.name, company.domain, company.industry)
        await self.session.flush()
        return row

    async def upsert_deal(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        deal: CrmDeal,
    ) -> CrmDealModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.DEAL,
            vendor_external_id=deal.external_id,
        )
        _validate_deal(deal)
        values: dict[str, object] = {
            "title": deal.title,
            "pipeline_external_id": deal.pipeline_external_id,
            "stage_external_id": deal.stage_external_id,
            "native_stage": deal.native_stage,
            "normalized_state": (
                deal.normalized_state.value
                if deal.normalized_state is not None
                else None
            ),
            "amount": deal.amount,
            "currency": deal.currency,
            "probability": deal.probability,
            "expected_close_date": deal.expected_close_date,
            "owner_external_id": deal.owner_external_id,
            "contact_external_ids": list(deal.contact_external_ids),
            "company_external_ids": list(deal.company_external_ids),
        }
        row = await self._upsert(
            CrmDealModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.DEAL,
            values=values,
        )
        _update_search(
            record,
            deal.title,
            deal.native_stage,
            deal.normalized_state,
            deal.currency,
        )
        await self.session.flush()
        return row

    async def upsert_activity(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        activity: CrmActivity,
    ) -> CrmActivityModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.ACTIVITY,
            vendor_external_id=activity.external_id,
        )
        _validate_activity(activity)
        values: dict[str, object] = {
            "kind": activity.kind,
            "subject": activity.subject,
            "normalized_text": activity.normalized_text,
            "occurred_at": activity.occurred_at,
            "actor_external_id": activity.actor_external_id,
            "participant_external_ids": list(activity.participant_external_ids),
            "related_external_ids": list(activity.related_external_ids),
        }
        row = await self._upsert(
            CrmActivityModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=CrmEntityKind.ACTIVITY,
            values=values,
        )
        _update_search(
            record,
            activity.kind,
            activity.subject,
            activity.normalized_text,
        )
        await self.session.flush()
        return row

    async def _require_record(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: CrmEntityKind,
        vendor_external_id: str,
    ) -> SorRecordModel:
        record = await self.records.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            for_update=True,
        )
        if record is None:
            raise SorProjectionError("Canonical CRM source record not found.")
        if (
            record.profile is not SorProfile.CRM
            or record.canonical_entity_kind != entity_kind.value
            or record.vendor_external_id != vendor_external_id
        ):
            raise SorProjectionError(
                "CRM value does not match its canonical source identity."
            )
        return record

    async def _upsert(
        self,
        model: type[CrmRecordModel],
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: CrmEntityKind,
        values: dict[str, object],
    ) -> CrmRecordModel:
        row = await self.session.scalar(
            select(model).where(
                model.organization_id == organization_id,
                model.source_id == source_id,
                model.record_id == record_id,
                model.deleted.is_(False),
            )
        )
        if row is None:
            row = model(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.CRM,
                canonical_entity_kind=entity_kind.value,
                **values,
            )
            self.session.add(row)
        else:
            for field, value in values.items():
                setattr(row, field, value)
        return row


def _validate_contact(contact: CrmContact) -> None:
    _required(contact.external_id, maximum=512, field="contact external ID")
    _optional(contact.name, maximum=1_000_000, field="contact name")
    _optional(contact.primary_email, maximum=1024, field="contact email")
    _optional(contact.primary_phone, maximum=320, field="contact phone")
    _optional(contact.job_title, maximum=1_000_000, field="contact job title")
    _optional(contact.lifecycle_stage, maximum=160, field="contact lifecycle")
    _optional(contact.owner_external_id, maximum=512, field="contact owner")


def _validate_company(company: CrmCompany) -> None:
    _required(company.external_id, maximum=512, field="company external ID")
    _optional(company.name, maximum=1_000_000, field="company name")
    _optional(company.domain, maximum=1024, field="company domain")
    _optional(company.industry, maximum=320, field="company industry")
    _optional(company.owner_external_id, maximum=512, field="company owner")


def _validate_deal(deal: CrmDeal) -> None:
    _required(deal.external_id, maximum=512, field="deal external ID")
    _required(deal.title, maximum=1_000_000, field="deal title")
    for value, maximum, field in (
        (deal.pipeline_external_id, 512, "deal pipeline"),
        (deal.stage_external_id, 512, "deal stage"),
        (deal.native_stage, 320, "deal native stage"),
        (deal.normalized_state, 96, "deal normalized state"),
        (deal.currency, 16, "deal currency"),
        (deal.owner_external_id, 512, "deal owner"),
    ):
        _optional(value, maximum=maximum, field=field)
    _bounded_decimal(deal.amount, maximum=Decimal("1e21"), field="deal amount")
    if deal.probability is not None and not Decimal("0") <= deal.probability <= Decimal(
        "1"
    ):
        raise SorProjectionError("CRM deal probability must be between 0 and 1.")
    _identities(deal.contact_external_ids, field="deal contacts")
    _identities(deal.company_external_ids, field="deal companies")


def _validate_activity(activity: CrmActivity) -> None:
    _required(activity.external_id, maximum=512, field="activity external ID")
    _required(activity.kind, maximum=96, field="activity kind")
    _optional(activity.subject, maximum=1_000_000, field="activity subject")
    _optional(activity.normalized_text, maximum=1_000_000, field="activity text")
    _optional(activity.actor_external_id, maximum=512, field="activity actor")
    if activity.occurred_at.tzinfo is None or activity.occurred_at.utcoffset() is None:
        raise SorProjectionError("CRM activity timestamp must be timezone-aware.")
    _identities(activity.participant_external_ids, field="activity participants")
    _identities(activity.related_external_ids, field="activity relations")
    _identities(activity.contact_external_ids, field="activity contacts")
    _identities(activity.company_external_ids, field="activity companies")
    _identities(activity.deal_external_ids, field="activity deals")


def _required(value: str, *, maximum: int, field: str) -> None:
    if not value or len(value) > maximum:
        raise SorProjectionError(f"CRM {field} is invalid.")


def _optional(value: str | None, *, maximum: int, field: str) -> None:
    if value is not None and len(value) > maximum:
        raise SorProjectionError(f"CRM {field} is too large.")


def _bounded_decimal(
    value: Decimal | None,
    *,
    maximum: Decimal,
    field: str,
) -> None:
    if value is not None and (not value.is_finite() or abs(value) >= maximum):
        raise SorProjectionError(f"CRM {field} is outside the supported range.")


def _identities(values: tuple[str, ...], *, field: str) -> None:
    if (
        len(values) > 10_000
        or len(values) != len(set(values))
        or any(not value or len(value) > 512 for value in values)
    ):
        raise SorProjectionError(f"CRM {field} are invalid.")


def _update_search(record: SorRecordModel, *values: str | None) -> None:
    record.search_text = " ".join(value for value in values if value)[:1_000_000]
    record.search_vector = func.to_tsvector("simple", record.search_text)


__all__ = ["CrmProjectionService"]
