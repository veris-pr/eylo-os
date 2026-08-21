"""Typed canonical projection tables for the CRM profile."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel


class CrmContactModel(SorProfileRecordModel):
    """Canonical person projected from a mapped CRM contact."""

    __tablename__ = "sor_crm_contacts"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.CRM,
            entity_kind="contact",
        ),
        Index("ix_sor_crm_contacts_source_email", "source_id", "primary_email"),
        Index(
            "ix_sor_crm_contacts_source_lifecycle",
            "source_id",
            "lifecycle_stage",
        ),
        Index("ix_sor_crm_contacts_source_owner", "source_id", "owner_external_id"),
    )

    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_email: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    primary_phone: Mapped[str | None] = mapped_column(String(320), nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CrmCompanyModel(SorProfileRecordModel):
    """Canonical organization projected from a mapped CRM company."""

    __tablename__ = "sor_crm_companies"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.CRM,
            entity_kind="company",
        ),
        Index("ix_sor_crm_companies_source_domain", "source_id", "domain"),
        Index("ix_sor_crm_companies_source_industry", "source_id", "industry"),
        Index("ix_sor_crm_companies_source_owner", "source_id", "owner_external_id"),
    )

    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(320), nullable=True)
    owner_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CrmDealModel(SorProfileRecordModel):
    """Canonical commercial opportunity and its mapped pipeline state."""

    __tablename__ = "sor_crm_deals"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.CRM,
            entity_kind="deal",
        ),
        CheckConstraint(
            "cardinality(contact_external_ids) <= 10000 "
            "AND cardinality(company_external_ids) <= 10000",
            name="ck_sor_crm_deals_relationship_counts",
        ),
        Index("ix_sor_crm_deals_source_stage", "source_id", "stage_external_id"),
        Index("ix_sor_crm_deals_source_state", "source_id", "normalized_state"),
        Index("ix_sor_crm_deals_source_owner", "source_id", "owner_external_id"),
        Index("ix_sor_crm_deals_source_close", "source_id", "expected_close_date"),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_external_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    stage_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    native_stage: Mapped[str | None] = mapped_column(String(320), nullable=True)
    normalized_state: Mapped[str | None] = mapped_column(String(96), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    contact_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    company_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )


class CrmActivityModel(SorProfileRecordModel):
    """Canonical CRM activity for future vendor activity streams."""

    __tablename__ = "sor_crm_activities"
    __table_args__ = (
        *SorProfileRecordModel.get_organization_constraints(__tablename__),
        *SorProfileRecordModel.get_record_constraints(
            __tablename__,
            profile=SorProfile.CRM,
            entity_kind="activity",
        ),
        CheckConstraint(
            "cardinality(participant_external_ids) <= 10000 "
            "AND cardinality(related_external_ids) <= 10000",
            name="ck_sor_crm_activities_relationship_counts",
        ),
        Index("ix_sor_crm_activities_source_kind", "source_id", "kind"),
        Index("ix_sor_crm_activities_source_occurred", "source_id", "occurred_at"),
    )

    kind: Mapped[str] = mapped_column(String(96), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    participant_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    related_external_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(512)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )


__all__ = [
    "CrmActivityModel",
    "CrmCompanyModel",
    "CrmContactModel",
    "CrmDealModel",
]
