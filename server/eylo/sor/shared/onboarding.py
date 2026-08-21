"""Atomic source activation across mapping, streams, and durable sync intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.shared.contracts import (
    SorFieldMappingDirection,
    SorFieldMappingDraft,
    SorSourceState,
    SorStreamDraft,
    SorSyncRunKind,
)
from eylo.sor.shared.custom_datasets import (
    CUSTOM_DATASET_ENTITY,
    SorCustomDatasetService,
)
from eylo.sor.shared.models import (
    SorMappingRevisionModel,
    SorSourceModel,
    SorSourceStreamModel,
    SorSyncRunModel,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorMappingService,
    SorSourceService,
    snapshot_objects,
)
from eylo.sor.shared.sync_services import SorStreamService, SorSyncRunService


@dataclass(frozen=True, slots=True)
class SorActivationResult:
    """Rows persisted by one complete source activation transaction."""

    source: SorSourceModel
    mapping: SorMappingRevisionModel
    streams: tuple[SorSourceStreamModel, ...]
    runs: tuple[SorSyncRunModel, ...]


class SorOnboardingService:
    """Activate one verified source without browser-coordinated partial state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.registry = registry or get_sor_registry()
        self.sources = SorSourceService(session, registry=self.registry)
        self.mappings = SorMappingService(session, registry=self.registry)
        self.streams = SorStreamService(session, registry=self.registry)
        self.runs = SorSyncRunService(session)
        self.repository = SorRepository(session)
        self.datasets = SorCustomDatasetService(session)

    async def activate(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        fields: Sequence[SorFieldMappingDraft],
        stream_drafts: Sequence[SorStreamDraft],
        actor_id: UUID | None,
        projection_version: int = 1,
    ) -> SorActivationResult:
        """Persist all bootstrap authority before any durable worker can start."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state is not SorSourceState.DRAFT:
            raise SorConflictError(
                "Only a verified draft source can be activated."
            )
        if source.active_mapping_revision_id is not None:
            raise SorConflictError("This source already has an active mapping.")
        if source.active_schema_revision_id is None:
            raise SorConfigurationError("Discover a source schema before activation.")
        schema = await self.repository.get_schema_revision(
            organization_id=organization_id,
            source_id=source.id,
            schema_revision_id=source.active_schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Active source schema no longer exists.")
        discovered_objects = snapshot_objects(schema.schema_snapshot)
        self._validate_selection(
            source=source,
            fields=fields,
            streams=stream_drafts,
            discovered_objects=discovered_objects,
        )

        mapping = await self.mappings.create_draft(
            organization_id=organization_id,
            source_id=source_id,
            fields=fields,
            actor_id=actor_id,
            projection_version=projection_version,
        )
        mapping = await self.mappings.publish(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=mapping.id,
            actor_id=actor_id,
        )

        stream_rows: list[SorSourceStreamModel] = []
        run_rows: list[SorSyncRunModel] = []
        for draft in stream_drafts:
            label, custom = discovered_objects[draft.vendor_object_key]
            if custom:
                await self.datasets.ensure(
                    organization_id=organization_id,
                    source_id=source.id,
                    vendor_object_key=draft.vendor_object_key,
                    label=label,
                )
            stream = await self.streams.ensure(
                organization_id=organization_id,
                source_id=source_id,
                vendor_object_key=draft.vendor_object_key,
                canonical_entity_kind=draft.canonical_entity_kind,
                strategy=draft.strategy,
                lookback_seconds=draft.lookback_seconds,
                schedule=draft.schedule,
            )
            run, created = await self.runs.create_stream_run(
                organization_id=organization_id,
                source_id=source_id,
                stream_id=stream.id,
                kind=SorSyncRunKind.BOOTSTRAP,
            )
            if not created:
                raise SorConflictError(
                    "A source stream already has active bootstrap work."
                )
            stream_rows.append(stream)
            run_rows.append(run)

        return SorActivationResult(
            source=source,
            mapping=mapping,
            streams=tuple(stream_rows),
            runs=tuple(run_rows),
        )

    def _validate_selection(
        self,
        *,
        source: SorSourceModel,
        fields: Sequence[SorFieldMappingDraft],
        streams: Sequence[SorStreamDraft],
        discovered_objects: dict[str, tuple[str, bool]],
    ) -> None:
        selected = tuple(source.selected_objects or ())
        stream_keys = [stream.vendor_object_key for stream in streams]
        if len(stream_keys) != len(set(stream_keys)) or set(stream_keys) != set(
            selected
        ):
            raise SorConfigurationError(
                "Activation requires exactly one stream for every selected object."
            )

        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        manifest_streams = {stream.key: stream for stream in manifest.streams}
        profile_entities = {
            entity.key: entity for entity in self.registry.get_profile(source.profile).entities
        }
        mapped_fields = [
            field
            for field in fields
            if field.direction is not SorFieldMappingDirection.IGNORE
        ]
        mapped_objects = {field.vendor_object_key for field in mapped_fields}
        if mapped_objects != set(selected):
            raise SorConfigurationError(
                "Activation requires at least one mapped field for every selected object."
            )

        for stream in streams:
            manifest_stream = manifest_streams.get(stream.vendor_object_key)
            if manifest_stream is None:
                metadata = discovered_objects.get(stream.vendor_object_key)
                if (
                    metadata is None
                    or not metadata[1]
                    or not manifest.supports_custom_objects
                    or stream.canonical_entity_kind != CUSTOM_DATASET_ENTITY
                    or stream.strategy not in manifest.custom_object_change_strategies
                ):
                    raise SorConfigurationError(
                        "Activation custom-object stream is not executable."
                    )
                custom_fields = [
                    field
                    for field in mapped_fields
                    if field.vendor_object_key == stream.vendor_object_key
                ]
                if any(
                    field.direction is not SorFieldMappingDirection.READ_ONLY
                    or field.canonical_target_path is not None
                    or field.custom_type is None
                    or field.agent_visible
                    for field in custom_fields
                ):
                    raise SorConfigurationError(
                        "Custom-object mappings must be read-only typed audit fields."
                    )
                continue
            if stream.canonical_entity_kind != manifest_stream.canonical_entity:
                raise SorConfigurationError(
                    "Activation stream entity does not match the adapter contract."
                )
            required = {
                field.key
                for field in profile_entities[manifest_stream.canonical_entity].fields
                if field.required
            }
            selected_targets = {
                field.canonical_target_path
                for field in mapped_fields
                if field.vendor_object_key == stream.vendor_object_key
                and field.canonical_target_path is not None
            }
            missing = required - selected_targets
            if missing:
                raise SorConfigurationError(
                    f"{manifest_stream.canonical_entity} mapping requires canonical "
                    f"fields: {', '.join(sorted(missing))}."
                )


__all__ = ["SorActivationResult", "SorOnboardingService"]
