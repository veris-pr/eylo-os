"""Explicit CRM field contracts for shared SOR audit queries."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import QueryableAttribute

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import (
    SorProfileRecordModel,
    SorRecordModel,
    SorSourceModel,
)
from eylo.sor.shared.query import SorGridColumnImportance, SorGridColumnKind
from eylo.sor.shared.reads import SorEntityReadSpec, SorReadFieldSpec

from .models import CrmActivityModel, CrmCompanyModel, CrmContactModel, CrmDealModel


def _extension_value(
    name: str,
) -> Callable[[SorRecordModel, SorProfileRecordModel | None, SorSourceModel], object]:
    return lambda _record, extension, _source: (
        getattr(extension, name) if extension is not None else None
    )


def _field(
    *,
    key: str,
    label: str,
    kind: SorGridColumnKind,
    importance: SorGridColumnImportance,
    expression: QueryableAttribute[Any],
    attribute: str,
    default_visible: bool = True,
    filterable: bool = True,
    sortable: bool = True,
    groupable: bool = False,
    wraps: bool = False,
) -> SorReadFieldSpec:
    return SorReadFieldSpec(
        key=key,
        label=label,
        kind=kind,
        importance=importance,
        expression=expression,
        read_value=_extension_value(attribute),
        default_visible=default_visible,
        filterable=filterable,
        sortable=sortable,
        groupable=groupable,
        wraps=wraps,
    )


CRM_CONTACT_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.CRM,
    entity="contact",
    model=CrmContactModel,
    fields=(
        _field(
            key="name",
            label="Name",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmContactModel.name,
            attribute="name",
        ),
        _field(
            key="primary_email",
            label="Email",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmContactModel.primary_email,
            attribute="primary_email",
        ),
        _field(
            key="primary_phone",
            label="Phone",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmContactModel.primary_phone,
            attribute="primary_phone",
            default_visible=False,
        ),
        _field(
            key="job_title",
            label="Job title",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmContactModel.job_title,
            attribute="job_title",
        ),
        _field(
            key="lifecycle_stage",
            label="Lifecycle",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmContactModel.lifecycle_stage,
            attribute="lifecycle_stage",
            groupable=True,
        ),
        _field(
            key="owner",
            label="Owner",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.METADATA,
            expression=CrmContactModel.owner_external_id,
            attribute="owner_external_id",
            default_visible=False,
            groupable=True,
        ),
    ),
)

CRM_COMPANY_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.CRM,
    entity="company",
    model=CrmCompanyModel,
    fields=(
        _field(
            key="name",
            label="Name",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmCompanyModel.name,
            attribute="name",
        ),
        _field(
            key="domain",
            label="Domain",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmCompanyModel.domain,
            attribute="domain",
        ),
        _field(
            key="industry",
            label="Industry",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmCompanyModel.industry,
            attribute="industry",
            groupable=True,
        ),
        _field(
            key="owner",
            label="Owner",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.METADATA,
            expression=CrmCompanyModel.owner_external_id,
            attribute="owner_external_id",
            default_visible=False,
            groupable=True,
        ),
    ),
)

CRM_DEAL_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.CRM,
    entity="deal",
    model=CrmDealModel,
    fields=(
        _field(
            key="title",
            label="Deal",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmDealModel.title,
            attribute="title",
            wraps=True,
        ),
        _field(
            key="normalized_state",
            label="State",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmDealModel.normalized_state,
            attribute="normalized_state",
            groupable=True,
        ),
        _field(
            key="native_stage",
            label="Source stage",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmDealModel.native_stage,
            attribute="native_stage",
            groupable=True,
        ),
        _field(
            key="amount",
            label="Amount",
            kind=SorGridColumnKind.NUMBER,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmDealModel.amount,
            attribute="amount",
        ),
        _field(
            key="currency",
            label="Currency",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmDealModel.currency,
            attribute="currency",
            groupable=True,
        ),
        _field(
            key="probability",
            label="Probability",
            kind=SorGridColumnKind.NUMBER,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmDealModel.probability,
            attribute="probability",
            default_visible=False,
        ),
        _field(
            key="expected_close_date",
            label="Expected close",
            kind=SorGridColumnKind.DATE,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmDealModel.expected_close_date,
            attribute="expected_close_date",
        ),
        _field(
            key="owner",
            label="Owner",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.METADATA,
            expression=CrmDealModel.owner_external_id,
            attribute="owner_external_id",
            default_visible=False,
            groupable=True,
        ),
    ),
)

CRM_ACTIVITY_READ_SPEC = SorEntityReadSpec(
    profile=SorProfile.CRM,
    entity="activity",
    model=CrmActivityModel,
    fields=(
        _field(
            key="kind",
            label="Kind",
            kind=SorGridColumnKind.ENUM,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmActivityModel.kind,
            attribute="kind",
            groupable=True,
        ),
        _field(
            key="subject",
            label="Subject",
            kind=SorGridColumnKind.TEXT,
            importance=SorGridColumnImportance.PRIMARY,
            expression=CrmActivityModel.subject,
            attribute="subject",
        ),
        _field(
            key="text",
            label="Activity",
            kind=SorGridColumnKind.LONG_TEXT,
            importance=SorGridColumnImportance.SECONDARY,
            expression=CrmActivityModel.normalized_text,
            attribute="normalized_text",
            wraps=True,
        ),
        _field(
            key="occurred_at",
            label="Occurred",
            kind=SorGridColumnKind.DATETIME,
            importance=SorGridColumnImportance.METADATA,
            expression=CrmActivityModel.occurred_at,
            attribute="occurred_at",
        ),
        _field(
            key="actor",
            label="Actor",
            kind=SorGridColumnKind.REFERENCE,
            importance=SorGridColumnImportance.METADATA,
            expression=CrmActivityModel.actor_external_id,
            attribute="actor_external_id",
            default_visible=False,
            groupable=True,
        ),
    ),
)

CRM_READ_SPECS = {
    spec.entity: spec
    for spec in (
        CRM_CONTACT_READ_SPEC,
        CRM_COMPANY_READ_SPEC,
        CRM_DEAL_READ_SPEC,
        CRM_ACTIVITY_READ_SPEC,
    )
}


__all__ = [
    "CRM_ACTIVITY_READ_SPEC",
    "CRM_COMPANY_READ_SPEC",
    "CRM_CONTACT_READ_SPEC",
    "CRM_DEAL_READ_SPEC",
    "CRM_READ_SPECS",
]
