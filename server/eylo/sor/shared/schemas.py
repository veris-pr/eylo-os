"""Public configuration and catalog schemas for Systems of Record."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from eylo.modules.connections.domain import (
    ConnectionAuthKind,
    ExternalConnectionStatus,
)
from eylo.sor.shared.contracts import (
    SorChangeStrategy,
    SorConfigurationFieldKind,
    SorConnectionVerification,
    SorCustomFieldType,
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorImplementationStatus,
    SorMappingState,
    SorProfile,
    SorSchemaDifference,
    SorSensitivity,
    SorSourceAccess,
    SorSourceState,
    SorStreamState,
    SorSyncRunKind,
    SorToolEffect,
    SorTransformKind,
    SorWorkState,
)
from eylo.sor.shared.query import SorCollectionQuery, SorGridContract

if TYPE_CHECKING:
    from eylo.sor.shared.models import SorSchemaRevisionModel


class SorApiModel(BaseModel):
    """Strict public SOR contract with ORM projection support."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class SorSourceCreateRequest(SorApiModel):
    name: str = Field(min_length=1, max_length=160)
    profile: SorProfile
    vendor_key: str = Field(min_length=1, max_length=64)
    external_connection_id: UUID
    configuration: dict[str, object] = Field(default_factory=dict)
    selected_objects: tuple[str, ...] = Field(min_length=1)
    freshness_target_seconds: int = Field(default=900, gt=0)
    required_sync_interval_seconds: int = Field(default=900, gt=0)


class SorApiKeySourceCreateRequest(SorApiModel):
    """Create one source whose org connection uses a transient API key."""

    name: str = Field(min_length=1, max_length=160)
    profile: SorProfile
    vendor_key: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=4096, repr=False)
    instance_origin: str | None = Field(default=None, min_length=1, max_length=512)
    configuration: dict[str, object] = Field(default_factory=dict)
    selected_objects: tuple[str, ...] = Field(min_length=1)
    freshness_target_seconds: int = Field(default=900, gt=0)
    required_sync_interval_seconds: int = Field(default=900, gt=0)


class SorSourceSelectionUpdateRequest(SorApiModel):
    """Select only objects proven by the active discovery revision."""

    selected_objects: tuple[str, ...] = Field(min_length=1, max_length=100)
    expected_config_revision: int = Field(gt=0)


class SorWebhookSigningSecretUpdateRequest(SorApiModel):
    """Rotate one source-owned vendor signing secret without returning it."""

    signing_secret: str = Field(min_length=1, max_length=4096)
    expected_config_revision: int = Field(gt=0)


class SorConnectorCreateRequest(SorApiModel):
    """Configure one organization-owned OAuth application for a SOR vendor."""

    name: str = Field(min_length=1, max_length=160)
    profile: SorProfile
    vendor_key: str = Field(min_length=1, max_length=64)
    auth_kind: ConnectionAuthKind
    oauth_client_id: str = Field(min_length=1, max_length=512)
    oauth_client_secret: str = Field(min_length=1, max_length=4096)


class SorConnectorConnectionResponse(SorApiModel):
    id: UUID
    status: ExternalConnectionStatus
    instance_origin: str | None
    granted_scopes: tuple[str, ...]
    credentials_expires_at: datetime | None
    revision: int


class SorConnectorResponse(SorApiModel):
    id: UUID
    organization_id: UUID
    name: str
    profile: SorProfile
    vendor_key: str
    auth_kind: ConnectionAuthKind
    oauth_client_id: str
    oauth_callback_url: str
    has_oauth_client_secret: bool
    config_revision: int
    configured_by: UUID
    connection: SorConnectorConnectionResponse | None
    created_at: datetime
    updated_at: datetime


class SorConnectorListResponse(SorApiModel):
    items: tuple[SorConnectorResponse, ...]


class SorConnectorAuthorizationRequest(SorApiModel):
    selected_objects: tuple[str, ...] = Field(min_length=1)
    access: SorSourceAccess
    instance_origin: str | None = Field(default=None, min_length=1, max_length=512)


class SorAuthorizationRedirectResponse(SorApiModel):
    authorization_url: str
    callback_url: str
    callback_origin: str


class SorOAuthConfigurationResponse(SorApiModel):
    """Public operator input required before creating a vendor OAuth app."""

    callback_url: str


