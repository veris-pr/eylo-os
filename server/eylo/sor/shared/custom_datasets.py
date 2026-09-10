"""Domain policy for audit-only custom SOR datasets."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.models import SorCustomDatasetModel, SorSourceModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorConfigurationError, SorNotFoundError

CUSTOM_DATASET_ENTITY = "custom_dataset"


class SorCustomDatasetView(BaseModel):
    """Transaction-owned dataset/source rows, excluded from public snapshots."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    dataset: SkipJsonSchema[InstanceOf[SorCustomDatasetModel]] = Field(
        exclude=True, repr=False
    )
    source: SkipJsonSchema[InstanceOf[SorSourceModel]] = Field(exclude=True, repr=False)


class SorCustomDatasetService:
    """Create and read custom datasets without granting Agent authority."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)

    async def ensure(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        label: str,
        description: str | None = None,
    ) -> SorCustomDatasetModel:
        """Create one stable audit dataset for an explicitly selected object."""
        object_key = vendor_object_key.strip()
        normalized_label = label.strip()
        if not object_key or len(object_key) > 160:
            raise SorConfigurationError("Custom dataset object key is invalid.")
        if not normalized_label or len(normalized_label) > 256:
            raise SorConfigurationError("Custom dataset label is invalid.")
        normalized_description = description.strip() if description else None
        if normalized_description and len(normalized_description) > 4096:
            raise SorConfigurationError("Custom dataset description is too long.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        existing = await self.repository.get_custom_dataset_by_object(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=object_key,
            for_update=True,
        )
        if existing is not None:
            existing.label = normalized_label
            existing.description = normalized_description
            await self.session.flush()
            return existing
        row = SorCustomDatasetModel(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=object_key,
            label=normalized_label,
            description=normalized_description,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(
        self,
        *,
        organization_id: UUID,
        dataset_id: UUID,
    ) -> SorCustomDatasetView:
        dataset = await self.repository.get_custom_dataset(
            organization_id=organization_id,
            dataset_id=dataset_id,
        )
        if dataset is None:
            raise SorNotFoundError("SOR custom dataset not found.")
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=dataset.source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR custom dataset not found.")
        return SorCustomDatasetView(dataset=dataset, source=source)

    async def list(
        self,
        *,
        organization_id: UUID,
    ) -> tuple[SorCustomDatasetView, ...]:
        datasets = await self.repository.list_custom_datasets(
            organization_id=organization_id
        )
        views: list[SorCustomDatasetView] = []
        for dataset in datasets:
            source = await self.repository.get_source(
                organization_id=organization_id,
                source_id=dataset.source_id,
            )
            if source is not None:
                views.append(SorCustomDatasetView(dataset=dataset, source=source))
        return tuple(views)


__all__ = [
    "CUSTOM_DATASET_ENTITY",
    "SorCustomDatasetService",
    "SorCustomDatasetView",
]
