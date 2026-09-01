"""Domain policy for SOR sources, immutable mappings, and inbound projection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import delete, func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.connections.domain import (
    ConnectionAuthKind,
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.models import ExternalConnectionModel
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.registry import SorRegistry

from .contracts import (
    SorAdapterCapabilityManifest,
    SorCanonicalFieldSpec,
    SorConfigurationFieldKind,
    SorCustomFieldType,
    SorDiscoveredField,
    SorDiscoveredSchema,
    SorExternalRecord,
    SorFieldMappingDirection,
    SorFieldMappingDraft,
    SorFieldMappingState,
    SorMappingState,
    SorProfile,
    SorProjectionDisposition,
    SorProjectionOutcome,
    SorSchemaDifference,
    SorSourceState,
    SorSourceTransition,
    SorTransformKind,
    transition_source_state,
)
from .events import (
    register_mapping_published,
    register_schema_changed,
    register_source_transition,
)
from .models import (
    SorCustomFieldDefinitionModel,
    SorCustomFieldValueModel,
    SorFieldMappingModel,
    SorMappingRevisionModel,
    SorRecordModel,
    SorRecordRelationModel,
    SorSchemaRevisionModel,
    SorSourceModel,
)
from .repositories import SorRepository

_VENDOR_KEY = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FIELD_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_CANONICAL_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_SAFE_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_EMPTY_AS_NULL_SOURCE_TYPES = frozenset(
    {"boolean", "bounded_json", "date", "decimal", "enum", "string_array", "timestamp"}
)


class SorError(Exception):
    """Base domain refusal whose message is safe for an operator."""


class SorNotFoundError(SorError):
    """A tenant-scoped SOR aggregate does not exist."""


class SorConfigurationError(SorError):
    """Source or mapping configuration cannot execute safely."""


class SorConflictError(SorError):
    """An immutable revision or idempotent projection conflicts."""


class SorProjectionError(SorError):
    """A source payload cannot satisfy its published mapping."""


@dataclass(frozen=True, slots=True)
class _SourceDraft:
    """Normalized source identity used for create-request idempotency."""

    configuration: dict[str, object]
    freshness_target_seconds: int
    manifest: SorAdapterCapabilityManifest
    name: str
    profile: SorProfile
    required_sync_interval_seconds: int
    selected_objects: tuple[str, ...]
    vendor_key: str


class SorSourceService:
    """Create and move source headers without performing vendor I/O."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.registry = registry or get_sor_registry()

    async def create(
        self,
        *,
        organization_id: UUID,
        onboarding_attempt_id: UUID,
        name: str,
        profile: SorProfile,
        vendor_key: str,
        external_connection_id: UUID,
        configuration: Mapping[str, object] | None = None,
        selected_objects: Sequence[str] = (),
        freshness_target_seconds: int = 900,
        required_sync_interval_seconds: int = 900,
    ) -> SorSourceModel:
        """Create or return the one draft owned by an onboarding attempt."""
        draft = self._prepare_draft(
            name=name,
            profile=profile,
            vendor_key=vendor_key,
            configuration=configuration,
            selected_objects=selected_objects,
            freshness_target_seconds=freshness_target_seconds,
            required_sync_interval_seconds=required_sync_interval_seconds,
        )
        existing = await self._reuse_attempt(
            organization_id=organization_id,
            onboarding_attempt_id=onboarding_attempt_id,
            draft=draft,
            expected_external_connection_id=external_connection_id,
        )
        if existing is not None:
            return existing

        required_scopes = {
            scope
            for object_key in draft.selected_objects
            for scope in draft.manifest.required_scopes.get(object_key, ())
        }
        connection = await self.repository.get_connection(
            organization_id=organization_id,
            connection_id=external_connection_id,
            vendor_key=draft.vendor_key,
            for_update=True,
        )
        if connection is None:
            raise SorNotFoundError("External connection not found.")
        _validate_source_connection(
            connection=connection,
            manifest=draft.manifest,
            required_scopes=required_scopes,
        )
        await self._require_unclaimed_connection(
            organization_id=organization_id,
            connection=connection,
            profile=draft.profile,
        )

        source = SorSourceModel(
            organization_id=organization_id,
            onboarding_attempt_id=onboarding_attempt_id,
            name=draft.name,
            profile=draft.profile,
            vendor_key=draft.vendor_key,
            external_connection_id=external_connection_id,
            configuration=draft.configuration,
            selected_objects=list(draft.selected_objects),
            freshness_target_seconds=draft.freshness_target_seconds,
            required_sync_interval_seconds=draft.required_sync_interval_seconds,
            state=SorSourceState.DRAFT,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def reuse_onboarding_attempt(
        self,
        *,
        organization_id: UUID,
        onboarding_attempt_id: UUID,
        name: str,
        profile: SorProfile,
        vendor_key: str,
        configuration: Mapping[str, object] | None = None,
        selected_objects: Sequence[str] = (),
        freshness_target_seconds: int = 900,
        required_sync_interval_seconds: int = 900,
        expected_instance_origin: str | None = None,
    ) -> SorSourceModel | None:
        """Return a matching prior source while holding the attempt lock."""
        draft = self._prepare_draft(
            name=name,
            profile=profile,
            vendor_key=vendor_key,
            configuration=configuration,
            selected_objects=selected_objects,
            freshness_target_seconds=freshness_target_seconds,
            required_sync_interval_seconds=required_sync_interval_seconds,
        )
        return await self._reuse_attempt(
            organization_id=organization_id,
            onboarding_attempt_id=onboarding_attempt_id,
            draft=draft,
            expected_instance_origin=expected_instance_origin,
        )

    def _prepare_draft(
        self,
        *,
        name: str,
        profile: SorProfile,
        vendor_key: str,
        configuration: Mapping[str, object] | None,
        selected_objects: Sequence[str],
        freshness_target_seconds: int,
        required_sync_interval_seconds: int,
    ) -> _SourceDraft:
        """Normalize and validate the stable, non-secret creation payload."""
        normalized_name = name.strip()
        normalized_vendor = vendor_key.strip().lower()
        if not 1 <= len(normalized_name) <= 160:
            raise SorConfigurationError("Source name must contain 1 to 160 characters.")
        if not _VENDOR_KEY.fullmatch(normalized_vendor):
            raise SorConfigurationError(
                "Source vendor must be a lowercase machine identifier."
            )
        if freshness_target_seconds <= 0 or required_sync_interval_seconds <= 0:
            raise SorConfigurationError("Source sync intervals must be positive.")

        try:
            manifest = self.registry.get_manifest(
                profile=profile,
                vendor_key=normalized_vendor,
            )
        except KeyError as error:
            raise SorConfigurationError(
                f"{profile.value}/{normalized_vendor} is catalog-only and cannot "
                "create a source yet."
            ) from error

        objects = _unique_keys(selected_objects, field_name="selected object")
        if not objects:
            raise SorConfigurationError(
                "Select at least one vendor object for this source."
            )
        available_objects = {stream.key for stream in manifest.streams}
        unknown_objects = set(objects) - available_objects
        if unknown_objects:
            raise SorConfigurationError(
                "Source selected unsupported vendor objects: "
                + ", ".join(sorted(unknown_objects))
                + "."
            )
        normalized_configuration = _normalize_source_configuration(
            configuration,
            manifest=manifest,
        )
        return _SourceDraft(
            configuration=normalized_configuration,
            freshness_target_seconds=freshness_target_seconds,
            manifest=manifest,
            name=normalized_name,
            profile=profile,
            required_sync_interval_seconds=required_sync_interval_seconds,
            selected_objects=objects,
            vendor_key=normalized_vendor,
        )

    async def _reuse_attempt(
        self,
        *,
        organization_id: UUID,
        onboarding_attempt_id: UUID,
        draft: _SourceDraft,
        expected_external_connection_id: UUID | None = None,
        expected_instance_origin: str | None = None,
    ) -> SorSourceModel | None:
        await self.repository.acquire_source_onboarding_lock(
            organization_id=organization_id,
            onboarding_attempt_id=onboarding_attempt_id,
        )
        existing = await self.repository.get_source_by_onboarding_attempt(
            organization_id=organization_id,
            onboarding_attempt_id=onboarding_attempt_id,
        )
        if existing is None:
            return None
        if existing.deleted:
            raise SorConflictError(
                "This onboarding attempt belongs to a deleted source. Start new."
            )
        _require_matching_source_attempt(existing=existing, draft=draft)
        if (
            expected_external_connection_id is not None
            and existing.external_connection_id != expected_external_connection_id
        ):
            raise SorConflictError(
                "This onboarding attempt is already bound to another connection."
            )
        if expected_instance_origin is not None:
            connection = await self.repository.get_connection(
                organization_id=organization_id,
                connection_id=existing.external_connection_id,
                vendor_key=draft.vendor_key,
            )
            if connection is None or connection.instance_origin != expected_instance_origin:
                raise SorConflictError(
                    "This onboarding attempt is already bound to another instance."
                )
        return existing

    async def reconnect_before_activation(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        external_connection_id: UUID,
        selected_objects: Sequence[str],
        expected_config_revision: int,
    ) -> SorSourceModel:
        """Replace a draft source connection without changing an active source."""
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.config_revision != expected_config_revision:
            raise SorConflictError("SOR source configuration changed.")
        if source.active_mapping_revision_id is not None or source.state not in {
            SorSourceState.DRAFT,
            SorSourceState.DEGRADED,
            SorSourceState.REAUTH_REQUIRED,
        }:
            raise SorConflictError(
                "Only a source awaiting activation can change connections."
            )

        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        objects = _unique_keys(selected_objects, field_name="selected object")
        if not objects:
            raise SorConfigurationError("Select at least one vendor object.")
        available_objects = {stream.key for stream in manifest.streams}
        unknown_objects = set(objects) - available_objects
        if unknown_objects:
            raise SorConfigurationError(
                "Reconnect using supported vendor objects only: "
                + ", ".join(sorted(unknown_objects))
                + "."
            )

        connection = await self.repository.get_connection(
            organization_id=organization_id,
            connection_id=external_connection_id,
            vendor_key=source.vendor_key,
            for_update=True,
        )
        if connection is None:
            raise SorNotFoundError("External connection not found.")
        required_scopes = {
            scope
            for object_key in objects
            for scope in manifest.required_scopes.get(object_key, ())
        }
        _validate_source_connection(
            connection=connection,
            manifest=manifest,
            required_scopes=required_scopes,
        )

        if source.external_connection_id != connection.id:
            raise SorConflictError(
                "A source connection cannot be replaced during setup. "
                "Start new or reauthorize the existing source."
            )
        await self._require_unclaimed_connection(
            organization_id=organization_id,
            connection=connection,
            profile=source.profile,
            source_id=source.id,
        )

        if (
            source.external_connection_id == connection.id
            and tuple(source.selected_objects or ()) == objects
        ):
            return source

        source.external_connection_id = connection.id
        source.selected_objects = list(objects)
        source.active_schema_revision_id = None
        source.config_revision += 1
        source.last_verified_at = None
        source.last_error_code = None
        source.last_error_summary = None
        await self.session.flush()
        return source

    async def _require_unclaimed_connection(
        self,
        *,
        organization_id: UUID,
        connection: ExternalConnectionModel,
        profile: SorProfile,
        source_id: UUID | None = None,
    ) -> None:
        """Keep one external connection owned by one source onboarding flow."""
        connector = await self.repository.get_connector_for_connection(
            organization_id=organization_id,
            connection_id=connection.id,
        )
        if connection.auth_kind == ConnectionAuthKind.OAUTH2:
            if connector is None:
                raise SorConfigurationError(
                    "The OAuth connection has no System of Record configuration."
                )
            if connector.profile is not profile:
                raise SorConfigurationError(
                    "The OAuth configuration belongs to another System of Record."
                )
            if connector.vendor_key != connection.vendor_key:
                raise SorConfigurationError(
                    "The OAuth configuration does not match the connection vendor."
                )

        claims = await self.repository.list_sources_for_connection(
            organization_id=organization_id,
            connection_id=connection.id,
        )
        if any(claim.id != source_id for claim in claims):
            raise SorConflictError(
                "This connection already belongs to another source. "
                "Configure and authorize a new connection."
            )

    async def get(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        for_update: bool = False,
    ) -> SorSourceModel:
        source = await self.repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=for_update,
        )
        if source is None:
            raise SorNotFoundError("SOR source not found.")
        return source

    async def update_selection_from_discovery(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        selected_objects: Sequence[str],
        expected_config_revision: int,
    ) -> SorSourceModel:
        """Select discovered objects before mapping without trusting raw object IDs."""
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.config_revision != expected_config_revision:
            raise SorConflictError("SOR source configuration changed.")
        if (
            source.state is not SorSourceState.DRAFT
            or source.active_schema_revision_id is None
            or source.active_mapping_revision_id is not None
        ):
            raise SorConflictError(
                "Object selection can change only after discovery and before mapping."
            )
        objects = await self.validate_discovered_selection(
            organization_id=organization_id,
            source=source,
            selected_objects=selected_objects,
        )
        if tuple(source.selected_objects or ()) != objects:
            source.selected_objects = list(objects)
            source.config_revision += 1
            await self.session.flush()
        return source

    async def validate_discovered_selection(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        selected_objects: Sequence[str],
    ) -> tuple[str, ...]:
        """Validate source objects against discovery, adapter, and live authority."""
        objects = _unique_keys(selected_objects, field_name="selected object")
        if not objects:
            raise SorConfigurationError("Select at least one source object.")
        if source.organization_id != organization_id:
            raise SorNotFoundError("SOR source not found.")
        if source.active_schema_revision_id is None:
            raise SorConflictError("Discover a source schema before selecting objects.")
        schema = await self.repository.get_schema_revision(
            organization_id=organization_id,
            source_id=source.id,
            schema_revision_id=source.active_schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Active source schema no longer exists.")
        discovered = snapshot_objects(schema.schema_snapshot)
        unknown = set(objects) - set(discovered)
        if unknown:
            raise SorConfigurationError(
                "Source selected undiscovered objects: "
                + ", ".join(sorted(unknown))
                + "."
            )
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        static_keys = {stream.key for stream in manifest.streams}
        custom_keys = set(objects) - static_keys
        if custom_keys and (
            not manifest.supports_custom_objects
            or any(not discovered[key][1] for key in custom_keys)
        ):
            raise SorConfigurationError(
                "This adapter cannot enable the selected custom objects."
            )
        connection = await self.repository.get_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            vendor_key=source.vendor_key,
        )
        if connection is None:
            raise SorConfigurationError(
                "The source connection is unavailable. Reconnect before continuing."
            )
        required_scopes = {
            scope
            for object_key in objects
            for scope in manifest.required_scopes.get(object_key, ())
        }
        if custom_keys:
            required_scopes.update(manifest.custom_object_required_scopes)
        _validate_source_connection(
            connection=connection,
            manifest=manifest,
            required_scopes=required_scopes,
            unavailable_message=(
                "The source connection is unavailable. Reconnect before continuing."
            ),
        )
        return objects

    async def transition(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        transition: SorSourceTransition,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> SorSourceModel:
        """Apply one deterministic lifecycle command while holding the source."""
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        previous_state = source.state
        source.state = transition_source_state(source.state, transition)
        if transition in {
            SorSourceTransition.VERIFICATION_FAILED,
            SorSourceTransition.DISCOVERY_FAILED,
            SorSourceTransition.BOOTSTRAP_FAILED,
            SorSourceTransition.SYNC_FAILED,
            SorSourceTransition.REAUTHORIZATION_REQUIRED,
        }:
            source.last_error_code = _safe_error_code(error_code)
            source.last_error_summary = _safe_error_summary(error_summary)
        else:
            source.last_error_code = None
            source.last_error_summary = None
        if transition is SorSourceTransition.VERIFICATION_SUCCEEDED:
            source.last_verified_at = datetime.now(timezone.utc)
        if transition in {
            SorSourceTransition.BOOTSTRAP_SUCCEEDED,
            SorSourceTransition.SYNC_SUCCEEDED,
        }:
            source.last_successful_sync_at = datetime.now(timezone.utc)
        await self.session.flush()
        register_source_transition(
            organization_id=organization_id,
            source_id=source.id,
            profile=source.profile,
            vendor_key=source.vendor_key,
            config_revision=source.config_revision,
            previous_state=previous_state,
            current_state=source.state,
            error_code=source.last_error_code,
        )
        return source

    async def complete_reauthorization(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        expected_connection_revision: int,
    ) -> SorSourceModel:
        """Restore one activated source after its exact connection is renewed."""
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state is not SorSourceState.REAUTH_REQUIRED:
            raise SorConflictError(
                "Only a source awaiting reauthorization can resume."
            )
        if (
            source.active_schema_revision_id is None
            or source.active_mapping_revision_id is None
        ):
            raise SorConflictError(
                "This source has not been activated. Continue source setup instead."
            )

        connection = await self.repository.get_connection(
            organization_id=organization_id,
            connection_id=source.external_connection_id,
            vendor_key=source.vendor_key,
            for_update=True,
        )
        if connection is None:
            raise SorNotFoundError("External connection not found.")
        if connection.revision != expected_connection_revision:
            raise SorConflictError(
                "The source connection changed while reauthorization completed."
            )
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        required_scopes = {
            scope
            for object_key in source.selected_objects
            for scope in manifest.required_scopes.get(str(object_key), ())
        }
        _validate_source_connection(
            connection=connection,
            manifest=manifest,
            required_scopes=required_scopes,
            unavailable_message=(
                "The source connection is not active after reauthorization."
            ),
        )
        return await self.transition(
            organization_id=organization_id,
            source_id=source_id,
            transition=SorSourceTransition.REAUTHORIZATION_SUCCEEDED,
        )

    async def prepare_schema_refresh(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
    ) -> tuple[int, UUID]:
        """Pin an active source's config and mapping before vendor discovery."""
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
            raise SorConfigurationError(
                "Only an active or degraded source can refresh its schema."
            )
        if (
            source.active_schema_revision_id is None
            or source.active_mapping_revision_id is None
        ):
            raise SorConfigurationError(
                "Complete source onboarding before refreshing its schema."
            )
        active_run = await self.repository.get_active_source_sync_run(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if active_run is not None:
            raise SorConflictError(
                "Wait for active source synchronization to finish before "
                "refreshing its schema."
            )
        return source.config_revision, source.active_mapping_revision_id

    async def record_schema_refresh_failure(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        expected_config_revision: int,
        expected_mapping_revision_id: UUID,
        error_code: str,
        error_summary: str,
    ) -> None:
        """Record a safe refresh error without hiding the active projection."""
        source = await self._locked_schema_refresh_source(
            organization_id=organization_id,
            source_id=source_id,
            expected_config_revision=expected_config_revision,
            expected_mapping_revision_id=expected_mapping_revision_id,
        )
        source.last_error_code = _safe_error_code(error_code)
        source.last_error_summary = _safe_error_summary(error_summary)
        await self.session.flush()

    async def record_schema_refresh_reauthorization_required(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        expected_config_revision: int,
        expected_mapping_revision_id: UUID,
        error_code: str,
        error_summary: str,
    ) -> None:
        """Fail closed when the pinned refresh credential needs authorization."""
        source = await self._locked_schema_refresh_source(
            organization_id=organization_id,
            source_id=source_id,
            expected_config_revision=expected_config_revision,
            expected_mapping_revision_id=expected_mapping_revision_id,
        )
        source.state = transition_source_state(
            source.state,
            SorSourceTransition.REAUTHORIZATION_REQUIRED,
        )
        source.last_error_code = _safe_error_code(error_code)
        source.last_error_summary = _safe_error_summary(error_summary)
        await self.session.flush()

    async def _locked_schema_refresh_source(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        expected_config_revision: int,
        expected_mapping_revision_id: UUID,
    ) -> SorSourceModel:
        source = await self.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
            raise SorConflictError(
                "SOR source lifecycle changed during schema refresh."
            )
        if (
            source.config_revision != expected_config_revision
            or source.active_mapping_revision_id != expected_mapping_revision_id
        ):
            raise SorConflictError(
                "SOR source authority changed during schema refresh."
            )
        return source


class SorSchemaService:
    """Commit complete schema snapshots and surface drift without widening data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.sources = SorSourceService(session)

    async def record_discovery(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        schema: SorDiscoveredSchema,
        expected_config_revision: int,
        expected_mapping_revision_id: UUID | None,
        verified_at: datetime,
        discovery_run_id: UUID | None = None,
    ) -> tuple[SorSchemaRevisionModel, SorSchemaDifference]:
        """Atomically activate one complete immutable discovery result."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state not in {
            SorSourceState.DISCOVERING,
            SorSourceState.ACTIVE,
            SorSourceState.DEGRADED,
        }:
            raise SorConfigurationError(
                f"Schema discovery cannot complete while source is {source.state.value}."
            )
        if (
            source.config_revision != expected_config_revision
            or source.active_mapping_revision_id != expected_mapping_revision_id
        ):
            raise SorConflictError("SOR source authority changed during discovery.")
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise SorConfigurationError(
                "Schema verification time must include a timezone."
            )
        active_run = await self.repository.get_active_source_sync_run(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if active_run is not None:
            raise SorConflictError(
                "Wait for active source synchronization to finish before "
                "committing schema discovery."
            )
        snapshot = _schema_snapshot(schema)
        digest = _sha256(snapshot)
        previous = None
        if source.active_schema_revision_id is not None:
            previous = await self.repository.get_schema_revision(
                organization_id=organization_id,
                source_id=source_id,
                schema_revision_id=source.active_schema_revision_id,
            )
        difference = _schema_difference(
            previous.schema_snapshot if previous is not None else None,
            snapshot,
        )
        if previous is not None and previous.schema_hash == digest:
            if source.state is SorSourceState.DISCOVERING:
                source.state = transition_source_state(
                    source.state,
                    SorSourceTransition.DISCOVERY_SUCCEEDED,
                )
            source.last_error_code = None
            source.last_error_summary = None
            source.last_verified_at = verified_at
            await self.session.flush()
            return previous, difference

        revision = await self.repository.latest_schema_revision(
            organization_id=organization_id,
            source_id=source_id,
        )
        row = SorSchemaRevisionModel(
            organization_id=organization_id,
            source_id=source_id,
            revision=revision + 1,
            schema_hash=digest,
            schema_snapshot=snapshot,
            vendor_api_version=schema.vendor_api_version,
            discovery_run_id=discovery_run_id,
        )
        self.session.add(row)
        await self.session.flush()

        active_mapping_revision_id = source.active_mapping_revision_id
        if active_mapping_revision_id is not None:
            await self._apply_drift_to_mapping(
                organization_id=organization_id,
                source=source,
                mapping_revision_id=active_mapping_revision_id,
                difference=difference,
            )
        await self._refresh_custom_definitions(
            organization_id=organization_id,
            source_id=source_id,
            schema=schema,
        )
        source.active_schema_revision_id = row.id
        if source.state is SorSourceState.DISCOVERING:
            source.state = transition_source_state(
                source.state,
                SorSourceTransition.DISCOVERY_SUCCEEDED,
            )
        source.last_error_code = None
        source.last_error_summary = None
        source.last_verified_at = verified_at
        await self.session.flush()
        if previous is not None:
            register_schema_changed(
                organization_id=organization_id,
                source_id=source.id,
                previous_schema_revision_id=previous.id,
                schema_revision_id=row.id,
                difference=difference,
            )
        return row, difference

    async def _apply_drift_to_mapping(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        mapping_revision_id: UUID,
        difference: SorSchemaDifference,
    ) -> None:
        mapping = await self.repository.get_mapping_revision(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=mapping_revision_id,
            for_update=True,
        )
        if mapping is None or not difference.changed:
            return
        fields = await self.repository.list_field_mappings(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=mapping.id,
        )
        invalid = set(difference.type_changed)
        unavailable = set(difference.removed)
        for field in fields:
            identity = f"{field.vendor_object_key}.{field.vendor_field_key}"
            if identity in invalid:
                field.state = SorFieldMappingState.INCOMPATIBLE
                field.incompatibility_reason = "Source field type changed."
            elif identity in unavailable:
                field.state = SorFieldMappingState.INCOMPATIBLE
                field.incompatibility_reason = "Source field was removed."
        if invalid:
            mapping.state = SorMappingState.INVALID
        elif mapping.state is SorMappingState.ACTIVE:
            mapping.state = SorMappingState.STALE

    async def _refresh_custom_definitions(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        schema: SorDiscoveredSchema,
    ) -> None:
        definitions = await self.repository.list_custom_field_definitions(
            organization_id=organization_id,
            source_id=source_id,
        )
        discovered = {
            (object_.key, field.key): field
            for object_ in schema.objects
            for field in object_.fields
        }
        now = datetime.now(timezone.utc)
        for definition in definitions:
            field = discovered.get(
                (definition.vendor_object_key, definition.vendor_field_key)
            )
            if field is None:
                definition.removed_at = definition.removed_at or now
                continue
            definition.label = field.label
            definition.description = field.description
            definition.source_group = field.group
            definition.readable = True
            definition.writable = field.writable
            definition.last_seen_at = now
            definition.removed_at = None


class SorMappingService:
    """Create immutable field selections and publish one active interpretation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: SorRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.registry = registry or get_sor_registry()
        self.sources = SorSourceService(session, registry=self.registry)

    async def create_draft(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        fields: Sequence[SorFieldMappingDraft],
        actor_id: UUID | None = None,
        projection_version: int = 1,
    ) -> SorMappingRevisionModel:
        """Create a new draft from exact stable keys in the active schema."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source.state is SorSourceState.DISABLED:
            raise SorConfigurationError("Disabled sources cannot create mappings.")
        if source.active_schema_revision_id is None:
            raise SorConfigurationError("Discover a source schema before mapping it.")
        if projection_version <= 0:
            raise SorConfigurationError("Projection version must be positive.")
        schema = await self.repository.get_schema_revision(
            organization_id=organization_id,
            source_id=source_id,
            schema_revision_id=source.active_schema_revision_id,
        )
        if schema is None:
            raise SorConflictError("Active source schema no longer exists.")
        discovered = _snapshot_fields(schema.schema_snapshot)
        discovered_objects = snapshot_objects(schema.schema_snapshot)
        selected_objects = set(source.selected_objects or ())
        identities = [
            (field.vendor_object_key, field.vendor_field_key) for field in fields
        ]
        if not identities or len(identities) != len(set(identities)):
            raise SorConfigurationError(
                "Mapping must contain unique discovered fields."
            )
        unselected_objects = {
            object_key for object_key, _field_key in identities
        } - selected_objects
        if unselected_objects:
            raise SorConfigurationError(
                "Mapping references objects outside the source selection: "
                + ", ".join(sorted(unselected_objects))
                + "."
            )
        canonical_targets = [
            (field.vendor_object_key, field.canonical_target_path)
            for field in fields
            if field.direction is not SorFieldMappingDirection.IGNORE
            and field.canonical_target_path is not None
        ]
        if len(canonical_targets) != len(set(canonical_targets)):
            raise SorConfigurationError(
                "Each canonical field can be mapped only once per source object."
            )

        revision = await self.repository.latest_mapping_revision(
            organization_id=organization_id,
            source_id=source_id,
        )
        mapping = SorMappingRevisionModel(
            organization_id=organization_id,
            source_id=source_id,
            revision=revision + 1,
            source_schema_revision_id=schema.id,
            state=SorMappingState.DRAFT,
            created_by=actor_id,
            projection_version=projection_version,
        )
        self.session.add(mapping)
        await self.session.flush()

        rows: list[SorFieldMappingModel] = []
        for draft in fields:
            object_metadata = discovered_objects.get(draft.vendor_object_key)
            if object_metadata is None:
                raise SorConfigurationError(
                    "Mapping references an object absent from its schema revision."
                )
            if object_metadata[1]:
                _validate_custom_dataset_mapping(draft)
            discovered_field = discovered.get(
                (draft.vendor_object_key, draft.vendor_field_key)
            )
            if discovered_field is None:
                raise SorConfigurationError(
                    "Mapping references a field absent from its schema revision: "
                    f"{draft.vendor_object_key}.{draft.vendor_field_key}."
                )
            rows.append(
                await self._field_row(
                    organization_id=organization_id,
                    source=source,
                    mapping=mapping,
                    draft=draft,
                    discovered=discovered_field,
                )
            )
        self.session.add_all(rows)
        await self.session.flush()
        return mapping

    async def publish(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        mapping_revision_id: UUID,
        actor_id: UUID | None = None,
    ) -> SorMappingRevisionModel:
        """Atomically supersede the prior mapping and activate this draft."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        active_run = await self.repository.get_active_source_sync_run(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if active_run is not None:
            raise SorConflictError(
                "Wait for active source synchronization to finish before "
                "publishing a mapping."
            )
        mapping = await self.repository.get_mapping_revision(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=mapping_revision_id,
            for_update=True,
        )
        if mapping is None:
            raise SorNotFoundError("Mapping revision not found.")
        if mapping.state is not SorMappingState.DRAFT:
            raise SorConflictError("Only a draft mapping can be published.")
        if mapping.source_schema_revision_id != source.active_schema_revision_id:
            raise SorConflictError(
                "Mapping schema is stale; create a draft from the active schema."
            )
        fields = await self.repository.list_field_mappings(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=mapping.id,
        )
        if not fields or not any(
            field.direction is not SorFieldMappingDirection.IGNORE for field in fields
        ):
            raise SorConfigurationError("Published mappings must select a field.")
        if any(field.state is SorFieldMappingState.INCOMPATIBLE for field in fields):
            raise SorConfigurationError("Incompatible fields cannot be published.")

        if source.active_mapping_revision_id is not None:
            previous = await self.repository.get_mapping_revision(
                organization_id=organization_id,
                source_id=source_id,
                mapping_revision_id=source.active_mapping_revision_id,
                for_update=True,
            )
            if previous is not None and previous.id != mapping.id:
                previous.state = SorMappingState.SUPERSEDED
        mapping.state = SorMappingState.ACTIVE
        mapping.published_at = datetime.now(timezone.utc)
        mapping.published_by = actor_id
        source.active_mapping_revision_id = mapping.id
        source.config_revision += 1
        source.state = transition_source_state(
            source.state,
            SorSourceTransition.BEGIN_BOOTSTRAP,
        )
        await self.session.flush()
        register_mapping_published(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=mapping.id,
            mapping_revision=mapping.revision,
        )
        return mapping

    async def _field_row(
        self,
        *,
        organization_id: UUID,
        source: SorSourceModel,
        mapping: SorMappingRevisionModel,
        draft: SorFieldMappingDraft,
        discovered: SorDiscoveredField,
    ) -> SorFieldMappingModel:
        _require_key(draft.vendor_object_key, field_name="vendor object")
        _require_key(draft.vendor_field_key, field_name="vendor field")
        canonical = (
            draft.canonical_target_path.strip()
            if draft.canonical_target_path is not None
            else None
        )
        if canonical == "":
            canonical = None
        if canonical is not None and not _CANONICAL_PATH.fullmatch(canonical):
            raise SorConfigurationError("Canonical target path is invalid.")
        canonical_field = (
            None
            if canonical is None
            else self._canonical_field(
                source=source,
                vendor_object_key=draft.vendor_object_key,
                canonical_target_path=canonical,
            )
        )
        is_custom = draft.custom_type is not None
        if draft.direction is SorFieldMappingDirection.IGNORE:
            if canonical is not None or is_custom:
                raise SorConfigurationError("Ignored fields cannot have a target.")
            if draft.agent_visible or draft.ui_default_column:
                raise SorConfigurationError("Ignored fields cannot be exposed.")
        elif (canonical is None) == (not is_custom):
            raise SorConfigurationError(
                "Mapped fields require exactly one canonical or custom target."
            )
        if (
            draft.direction is SorFieldMappingDirection.READ_WRITE
            and not discovered.writable
        ):
            raise SorConfigurationError(
                f"Source field {draft.vendor_field_key} is not writable."
            )
        if (
            draft.direction is SorFieldMappingDirection.READ_WRITE
            and canonical_field is not None
            and not canonical_field.writable
        ):
            raise SorConfigurationError(
                f"Canonical field {canonical_field.key} is read-only."
            )
        _validate_transform(draft.transform_kind, draft.transform_config)
        if draft.custom_type is SorCustomFieldType.REFERENCE and (
            draft.transform_kind is not SorTransformKind.IDENTITY_REFERENCE
        ):
            raise SorConfigurationError(
                "Custom REFERENCE fields require IDENTITY_REFERENCE transform."
            )

        definition = None
        if is_custom:
            definition = await self._ensure_custom_definition(
                organization_id=organization_id,
                source_id=source.id,
                draft=draft,
                discovered=discovered,
            )
        return SorFieldMappingModel(
            organization_id=organization_id,
            source_id=source.id,
            mapping_revision_id=mapping.id,
            vendor_object_key=draft.vendor_object_key,
            vendor_field_key=draft.vendor_field_key,
            source_label=discovered.label,
            source_data_type=discovered.data_type,
            canonical_target_path=canonical,
            custom_field_definition_id=definition.id if definition else None,
            transform_kind=draft.transform_kind,
            transform_config=dict(draft.transform_config),
            direction=draft.direction,
            agent_visible=draft.agent_visible,
            ui_default_column=draft.ui_default_column,
            nullable=discovered.nullable,
            enum_choices=list(discovered.choices),
            sensitivity=draft.sensitivity,
            writable_capability=discovered.writable,
            state=SorFieldMappingState.ACTIVE,
        )

    def _canonical_field(
        self,
        *,
        source: SorSourceModel,
        vendor_object_key: str,
        canonical_target_path: str,
    ) -> SorCanonicalFieldSpec:
        manifest = self.registry.get_manifest(
            profile=source.profile,
            vendor_key=source.vendor_key,
        )
        stream = next(
            (
                candidate
                for candidate in manifest.streams
                if candidate.key == vendor_object_key
            ),
            None,
        )
        if stream is None:
            raise SorConfigurationError(
                "Mapping references an object outside the source selection."
            )
        entity = next(
            item
            for item in self.registry.get_profile(source.profile).entities
            if item.key == stream.canonical_entity
        )
        field = next(
            (
                candidate
                for candidate in entity.fields
                if candidate.key == canonical_target_path
            ),
            None,
        )
        if field is None:
            raise SorConfigurationError(
                f"{canonical_target_path} is not a canonical "
                f"{stream.canonical_entity} field."
            )
        return field

    async def _ensure_custom_definition(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        draft: SorFieldMappingDraft,
        discovered: SorDiscoveredField,
    ) -> SorCustomFieldDefinitionModel:
        custom_type = draft.custom_type
        if custom_type is None:
            raise SorConfigurationError("Custom field type is required.")
        definition = await self.repository.get_custom_field_definition(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=draft.vendor_object_key,
            vendor_field_key=draft.vendor_field_key,
            for_update=True,
        )
        now = datetime.now(timezone.utc)
        if definition is None:
            definition = SorCustomFieldDefinitionModel(
                organization_id=organization_id,
                source_id=source_id,
                vendor_object_key=draft.vendor_object_key,
                vendor_field_key=draft.vendor_field_key,
                label=discovered.label,
                description=discovered.description,
                data_type=custom_type,
                choices=list(discovered.choices),
                source_group=discovered.group,
                readable=True,
                writable=discovered.writable,
                sensitivity=draft.sensitivity,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(definition)
            await self.session.flush()
            return definition
        definition.label = discovered.label
        definition.description = discovered.description
        definition.data_type = custom_type
        definition.choices = list(discovered.choices)
        definition.source_group = discovered.group
        definition.readable = True
        definition.writable = discovered.writable
        definition.sensitivity = draft.sensitivity
        definition.last_seen_at = now
        definition.removed_at = None
        return definition


class SorProjectionService:
    """Project inbound snapshots only; this module cannot enqueue vendor writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SorRepository(session)
        self.sources = SorSourceService(session)

    async def project(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        external_record: SorExternalRecord,
        canonical_entity_kind: str,
        human_external_key: str | None = None,
        sync_run_id: UUID | None = None,
    ) -> SorProjectionOutcome:
        """Idempotently upsert mapping-approved data and replace typed custom rows."""
        source = await self.sources.get(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source.state not in {
            SorSourceState.BOOTSTRAPPING,
            SorSourceState.ACTIVE,
            SorSourceState.DEGRADED,
        }:
            raise SorProjectionError(
                f"Source {source.id} cannot project while {source.state.value}."
            )
        if source.active_mapping_revision_id is None:
            raise SorProjectionError("Source has no published mapping.")
        mapping = await self.repository.get_mapping_revision(
            organization_id=organization_id,
            source_id=source_id,
            mapping_revision_id=source.active_mapping_revision_id,
        )
        if mapping is None or mapping.state not in {
            SorMappingState.ACTIVE,
            SorMappingState.STALE,
        }:
            raise SorProjectionError("Source mapping is not projectable.")
        fields = [
            field
            for field in await self.repository.list_field_mappings(
                organization_id=organization_id,
                source_id=source_id,
                mapping_revision_id=mapping.id,
            )
            if field.vendor_object_key == external_record.vendor_object_key
            and field.direction is not SorFieldMappingDirection.IGNORE
            and field.state is SorFieldMappingState.ACTIVE
        ]
        if not fields:
            raise SorProjectionError(
                "Published mapping does not select this vendor object."
            )

        selected: dict[str, object] = {}
        canonical: dict[str, object] = {}
        custom: list[tuple[SorFieldMappingModel, object]] = []
        agent_visible: dict[str, object] = {}
        for field in fields:
            if field.vendor_field_key not in external_record.payload:
                if field.nullable:
                    continue
                raise SorProjectionError(
                    f"Required source field is missing: {field.vendor_field_key}."
                )
            raw = external_record.payload[field.vendor_field_key]
            if _mapped_value_is_absent(field, raw):
                if field.nullable:
                    continue
                raise SorProjectionError(
                    f"Required source field is null: {field.vendor_field_key}."
                )
            selected[field.vendor_field_key] = _json_safe(raw)
            transformed = _transform(
                field.transform_kind,
                raw,
                field.transform_config,
            )
            if field.canonical_target_path is not None:
                canonical[field.canonical_target_path] = transformed
                agent_key = field.canonical_target_path
            elif field.custom_field_definition_id is not None:
                custom.append((field, transformed))
                agent_key = _custom_field_key(field.custom_field_definition_id)
            else:
                raise SorProjectionError("Mapped field target is unavailable.")
            if field.agent_visible:
                agent_visible[agent_key] = _json_safe(transformed)

        _bounded_json(
            selected,
            maximum=1_048_576,
            field_name="selected source payload",
            expected_type=dict,
        )
        _bounded_json(
            agent_visible,
            maximum=1_048_576,
            field_name="Agent-visible payload",
            expected_type=dict,
        )
        payload_hash = _sha256(selected)
        search_text = _projection_search_text(canonical, custom)
        agent_search_text = _search_text(agent_visible)
        record = await self.repository.get_record_by_identity(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=external_record.vendor_object_key,
            vendor_external_id=external_record.external_id,
            for_update=True,
        )
        if record is None:
            record = SorRecordModel(
                organization_id=organization_id,
                source_id=source_id,
                profile=source.profile,
                canonical_entity_kind=canonical_entity_kind,
                vendor_object_key=external_record.vendor_object_key,
                vendor_external_id=external_record.external_id,
                human_external_key=human_external_key,
                source_created_at=external_record.source_created_at,
                source_updated_at=external_record.source_updated_at,
                source_revision=external_record.source_revision,
                selected_raw_payload=selected,
                agent_visible_payload=agent_visible,
                payload_hash=payload_hash,
                mapping_revision_id=mapping.id,
                mapping_projection_version=mapping.projection_version,
                last_successful_sync_run_id=sync_run_id,
                source_url=external_record.source_url,
                search_text=search_text,
                agent_search_text=agent_search_text,
            )
            record.search_vector = func.to_tsvector("simple", record.search_text)
            record.agent_search_vector = func.to_tsvector(
                "simple", record.agent_search_text
            )
            self.session.add(record)
            await self.session.flush()
            disposition = SorProjectionDisposition.ADDED
        else:
            unchanged = (
                record.payload_hash == payload_hash
                and record.mapping_revision_id == mapping.id
                and record.mapping_projection_version == mapping.projection_version
                and record.tombstoned_at is None
            )
            disposition = (
                SorProjectionDisposition.UNCHANGED
                if unchanged
                else SorProjectionDisposition.UPDATED
            )
            record.source_created_at = external_record.source_created_at
            record.source_updated_at = external_record.source_updated_at
            record.source_revision = external_record.source_revision
            record.source_url = external_record.source_url
            record.projected_at = datetime.now(timezone.utc)
            if sync_run_id is not None:
                record.last_successful_sync_run_id = sync_run_id
            if not unchanged:
                record.canonical_entity_kind = canonical_entity_kind
                record.human_external_key = human_external_key
                record.selected_raw_payload = selected
                record.agent_visible_payload = agent_visible
                record.payload_hash = payload_hash
                record.mapping_revision_id = mapping.id
                record.mapping_projection_version = mapping.projection_version
                record.tombstoned_at = None
                record.deletion_reason = None
                record.search_text = search_text
                record.search_vector = func.to_tsvector("simple", record.search_text)
                record.agent_search_text = agent_search_text
                record.agent_search_vector = func.to_tsvector(
                    "simple", record.agent_search_text
                )

        if disposition is not SorProjectionDisposition.UNCHANGED:
            await self._replace_custom_values(
                organization_id=organization_id,
                source_id=source_id,
                record=record,
                mapped_fields=fields,
                values=custom,
            )
        await self.session.flush()
        keys = tuple(
            sorted(
                f"{field.vendor_object_key}.{field.vendor_field_key}"
                for field, _ in custom
            )
        )
        return SorProjectionOutcome(
            record_id=record.id,
            disposition=disposition,
            canonical_values=canonical,
            custom_field_keys=keys,
        )

    async def tombstone(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        vendor_object_key: str,
        vendor_external_id: str,
        deleted_at: datetime | None,
        reason: str,
        source_revision: str | None = None,
    ) -> SorRecordModel:
        """Mark one exact source identity deleted; callers own scan completeness."""
        record = await self.repository.get_record_by_identity(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=vendor_object_key,
            vendor_external_id=vendor_external_id,
            for_update=True,
        )
        if record is None:
            raise SorNotFoundError("SOR record not found.")
        normalized_reason = reason.strip()
        if not 1 <= len(normalized_reason) <= 256:
            raise SorProjectionError(
                "Deletion reason must contain 1 to 256 characters."
            )
        tombstoned_at = deleted_at or datetime.now(timezone.utc)
        record.tombstoned_at = tombstoned_at
        record.deletion_reason = normalized_reason
        record.source_revision = source_revision or record.source_revision
        record.projected_at = datetime.now(timezone.utc)
        await self.tombstone_relations_for_records(
            organization_id=organization_id,
            source_id=source_id,
            record_ids=(record.id,),
            relation_external_ids=(
                (record.vendor_external_id,)
                if record.canonical_entity_kind == "relation"
                else ()
            ),
            tombstoned_at=tombstoned_at,
        )
        await self.session.flush()
        return record

    async def tombstone_relations_for_records(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_ids: Sequence[UUID],
        relation_external_ids: Sequence[str],
        tombstoned_at: datetime,
    ) -> int:
        """Close active edges owned by deleted endpoints or relation records."""
        predicates = []
        if record_ids:
            predicates.append(SorRecordRelationModel.from_record_id.in_(record_ids))
            predicates.append(SorRecordRelationModel.to_record_id.in_(record_ids))
        if relation_external_ids:
            predicates.append(
                SorRecordRelationModel.external_relation_id.in_(
                    relation_external_ids
                )
            )
        if not predicates:
            return 0
        result = await self.session.execute(
            update(SorRecordRelationModel)
            .where(
                SorRecordRelationModel.organization_id == organization_id,
                SorRecordRelationModel.source_id == source_id,
                SorRecordRelationModel.tombstoned_at.is_(None),
                SorRecordRelationModel.deleted.is_(False),
                or_(*predicates),
            )
            .values(tombstoned_at=tombstoned_at, updated_at=tombstoned_at)
            .returning(SorRecordRelationModel.id)
        )
        return len(result.all())

    async def set_human_external_key(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        value: str | None,
    ) -> None:
        """Set a bounded profile-derived key after mapping-approved normalization."""
        record = await self.repository.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            for_update=True,
        )
        if record is None:
            raise SorNotFoundError("SOR record not found.")
        normalized = value.strip() if value is not None else None
        if normalized == "":
            normalized = None
        if normalized is not None and len(normalized) > 320:
            raise SorProjectionError("Human source key exceeds 320 characters.")
        record.human_external_key = normalized
        await self.session.flush()

    async def _replace_custom_values(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record: SorRecordModel,
        mapped_fields: Sequence[SorFieldMappingModel],
        values: Sequence[tuple[SorFieldMappingModel, object]],
    ) -> None:
        definition_ids = [
            field.custom_field_definition_id
            for field in mapped_fields
            if field.custom_field_definition_id is not None
        ]
        if definition_ids:
            await self.session.execute(
                delete(SorCustomFieldValueModel).where(
                    SorCustomFieldValueModel.organization_id == organization_id,
                    SorCustomFieldValueModel.source_id == source_id,
                    SorCustomFieldValueModel.record_id == record.id,
                    SorCustomFieldValueModel.field_definition_id.in_(definition_ids),
                )
            )
        definitions = {
            definition.id: definition
            for definition in await self.repository.list_custom_field_definitions(
                organization_id=organization_id,
                source_id=source_id,
                definition_ids=definition_ids,
            )
        }
        rows: list[SorCustomFieldValueModel] = []
        for field, value in values:
            definition_id = field.custom_field_definition_id
            if definition_id is None:
                raise SorProjectionError("Mapped custom field definition is missing.")
            definition = definitions.get(definition_id)
            if definition is None:
                raise SorProjectionError("Mapped custom field definition is missing.")
            rows.append(
                await self._custom_value_row(
                    organization_id=organization_id,
                    source_id=source_id,
                    record_id=record.id,
                    field=field,
                    definition=definition,
                    value=value,
                )
            )
        self.session.add_all(rows)

    async def _custom_value_row(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        field: SorFieldMappingModel,
        definition: SorCustomFieldDefinitionModel,
        value: object,
    ) -> SorCustomFieldValueModel:
        values: dict[str, object] = {}
        kind = definition.data_type
        if kind is SorCustomFieldType.TEXT:
            if not isinstance(value, str):
                raise SorProjectionError("Custom TEXT value must be a string.")
            values["text_value"] = value
        elif kind is SorCustomFieldType.DECIMAL:
            try:
                values["decimal_value"] = Decimal(str(value))
            except (InvalidOperation, ValueError) as error:
                raise SorProjectionError("Custom DECIMAL value is invalid.") from error
        elif kind is SorCustomFieldType.BOOLEAN:
            values["boolean_value"] = _boolean(value)
        elif kind is SorCustomFieldType.DATE:
            values["date_value"] = _date(value)
        elif kind is SorCustomFieldType.TIMESTAMP:
            values["timestamp_value"] = _timestamp(value)
        elif kind is SorCustomFieldType.STRING_ARRAY:
            values["string_array_value"] = _string_array(value)
        elif kind is SorCustomFieldType.REFERENCE:
            reference = await self._resolve_reference(
                organization_id=organization_id,
                source_id=source_id,
                field=field,
                value=value,
            )
            values["reference_record_id"] = reference.id
        elif kind is SorCustomFieldType.BOUNDED_JSON:
            _bounded_json(
                value,
                maximum=16_384,
                field_name="custom JSON value",
                expected_type=(dict, list),
            )
            values["json_value"] = value
        return SorCustomFieldValueModel(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            field_definition_id=definition.id,
            value_type=kind,
            **values,
        )

    async def _resolve_reference(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        field: SorFieldMappingModel,
        value: object,
    ) -> SorRecordModel:
        if not isinstance(value, str):
            raise SorProjectionError("Custom REFERENCE value must be an external ID.")
        object_key = field.transform_config.get("vendor_object_key")
        if not isinstance(object_key, str):
            raise SorProjectionError(
                "REFERENCE mappings require vendor_object_key transform config."
            )
        record = await self.repository.get_record_by_identity(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=object_key,
            vendor_external_id=value,
        )
        if record is None or record.tombstoned_at is not None:
            raise SorProjectionError("Custom reference target is unavailable.")
        return record


def _schema_snapshot(schema: SorDiscoveredSchema) -> dict[str, object]:
    if not schema.objects:
        raise SorConfigurationError("Discovered schema must contain an object.")
    objects: list[dict[str, object]] = []
    object_keys: set[str] = set()
    for object_ in sorted(schema.objects, key=lambda item: item.key):
        _require_key(object_.key, field_name="schema object")
        if object_.key in object_keys or not object_.fields:
            raise SorConfigurationError(
                "Discovered objects must be unique and contain fields."
            )
        object_keys.add(object_.key)
        field_keys: set[str] = set()
        fields: list[dict[str, object]] = []
        for field in sorted(object_.fields, key=lambda item: item.key):
            _require_key(field.key, field_name="schema field")
            if field.key in field_keys:
                raise SorConfigurationError("Discovered field keys must be unique.")
            field_keys.add(field.key)
            fields.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "data_type": field.data_type,
                    "nullable": field.nullable,
                    "writable": field.writable,
                    "choices": list(field.choices),
                    "description": field.description,
                    "group": field.group,
                    "vendor_type": field.vendor_type,
                }
            )
        objects.append(
            {
                "key": object_.key,
                "label": object_.label,
                "custom": object_.custom,
                "fields": fields,
            }
        )
    snapshot: dict[str, object] = {
        "objects": objects,
        "vendor_api_version": schema.vendor_api_version,
    }
    _bounded_json(
        snapshot,
        maximum=2_097_152,
        field_name="discovered schema",
        expected_type=dict,
    )
    return snapshot