class SorSourceResponse(SorApiModel):
    id: UUID
    organization_id: UUID
    name: str
    profile: SorProfile
    vendor_key: str
    external_connection_id: UUID
    configuration: dict[str, object]
    selected_objects: list[str]
    config_revision: int
    state: SorSourceState
    active_schema_revision_id: UUID | None
    active_mapping_revision_id: UUID | None
    has_webhook_signing_secret: bool
    webhook_signing_secret_revision: int
    freshness_target_seconds: int
    required_sync_interval_seconds: int
    last_verified_at: datetime | None
    last_successful_sync_at: datetime | None
    last_reconciliation_at: datetime | None
    last_error_code: str | None
    last_error_summary: str | None
    created_at: datetime
    updated_at: datetime


class SorSourceListResponse(SorApiModel):
    items: tuple[SorSourceResponse, ...]


class SorCustomDatasetResponse(SorApiModel):
    """One audit-only custom object and its source identity."""

    id: UUID
    source_id: UUID
    source_name: str
    profile: SorProfile
    vendor_key: str
    vendor_object_key: str
    label: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class SorCustomDatasetListResponse(SorApiModel):
    items: tuple[SorCustomDatasetResponse, ...]


class SorSourceGrantRequest(SorApiModel):
    """Create or replace one Agent draft's source authority."""

    access: SorSourceAccess
    expected_draft_version: int = Field(gt=0)


class SorSourceGrantResponse(SorApiModel):
    """One live grant plus safe source identity for configuration UI."""

    id: UUID
    organization_id: UUID
    agent_id: UUID
    source_id: UUID
    source_name: str
    profile: SorProfile
    vendor_key: str
    access: SorSourceAccess
    revision: int
    granted_by: UUID | None
    created_at: datetime
    updated_at: datetime


class SorSourceGrantListResponse(SorApiModel):
    items: tuple[SorSourceGrantResponse, ...]


class SorWebhookEndpointResponse(SorApiModel):
    endpoint_path: str
    endpoint_token: str


class SorStreamCreateRequest(SorApiModel):
    vendor_object_key: str = Field(min_length=1, max_length=160)
    canonical_entity_kind: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    strategy: SorChangeStrategy
    lookback_seconds: int = Field(default=0, ge=0)
    schedule: str | None = Field(default=None, min_length=1, max_length=128)


class SorStreamResponse(SorApiModel):
    id: UUID
    organization_id: UUID
    source_id: UUID
    vendor_object_key: str
    canonical_entity_kind: str
    strategy: SorChangeStrategy
    lookback_seconds: int
    cursor_version: int
    schedule: str | None
    next_due_at: datetime | None
    state: SorStreamState
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_code: str | None
    records_added: int
    records_updated: int
    records_tombstoned: int
    records_unchanged: int
    records_rejected: int
    created_at: datetime
    updated_at: datetime


class SorSyncRunCreateRequest(SorApiModel):
    kind: SorSyncRunKind
    max_attempts: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def validate_stream_kind(self) -> "SorSyncRunCreateRequest":
        if self.kind not in {
            SorSyncRunKind.BOOTSTRAP,
            SorSyncRunKind.INCREMENTAL,
            SorSyncRunKind.RECONCILIATION,
        }:
            raise ValueError("Only stream-based sync run kinds are accepted here.")
        return self


class SorSyncRunResponse(SorApiModel):
    id: UUID
    organization_id: UUID
    source_id: UUID
    stream_id: UUID | None
    mapping_revision_id: UUID
    kind: SorSyncRunKind
    state: SorWorkState
    absurd_task_id: UUID | None
    attempts: int
    max_attempts: int
    scan_complete: bool
    started_at: datetime | None
    finished_at: datetime | None
    safe_error_code: str | None
    safe_error_summary: str | None
    records_added: int
    records_updated: int
    records_tombstoned: int
    records_unchanged: int
    records_rejected: int
    created_at: datetime
    updated_at: datetime


class SorFreshnessResponse(SorApiModel):
    as_of: datetime
    target_seconds: int
    stale: bool


class SorCustomFieldValueResponse(SorApiModel):
    key: str
    label: str
    data_type: SorCustomFieldType
    value: JsonValue
    sensitivity: SorSensitivity
    agent_visible: bool
    writable: bool


