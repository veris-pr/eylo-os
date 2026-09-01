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
    SorMappingState,
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
    SorSyncGenerationModel,
    SorSyncRunModel,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorMappingService,
    SorNotFoundError,
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
    generation: SorSyncGenerationModel
    runs: tuple[SorSyncRunModel, ...]


@dataclass(frozen=True, slots=True)
class SorMappingPublicationResult:
    """Published mapping plus the durable bootstrap work it authorized."""

    mapping: SorMappingRevisionModel
    generation: SorSyncGenerationModel | None
    runs: tuple[SorSyncRunModel, ...]


class SorOnboardingService:
    """Persist complete source activation and remapping authority."""

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
            raise SorConflictError("Only a verified draft source can be activated.")
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

        return await self._publish_selection(
            organization_id=organization_id,
            source=source,
            fields=fields,
            stream_drafts=stream_drafts,
            actor_id=actor_id,
            projection_version=projection_version,
            discovered_objects=discovered_objects,
        )

    async def expand_selection(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        expected_config_revision: int,
        selected_objects: Sequence[str],
        fields: Sequence[SorFieldMappingDraft],
        stream_drafts: Sequence[SorStreamDraft],
        actor_id: UUID | None,
    ) -> SorActivationResult:
        """Atomically add discovered objects and bootstrap a complete replacement."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.config_revision != expected_config_revision:
            raise SorConflictError("SOR source configuration changed.")
        if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
            raise SorConflictError(
                "Only an active source can enable additional objects."
            )
        if source.active_mapping_revision_id is None:
            raise SorConflictError("Activate the source before expanding it.")
        if (
            await self.repository.get_active_source_sync_run(
                organization_id=organization_id,
                source_id=source_id,
                for_update=True,
            )
            is not None
        ):
            raise SorConflictError(
                "Wait for active source synchronization to finish before "
                "enabling objects."
            )

        objects = await self.sources.validate_discovered_selection(
            organization_id=organization_id,
            source=source,
            selected_objects=selected_objects,
        )
        current = set(source.selected_objects or ())
        requested = set(objects)
        if not current < requested:
            raise SorConfigurationError(
                "Source expansion must retain every enabled object and add at least one."
            )
        added = requested - current
        field_objects = {field.vendor_object_key for field in fields}
        stream_objects = {stream.vendor_object_key for stream in stream_drafts}
        if field_objects != added or stream_objects != added:
            raise SorConfigurationError(
                "Source expansion fields and streams must describe every newly "
                "enabled object exactly once."
            )
        schema = await self.repository.get_schema_revision(
            organization_id=organization_id,
            source_id=source.id,
            schema_revision_id=source.active_schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Active source schema no longer exists.")
        discovered_objects = snapshot_objects(schema.schema_snapshot)
        active_mapping = await self.repository.get_mapping_revision(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=source.active_mapping_revision_id,
            for_update=True,
        )
        if active_mapping is None:
            raise SorConflictError("Active source mapping no longer exists.")
        current_fields = await self._active_field_drafts(
            organization_id=organization_id,
            source=source,
        )
        current_streams = await self.repository.list_streams(
            organization_id=organization_id,
            source_id=source.id,
        )
        if {stream.vendor_object_key for stream in current_streams} != current:
            raise SorConflictError(
                "Active source streams do not match its selected objects."
            )
        complete_streams = tuple(
            SorStreamDraft(
                vendor_object_key=stream.vendor_object_key,
                canonical_entity_kind=stream.canonical_entity_kind,
                strategy=stream.strategy,
                lookback_seconds=stream.lookback_seconds,
                schedule=stream.schedule,
            )
            for stream in current_streams
        ) + tuple(stream_drafts)
        complete_fields = current_fields + tuple(fields)
        source.selected_objects = list(objects)
        source.config_revision += 1
        self._validate_selection(
            source=source,
            fields=complete_fields,
            streams=complete_streams,
            discovered_objects=discovered_objects,
        )
        return await self._publish_selection(
            organization_id=organization_id,
            source=source,
            fields=complete_fields,
            stream_drafts=complete_streams,
            actor_id=actor_id,
            projection_version=active_mapping.projection_version,
            discovered_objects=discovered_objects,
        )

    async def _active_field_drafts(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
    ) -> tuple[SorFieldMappingDraft, ...]:
        """Rehydrate the active mapping without weakening its public projection."""
        mapping_id = source.active_mapping_revision_id
        if mapping_id is None:
            raise SorConflictError("Active source mapping no longer exists.")
        rows = await self.repository.list_field_mappings(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=mapping_id,
        )
        definition_ids = tuple(
            row.custom_field_definition_id
            for row in rows
            if row.custom_field_definition_id is not None
        )
        definitions = {
            definition.id: definition
            for definition in await self.repository.list_custom_field_definitions(
                organization_id=organization_id,
                source_id=source.id,
                definition_ids=definition_ids,
            )
        }
        drafts: list[SorFieldMappingDraft] = []
        for row in rows:
            custom_type = None
            if row.custom_field_definition_id is not None:
                definition = definitions.get(row.custom_field_definition_id)
                if definition is None:
                    raise SorConflictError(
                        "Active mapping custom-field authority is unavailable."
                    )
                custom_type = definition.data_type
            drafts.append(
                SorFieldMappingDraft(
                    vendor_object_key=row.vendor_object_key,
                    vendor_field_key=row.vendor_field_key,
                    canonical_target_path=row.canonical_target_path,
                    custom_type=custom_type,
                    transform_kind=row.transform_kind,
                    transform_config=dict(row.transform_config),
                    direction=row.direction,
                    agent_visible=row.agent_visible,
                    ui_default_column=row.ui_default_column,
                    sensitivity=row.sensitivity,
                )
            )
        return tuple(drafts)

    async def _publish_selection(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        fields: Sequence[SorFieldMappingDraft],
        stream_drafts: Sequence[SorStreamDraft],
        actor_id: UUID | None,
        projection_version: int,
        discovered_objects: dict[str, tuple[str, bool]],
    ) -> SorActivationResult:
        """Publish one validated selection and persist its entire bootstrap DAG."""
        source_id = source.id

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
            stream_rows.append(stream)

        generation = await self.runs.create_generation(
            organization_id=organization_id,
            source_id=source_id,
            stream_ids=tuple(stream.id for stream in stream_rows),
            kind=SorSyncRunKind.BOOTSTRAP,
        )

        return SorActivationResult(
            source=source,
            mapping=mapping,
            streams=tuple(stream_rows),
            generation=generation.generation,
            runs=generation.runs,
        )

    async def publish_mapping(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        mapping_revision_id: UUID,
        actor_id: UUID | None,
    ) -> SorMappingPublicationResult:
        """Publish a replacement and persist its source-wide bootstrap DAG."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        streams = await self.repository.list_streams(
            organization_id=organization_id,
            source_id=source_id,
        )
        if not streams:
            raise SorConflictError(
                "Activate the source before publishing a replacement mapping."
            )
        mapping = await self.repository.get_mapping_revision(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=mapping_revision_id,
            for_update=True,
        )
        if mapping is None:
            raise SorNotFoundError("Mapping revision not found.")

        if mapping.state is SorMappingState.DRAFT:
            mapping = await self.mappings.publish(
                organization_id=organization_id,
                source_id=source_id,
                mapping_revision_id=mapping_revision_id,
                actor_id=actor_id,
            )
        elif (
            mapping.state is not SorMappingState.ACTIVE
            or source.active_mapping_revision_id != mapping.id
        ):
            raise SorConflictError("Only a draft mapping can be published.")

        active_run = await self.repository.get_active_source_sync_run(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if active_run is not None:
            generation = await self.repository.get_sync_generation(
                organization_id=organization_id,
                generation_id=active_run.generation_id,
                for_update=True,
            )
            if generation is None:
                raise SorConflictError("Active source work has no generation.")
            runs = await self.repository.list_generation_runs(
                organization_id=organization_id,
                generation_id=generation.id,
                for_update=True,
            )
            return SorMappingPublicationResult(
                mapping=mapping,
                generation=generation,
                runs=tuple(runs),
            )

        if source.state is SorSourceState.ACTIVE:
            return SorMappingPublicationResult(
                mapping=mapping,
                generation=None,
                runs=(),
            )

        generation = await self.runs.create_generation(
            organization_id=organization_id,
            source_id=source_id,
            stream_ids=tuple(stream.id for stream in streams),
            kind=SorSyncRunKind.BOOTSTRAP,
        )
        return SorMappingPublicationResult(
            mapping=mapping,
            generation=generation.generation,
            runs=generation.runs,
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
        selected_streams = set(selected)
        profile_entities = {
            entity.key: entity
            for entity in self.registry.get_profile(source.profile).entities
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
            missing_dependencies = sorted(manifest_stream.depends_on - selected_streams)
            if missing_dependencies:
                raise SorConfigurationError(
                    f"{manifest_stream.label} requires source objects: "
                    f"{', '.join(missing_dependencies)}."
                )
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


__all__ = [
    "SorActivationResult",
    "SorMappingPublicationResult",
    "SorOnboardingService",
]