def _schema_difference(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> SorSchemaDifference:
    if previous is None:
        return SorSchemaDifference(added=tuple(sorted(_flat_schema(current))))
    old = _flat_schema(previous)
    new = _flat_schema(current)
    old_keys = set(old)
    new_keys = set(new)
    common = old_keys & new_keys
    return SorSchemaDifference(
        added=tuple(sorted(new_keys - old_keys)),
        removed=tuple(sorted(old_keys - new_keys)),
        renamed=tuple(sorted(key for key in common if old[key][0] != new[key][0])),
        type_changed=tuple(sorted(key for key in common if old[key][1] != new[key][1])),
    )


def _flat_schema(snapshot: Mapping[str, object]) -> dict[str, tuple[str, str]]:
    flattened: dict[str, tuple[str, str]] = {}
    for object_ in _snapshot_object_rows(snapshot):
        for field in _snapshot_field_rows(object_):
            flattened[f"{object_['key']}.{field['key']}"] = (
                str(field["label"]),
                str(field["data_type"]),
            )
    return flattened


def _snapshot_fields(
    snapshot: Mapping[str, object],
) -> dict[tuple[str, str], SorDiscoveredField]:
    fields: dict[tuple[str, str], SorDiscoveredField] = {}
    for raw_object in _snapshot_object_rows(snapshot):
        object_key = raw_object.get("key")
        if not isinstance(object_key, str):
            continue
        for raw_field in _snapshot_field_rows(raw_object):
            field_key = raw_field.get("key")
            if not isinstance(field_key, str):
                continue
            choices = raw_field.get("choices")
            field = SorDiscoveredField(
                key=field_key,
                label=str(raw_field.get("label") or field_key),
                data_type=str(raw_field.get("data_type") or "unknown"),
                nullable=bool(raw_field.get("nullable")),
                writable=bool(raw_field.get("writable")),
                choices=(
                    tuple(str(item) for item in choices)
                    if isinstance(choices, list)
                    else ()
                ),
                description=(
                    str(raw_field["description"])
                    if raw_field.get("description") is not None
                    else None
                ),
                group=(
                    str(raw_field["group"])
                    if raw_field.get("group") is not None
                    else None
                ),
                vendor_type=(
                    str(raw_field["vendor_type"])
                    if raw_field.get("vendor_type") is not None
                    else None
                ),
            )
            fields[(object_key, field.key)] = field
    return fields


def snapshot_objects(
    snapshot: Mapping[str, object],
) -> dict[str, tuple[str, bool]]:
    objects: dict[str, tuple[str, bool]] = {}
    for raw_object in _snapshot_object_rows(snapshot):
        key = raw_object.get("key")
        if not isinstance(key, str):
            continue
        objects[key] = (
            str(raw_object.get("label") or key),
            raw_object.get("custom") is True,
        )
    return objects


def _snapshot_object_rows(
    snapshot: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    value = snapshot.get("objects")
    if not isinstance(value, list):
        return ()
    return tuple(row for row in value if isinstance(row, dict))


def _snapshot_field_rows(
    object_: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    value = object_.get("fields")
    if not isinstance(value, list):
        return ()
    return tuple(row for row in value if isinstance(row, dict))


def _validate_custom_dataset_mapping(draft: SorFieldMappingDraft) -> None:
    """Keep custom-object datasets audit-only and outside Agent payloads."""
    if draft.direction is SorFieldMappingDirection.IGNORE:
        return
    if draft.direction is not SorFieldMappingDirection.READ_ONLY:
        raise SorConfigurationError("Custom-object fields are read-only in v1.")
    if draft.canonical_target_path is not None or draft.custom_type is None:
        raise SorConfigurationError(
            "Custom-object fields must use typed custom targets."
        )
    if draft.agent_visible:
        raise SorConfigurationError(
            "Custom-object fields are not available to Agents in v1."
        )


def _transform(
    kind: SorTransformKind,
    value: object,
    config: Mapping[str, object],
) -> object:
    if kind is SorTransformKind.DIRECT:
        return value
    if kind is SorTransformKind.BOOLEAN:
        return _boolean(value)
    if kind is SorTransformKind.DATE:
        return _date(value)
    if kind is SorTransformKind.TIMESTAMP:
        return _timestamp(value)
    if kind is SorTransformKind.ARRAY:
        return _string_array(value)
    if kind is SorTransformKind.RICH_TEXT_TO_PLAIN_TEXT:
        return _plain_text(value)
    if kind is SorTransformKind.ENUM:
        if not isinstance(value, str):
            raise SorProjectionError("ENUM transform requires a string value.")
        mapping = config.get("mapping", {})
        if not isinstance(mapping, dict):
            raise SorProjectionError("ENUM transform mapping is invalid.")
        mapped = mapping.get(value)
        if mapped is None and not config.get("allow_unmapped", False):
            raise SorProjectionError(f"ENUM transform has no value for {value!r}.")
        return value if mapped is None else mapped
    if kind is SorTransformKind.MONEY:
        if not isinstance(value, dict) or "amount" not in value:
            raise SorProjectionError("MONEY transform requires amount and currency.")
        try:
            amount = Decimal(str(value["amount"]))
        except (InvalidOperation, ValueError) as error:
            raise SorProjectionError("MONEY amount is invalid.") from error
        currency = value.get("currency") or config.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise SorProjectionError("MONEY currency must be an ISO 4217 code.")
        return {"amount": str(amount), "currency": currency}
    if kind is SorTransformKind.IDENTITY_REFERENCE:
        if not isinstance(value, str) or not value:
            raise SorProjectionError("IDENTITY_REFERENCE requires a string ID.")
        return value
    raise SorProjectionError(f"Unsupported transform: {kind.value}.")


def _mapped_value_is_absent(field: SorFieldMappingModel, value: object) -> bool:
    if value is None:
        return True
    return (
        value == ""
        and field.nullable
        and field.source_data_type.casefold() in _EMPTY_AS_NULL_SOURCE_TYPES
    )


def _validate_transform(
    kind: SorTransformKind,
    config: Mapping[str, object],
) -> None:
    _bounded_json(
        dict(config),
        maximum=16_384,
        field_name="transform configuration",
        expected_type=dict,
    )
    allowed_keys = {
        SorTransformKind.DIRECT: set(),
        SorTransformKind.BOOLEAN: set(),
        SorTransformKind.DATE: set(),
        SorTransformKind.TIMESTAMP: set(),
        SorTransformKind.MONEY: {"currency"},
        SorTransformKind.RICH_TEXT_TO_PLAIN_TEXT: set(),
        SorTransformKind.ENUM: {"mapping", "allow_unmapped"},
        SorTransformKind.IDENTITY_REFERENCE: {"vendor_object_key"},
        SorTransformKind.ARRAY: set(),
    }[kind]
    unknown = set(config) - allowed_keys
    if unknown:
        raise SorConfigurationError(
            f"Transform {kind.value} has unsupported config keys: {sorted(unknown)}."
        )


def _plain_text(value: object) -> str:
    parts: list[str] = []

    def visit(item: object, depth: int) -> None:
        if depth > 8:
            raise SorProjectionError("Rich text nesting exceeds eight levels.")
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
            for key in ("plain_text", "text", "content", "children"):
                if key in item:
                    visit(item[key], depth + 1)
                    break

    visit(value, 1)
    result = " ".join(part.strip() for part in parts if part.strip())
    if len(result) > 1_000_000:
        raise SorProjectionError("Normalized rich text exceeds one million characters.")
    return result


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise SorProjectionError("BOOLEAN value must be boolean or 'true'/'false'.")


def _string_array(value: object) -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(";") if item.strip()]
    elif isinstance(value, (list, tuple)) and all(
        isinstance(item, str) for item in value
    ):
        items = list(value)
    else:
        raise SorProjectionError(
            "ARRAY value must be a string list or semicolon-delimited string."
        )
    if len(items) > 128 or any(len(item) > 512 for item in items):
        raise SorProjectionError("ARRAY value is too large.")
    return items


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return _millisecond_datetime(value, field_name="DATE").date()
    if isinstance(value, str):
        if re.fullmatch(r"-?\d+", value):
            return _millisecond_datetime(int(value), field_name="DATE").date()
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise SorProjectionError("DATE value must use ISO format.") from error
    raise SorProjectionError("DATE value is invalid.")


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int) and not isinstance(value, bool):
        parsed = _millisecond_datetime(value, field_name="TIMESTAMP")
    elif isinstance(value, str):
        if re.fullmatch(r"-?\d+", value):
            return _millisecond_datetime(int(value), field_name="TIMESTAMP")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise SorProjectionError("TIMESTAMP value must use ISO format.") from error
    else:
        raise SorProjectionError("TIMESTAMP value is invalid.")
    if parsed.tzinfo is None:
        raise SorProjectionError("TIMESTAMP value must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _millisecond_datetime(value: int, *, field_name: str) -> datetime:
    try:
        return datetime.fromtimestamp(value / 1_000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError) as error:
        raise SorProjectionError(
            f"{field_name} millisecond timestamp is out of range."
        ) from error


def _projection_search_text(
    canonical: Mapping[str, object],
    custom: Sequence[tuple[SorFieldMappingModel, object]],
) -> str:
    values = dict(canonical)
    values.update(
        {
            f"custom.{field.vendor_field_key}": value
            for field, value in custom
            if field.agent_visible or field.ui_default_column
        }
    )
    return _search_text(values)


def _search_text(values: Mapping[str, object]) -> str:
    parts = [
        str(value)
        for _, value in sorted(values.items())
        if isinstance(value, (str, int, float, Decimal)) and not isinstance(value, bool)
    ]
    return " ".join(parts)[:1_000_000]


def _custom_field_key(definition_id: UUID) -> str:
    return f"custom.{definition_id}"


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise SorProjectionError("Source datetimes must include a timezone.")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise SorProjectionError("Source payload contains a non-JSON value.")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SorConfigurationError("SOR data must be JSON serializable.") from error


def _bounded_json(
    value: object,
    *,
    maximum: int,
    field_name: str,
    expected_type: type | tuple[type, ...],
) -> None:
    if not isinstance(value, expected_type):
        raise SorConfigurationError(f"{field_name.capitalize()} has an invalid shape.")
    if len(_canonical_json(value)) > maximum:
        raise SorConfigurationError(f"{field_name.capitalize()} is too large.")


def _require_matching_source_attempt(
    *,
    existing: SorSourceModel,
    draft: _SourceDraft,
) -> None:
    """Reject an idempotency key reused for a different source definition."""
    matches = (
        existing.name == draft.name
        and existing.profile is draft.profile
        and existing.vendor_key == draft.vendor_key
        and existing.configuration == draft.configuration
        and tuple(existing.selected_objects or ()) == draft.selected_objects
        and existing.freshness_target_seconds == draft.freshness_target_seconds
        and existing.required_sync_interval_seconds
        == draft.required_sync_interval_seconds
    )
    if not matches:
        raise SorConflictError(
            "This onboarding attempt was already used for another source definition."
        )


def _normalize_source_configuration(
    configuration: Mapping[str, object] | None,
    *,
    manifest: SorAdapterCapabilityManifest,
) -> dict[str, object]:
    """Validate code-owned non-secret settings before a source is persisted."""
    normalized = dict(configuration or {})
    _bounded_json(
        normalized,
        maximum=65_536,
        field_name="source configuration",
        expected_type=dict,
    )
    fields = {field.key: field for field in manifest.configuration_fields}
    unknown = set(normalized) - set(fields)
    if unknown:
        raise SorConfigurationError(
            "Source configuration contains unsupported fields: "
            + ", ".join(sorted(unknown))
            + "."
        )
    for key, field in fields.items():
        value = normalized.get(key)
        if value is None:
            if field.required:
                raise SorConfigurationError(
                    f"Source configuration requires {field.label}."
                )
            continue
        if field.kind is not SorConfigurationFieldKind.STRING_LIST:
            raise SorConfigurationError(
                f"Source configuration field {field.label} is unsupported."
            )
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SorConfigurationError(
                f"Source configuration field {field.label} must be a list."
            )
        items: list[str] = []
        for raw_item in value:
            if not isinstance(raw_item, str):
                raise SorConfigurationError(
                    f"Source configuration field {field.label} must contain text."
                )
            item = raw_item.strip()
            if not 1 <= len(item) <= 256:
                raise SorConfigurationError(
                    f"Source configuration field {field.label} has an invalid item."
                )
            if item not in items:
                items.append(item)
        if not field.minimum_items <= len(items) <= field.maximum_items:
            raise SorConfigurationError(
                f"Source configuration field {field.label} requires "
                f"{field.minimum_items} to {field.maximum_items} items."
            )
        normalized[key] = items
    return normalized


def _validate_source_connection(
    *,
    connection: ExternalConnectionModel,
    manifest: SorAdapterCapabilityManifest,
    required_scopes: set[str],
    unavailable_message: str = "External connection must be active.",
) -> None:
    """Enforce the shared connection authority required by every source flow."""
    if connection.owner_kind is not ConnectionOwnerKind.ORGANIZATION:
        raise SorConfigurationError(
            "SOR V1 accepts organization-owned connections only."
        )
    if connection.status is not ExternalConnectionStatus.ACTIVE:
        raise SorConfigurationError(unavailable_message)
    if connection.auth_kind not in manifest.auth_kinds:
        raise SorConfigurationError(
            "External connection authentication is unsupported by this adapter."
        )
    if manifest.requires_instance_origin and not connection.instance_origin:
        raise SorConfigurationError("This source requires a verified instance origin.")
    if (
        manifest.fixed_origin
        and not manifest.requires_instance_origin
        and connection.instance_origin not in {None, manifest.fixed_origin}
    ):
        raise SorConfigurationError(
            "Connection origin does not match the adapter's pinned origin."
        )
    missing_scopes = required_scopes - set(connection.granted_scopes or ())
    if missing_scopes:
        raise SorConfigurationError(
            "Connection requires reauthorization for scopes: "
            + ", ".join(sorted(missing_scopes))
            + "."
        )


def _unique_keys(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    for value in normalized:
        _require_key(value, field_name=field_name)
    if len(normalized) != len(set(normalized)):
        raise SorConfigurationError(f"{field_name.capitalize()} values must be unique.")
    return normalized


def _require_key(value: str, *, field_name: str) -> None:
    if not _FIELD_KEY.fullmatch(value):
        raise SorConfigurationError(
            f"{field_name.capitalize()} must be a stable source identifier."
        )


def _safe_error_code(value: str | None) -> str:
    normalized = (value or "SOR_OPERATION_FAILED").strip().upper()
    if not _SAFE_ERROR.fullmatch(normalized):
        return "SOR_OPERATION_FAILED"
    return normalized


def _safe_error_summary(value: str | None) -> str:
    normalized = (value or "SOR operation failed.").strip()
    return normalized[:8_192]


__all__ = [
    "SorConfigurationError",
    "SorConflictError",
    "SorError",
    "SorMappingService",
    "SorNotFoundError",
    "SorProjectionError",
    "SorProjectionService",
    "SorSchemaService",
    "SorSourceService",
    "snapshot_objects",
]