class SorCollectionRowResponse(SorApiModel):
    id: UUID
    source_id: UUID
    source_name: str
    vendor_key: str
    profile: SorProfile
    entity: str
    human_external_key: str | None
    values: dict[str, JsonValue]
    custom_fields: tuple[SorCustomFieldValueResponse, ...]
    source_url: str | None
    source_created_at: datetime | None
    source_updated_at: datetime | None
    projected_at: datetime
    freshness: SorFreshnessResponse


class SorCollectionPageResponse(SorApiModel):
    query: SorCollectionQuery
    grid: SorGridContract
    items: tuple[SorCollectionRowResponse, ...]
    next_cursor: str | None
    has_more: bool


class SorRecordRelationResponse(SorApiModel):
    kind: str
    native_kind: str
    direction: str
    record_id: UUID
    record_entity: str
    record_key: str | None
    source_url: str | None


class SorRecordDetailResponse(SorApiModel):
    record: SorCollectionRowResponse
    selected_source_payload: dict[str, JsonValue]
    source_revision: str | None
    mapping_revision_id: UUID
    mapping_projection_version: int
    relations: tuple[SorRecordRelationResponse, ...]


class SorAgentVisibleFieldResponse(SorApiModel):
    """One source field the exact published Agent revision may perceive."""

    source_id: UUID
    key: str
    label: str
    data_type: str
    custom: bool
    writable: bool
    sensitivity: SorSensitivity


class SorAgentRecordResponse(SorApiModel):
    """Agent-safe record projection with provenance and no hidden source payload."""

    id: UUID
    source_id: UUID
    source_name: str
    vendor_key: str
    profile: SorProfile
    entity: str
    human_external_key: str | None
    values: dict[str, JsonValue]
    source_url: str | None
    source_updated_at: datetime | None
    source_revision: str | None
    mapping_revision_id: UUID
    projected_at: datetime
    freshness: SorFreshnessResponse
    relations: tuple[SorRecordRelationResponse, ...] = ()


class SorAgentRelatedAvailability(str, Enum):
    """Why a tool's declared related entity is or is not available."""

    AVAILABLE = "AVAILABLE"
    NOT_SELECTED = "NOT_SELECTED"
    NOT_MAPPED = "NOT_MAPPED"


class SorAgentRelatedCollectionResponse(SorApiModel):
    """Bounded related records tied to one exact primary Agent-visible record."""

    parent_record_id: UUID
    entity: str
    availability: SorAgentRelatedAvailability
    fields: tuple[SorAgentVisibleFieldResponse, ...]
    items: tuple[SorAgentRecordResponse, ...]
    truncated: bool


class SorAgentViewResponse(SorApiModel):
    """What one exact Agent revision can perceive for one canonical entity."""

    agent_id: UUID
    agent_revision: int
    profile: SorProfile
    entity: str
    authorized_tools: tuple[str, ...]
    fields: tuple[SorAgentVisibleFieldResponse, ...]
    items: tuple[SorAgentRecordResponse, ...]
    related: tuple[SorAgentRelatedCollectionResponse, ...] = ()
    next_cursor: str | None
    has_more: bool


class SorDiscoveredFieldResponse(SorApiModel):
    key: str
    label: str
    data_type: str
    nullable: bool
    writable: bool
    choices: tuple[str, ...] = ()
    description: str | None = None
    group: str | None = None


class SorDiscoveredObjectResponse(SorApiModel):
    key: str
    label: str
    custom: bool = False
    fields: tuple[SorDiscoveredFieldResponse, ...] = Field(min_length=1)


class SorSchemaRevisionResponse(SorApiModel):
    id: UUID
    source_id: UUID
    revision: int
    schema_hash: str
    objects: tuple[SorDiscoveredObjectResponse, ...] = Field(min_length=1)
    vendor_api_version: str | None
    discovered_at: datetime

    @classmethod
    def from_model(
        cls,
        row: "SorSchemaRevisionModel",
    ) -> "SorSchemaRevisionResponse":
        return cls(
            id=row.id,
            source_id=row.source_id,
            revision=row.revision,
            schema_hash=row.schema_hash,
            objects=tuple(
                SorDiscoveredObjectResponse.model_validate(item)
                for item in row.schema_snapshot.get("objects", [])
            ),
            vendor_api_version=row.vendor_api_version,
            discovered_at=row.discovered_at,
        )


class SorSchemaDifferenceResponse(SorApiModel):
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    type_changed: tuple[str, ...] = ()

    @classmethod
    def from_domain(
        cls,
        difference: SorSchemaDifference,
    ) -> "SorSchemaDifferenceResponse":
        return cls(
            added=difference.added,
            removed=difference.removed,
            renamed=difference.renamed,
            type_changed=difference.type_changed,
        )


