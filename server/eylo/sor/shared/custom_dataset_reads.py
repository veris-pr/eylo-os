"""Eylo-owned grid contract for audit-only custom source objects."""

from __future__ import annotations

from sqlalchemy import func

from eylo.sor.shared.custom_datasets import (
    CUSTOM_DATASET_ENTITY,
    SorCustomDatasetView,
)
from eylo.sor.shared.models import (
    SorProfileRecordModel,
    SorRecordModel,
    SorSourceModel,
)
from eylo.sor.shared.query import (
    SorGridColumnImportance,
    SorGridColumnKind,
)
from eylo.sor.shared.reads import SorEntityReadSpec, SorReadFieldSpec


def custom_dataset_read_spec(view: SorCustomDatasetView) -> SorEntityReadSpec:
    """Bind one dataset identity to the shared collection engine."""
    return SorEntityReadSpec(
        profile=view.source.profile,
        entity=CUSTOM_DATASET_ENTITY,
        model=None,
        vendor_object_key=view.dataset.vendor_object_key,
        fields=(
            SorReadFieldSpec(
                key="external_id",
                label="Record",
                kind=SorGridColumnKind.TEXT,
                importance=SorGridColumnImportance.PRIMARY,
                expression=func.coalesce(
                    SorRecordModel.human_external_key,
                    SorRecordModel.vendor_external_id,
                ),
                read_value=_external_key,
                groupable=False,
            ),
        ),
    )


def _external_key(
    record: SorRecordModel,
    _extension: SorProfileRecordModel | None,
    _source: SorSourceModel,
) -> str:
    return record.human_external_key or record.vendor_external_id


__all__ = ["custom_dataset_read_spec"]