class SorConnectionVerificationResponse(SorApiModel):
    account_external_id: str | None
    account_display_name: str | None
    granted_scopes: tuple[str, ...]
    vendor_api_version: str | None

    @classmethod
    def from_domain(
        cls,
        verification: SorConnectionVerification,
    ) -> "SorConnectionVerificationResponse":
        return cls(
            account_external_id=verification.account_external_id,
            account_display_name=verification.account_display_name,
            granted_scopes=verification.granted_scopes,
            vendor_api_version=verification.vendor_api_version,
        )


class SorDiscoveryResponse(SorApiModel):
    verification: SorConnectionVerificationResponse
    schema_revision: SorSchemaRevisionResponse
    difference: SorSchemaDifferenceResponse


class SorFieldMappingDraftRequest(SorApiModel):
    vendor_object_key: str = Field(min_length=1, max_length=160)
    vendor_field_key: str = Field(min_length=1, max_length=256)
    canonical_target_path: str | None = Field(default=None, max_length=320)
    custom_type: SorCustomFieldType | None = None
    transform_kind: SorTransformKind = SorTransformKind.DIRECT
    transform_config: dict[str, object] = Field(default_factory=dict)
    direction: SorFieldMappingDirection = SorFieldMappingDirection.READ_ONLY
    agent_visible: bool = False
    ui_default_column: bool = False
    sensitivity: SorSensitivity = SorSensitivity.STANDARD


class SorMappingDraftRequest(SorApiModel):
    fields: tuple[SorFieldMappingDraftRequest, ...] = Field(min_length=1)
    projection_version: int = Field(default=1, gt=0)


class SorFieldMappingResponse(SorApiModel):
    id: UUID
    vendor_object_key: str
    vendor_field_key: str
    source_label: str
    source_data_type: str
    canonical_target_path: str | None
    custom_field_definition_id: UUID | None
    transform_kind: SorTransformKind
    transform_config: dict[str, object]
    direction: SorFieldMappingDirection
    agent_visible: bool
    ui_default_column: bool
    nullable: bool
    enum_choices: list[str]
    sensitivity: SorSensitivity
    writable_capability: bool
    state: SorFieldMappingState
    incompatibility_reason: str | None


class SorMappingRevisionResponse(SorApiModel):
    id: UUID
    source_id: UUID
    revision: int
    source_schema_revision_id: UUID
    state: SorMappingState
    projection_version: int
    created_by: UUID | None
    published_by: UUID | None
    published_at: datetime | None
    created_at: datetime
    fields: tuple[SorFieldMappingResponse, ...]


class SorSourceActivationRequest(SorApiModel):
    mapping: SorMappingDraftRequest
    streams: tuple[SorStreamCreateRequest, ...] = Field(min_length=1)


class SorSourceActivationResponse(SorApiModel):
    source: SorSourceResponse
    mapping: SorMappingRevisionResponse
    streams: tuple[SorStreamResponse, ...] = Field(min_length=1)
    runs: tuple[SorSyncRunResponse, ...] = Field(min_length=1)


class SorCanonicalFieldCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    description: str
    data_type: str
    writable: bool
    required: bool


class SorEntityCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    description: str
    fields: tuple[SorCanonicalFieldCatalogResponse, ...] = ()


class SorToolCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    effect: SorToolEffect
    description: str
    target_entities: tuple[str, ...] = Field(min_length=1)
    entities: tuple[str, ...] = Field(min_length=1)


class SorVendorStreamResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    description: str
    canonical_entity: str
    change_strategies: tuple[SorChangeStrategy, ...] = Field(min_length=1)


class SorAdapterConfigurationFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    description: str
    kind: SorConfigurationFieldKind
    required: bool
    placeholder: str | None
    minimum_items: int
    maximum_items: int


class SorInstanceOriginOptionResponse(BaseModel):
    """One operator-selectable provider data region."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str
    label: str


class SorAdapterCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    auth_kinds: tuple[ConnectionAuthKind, ...] = Field(min_length=1)
    streams: tuple[SorVendorStreamResponse, ...] = Field(min_length=1)
    readable_entities: tuple[str, ...] = Field(min_length=1)
    writable_entities: tuple[str, ...] = ()
    readable_tools: tuple[str, ...] = Field(min_length=1)
    writable_tools: tuple[str, ...] = ()
    change_strategies: tuple[SorChangeStrategy, ...] = Field(min_length=1)
    configuration_fields: tuple[SorAdapterConfigurationFieldResponse, ...] = ()
    required_scopes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    custom_object_required_scopes: tuple[str, ...] = ()
    custom_object_change_strategies: tuple[SorChangeStrategy, ...] = ()
    tool_required_scopes: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    fixed_origin: str | None = None
    requires_instance_origin: bool = False
    requires_instance_origin_input: bool = False
    instance_origin_options: tuple[SorInstanceOriginOptionResponse, ...] = ()
    supports_webhooks: bool = False
    supports_deletions: bool = False
    supports_custom_fields: bool = False
    supports_custom_objects: bool = False
    supports_conditional_writes: bool = False
    supports_history: bool = False
    supports_comments: bool = False
    supports_attachments: bool = False
    supports_structured_documents: bool = False


class SorVendorCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    vendor_key: str
    display_name: str
    description: str
    status: SorImplementationStatus
    planned_auth_kinds: tuple[ConnectionAuthKind, ...] = Field(min_length=1)
    requires_instance_origin: bool = False
    setup_notes: tuple[str, ...] = ()
    capabilities: SorAdapterCapabilityResponse | None = None

    @model_validator(mode="after")
    def validate_support_claim(self) -> "SorVendorCatalogResponse":
        available = self.status is SorImplementationStatus.AVAILABLE
        if available != (self.capabilities is not None):
            raise ValueError(
                "Available SOR vendors require executable capabilities; planned "
                "vendors must not publish them."
            )
        return self


class SorProfileCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: SorProfile
    label: str
    description: str
    entities: tuple[SorEntityCatalogResponse, ...] = Field(min_length=1)
    tools: tuple[SorToolCatalogResponse, ...] = Field(min_length=1)
    vendors: tuple[SorVendorCatalogResponse, ...] = Field(min_length=1)


class SorCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profiles: tuple[SorProfileCatalogResponse, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profiles(self) -> "SorCatalogResponse":
        profiles = [item.profile for item in self.profiles]
        if len(profiles) != len(set(profiles)) or set(profiles) != set(SorProfile):
            raise ValueError("The SOR catalog must publish every profile exactly once.")
        return self


__all__ = [
    "SorAgentRecordResponse",
    "SorAgentRelatedAvailability",
    "SorAgentRelatedCollectionResponse",
    "SorAgentViewResponse",
    "SorAgentVisibleFieldResponse",
    "SorAdapterCapabilityResponse",
    "SorAdapterConfigurationFieldResponse",
    "SorAuthorizationRedirectResponse",
    "SorCatalogResponse",
    "SorCanonicalFieldCatalogResponse",
    "SorConnectorAuthorizationRequest",
    "SorConnectorConnectionResponse",
    "SorConnectorCreateRequest",
    "SorConnectorListResponse",
    "SorConnectorResponse",
    "SorCollectionPageResponse",
    "SorCollectionRowResponse",
    "SorConnectionVerificationResponse",
    "SorCustomDatasetListResponse",
    "SorCustomDatasetResponse",
    "SorCustomFieldValueResponse",
    "SorDiscoveredFieldResponse",
    "SorDiscoveredObjectResponse",
    "SorDiscoveryResponse",
    "SorEntityCatalogResponse",
    "SorFieldMappingDraftRequest",
    "SorFieldMappingResponse",
    "SorFreshnessResponse",
    "SorMappingDraftRequest",
    "SorMappingRevisionResponse",
    "SorProfileCatalogResponse",
    "SorRecordDetailResponse",
    "SorRecordRelationResponse",
    "SorSchemaDifferenceResponse",
    "SorSchemaRevisionResponse",
    "SorSourceCreateRequest",
    "SorSourceActivationRequest",
    "SorSourceActivationResponse",
    "SorSourceGrantListResponse",
    "SorSourceGrantRequest",
    "SorSourceGrantResponse",
    "SorSourceListResponse",
    "SorSourceResponse",
    "SorSourceSelectionUpdateRequest",
    "SorStreamCreateRequest",
    "SorStreamResponse",
    "SorSyncRunCreateRequest",
    "SorSyncRunResponse",
    "SorToolCatalogResponse",
    "SorVendorStreamResponse",
    "SorVendorCatalogResponse",
    "SorWebhookEndpointResponse",
]
