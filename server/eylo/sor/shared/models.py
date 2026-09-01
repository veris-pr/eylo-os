"""Tenant-bound persistence for SOR configuration, projection, and durable work."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from eylo.common.models import EyloBaseModel, EyloOrganizationModel
from eylo.modules.connections.domain import ConnectionAuthKind

from .contracts import (
    SorChangeStrategy,
    SorCommandState,
    SorCustomFieldType,
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorMappingState,
    SorProfile,
    SorRelationIntentState,
    SorSensitivity,
    SorSourceAccess,
    SorSourceState,
    SorStreamState,
    SorSyncRunKind,
    SorTransformKind,
    SorWebhookReceiptState,
    SorWorkState,
)


def _enum(enum_type: type, name: str) -> ENUM:
    """Build one PostgreSQL enum using stable domain values."""
    return ENUM(
        enum_type,
        name=name,
        values_callable=lambda enum: [member.value for member in enum],
        create_type=True,
    )


class SorConnectorModel(EyloOrganizationModel):
    """One organization-owned vendor authorization configuration."""

    __tablename__ = "sor_connectors"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_sor_connectors_id_organization_id",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "vendor_key",
            name="uq_sor_connectors_id_organization_vendor",
        ),
        ForeignKeyConstraint(
            ["external_connection_id", "organization_id", "vendor_key"],
            [
                "connection_external_connections.id",
                "connection_external_connections.organization_id",
                "connection_external_connections.vendor_key",
            ],
            name="fk_sor_connectors_external_connection_organization_vendor",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "auth_kind = 'oauth2'",
            name="ck_sor_connectors_oauth2_only",
        ),
        CheckConstraint(
            "config_revision > 0",
            name="ck_sor_connectors_config_revision_positive",
        ),
        Index(
            "uq_sor_connectors_external_connection_org_active",
            "external_connection_id",
            "organization_id",
            unique=True,
            postgresql_where=text(
                "external_connection_id IS NOT NULL AND deleted = false"
            ),
        ),
        Index(
            "ix_sor_connectors_org_profile_vendor",
            "organization_id",
            "profile",
            "vendor_key",
        ),
        Index(
            "uq_sor_connectors_webhook_endpoint_key_active",
            "webhook_endpoint_key",
            unique=True,
            postgresql_where=text(
                "webhook_endpoint_key IS NOT NULL AND deleted = false"
            ),
        ),
        CheckConstraint(
            "(webhook_signing_secret IS NULL AND "
            "webhook_signing_secret_revision = 0) OR "
            "(webhook_signing_secret IS NOT NULL AND "
            "webhook_signing_secret_revision > 0)",
            name="ck_sor_connectors_webhook_signing_secret_revision",
        ),
        CheckConstraint(
            "webhook_authorized_connection_revision IS NULL OR "
            "webhook_authorized_connection_revision > 0",
            name="ck_sor_connectors_webhook_authorized_revision_positive",
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    profile: Mapped[SorProfile] = mapped_column(
        _enum(SorProfile, "sor_profile_enum"), nullable=False, index=True
    )
    vendor_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    auth_kind: Mapped[ConnectionAuthKind] = mapped_column(
        String(32),
        nullable=False,
        default=ConnectionAuthKind.OAUTH2.value,
        server_default=ConnectionAuthKind.OAUTH2.value,
    )
    oauth_client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    oauth_client_secret: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Encrypted client secret; never returned by an API read.",
        doc="Encrypted client secret; never returned by an API read.",
    )
    external_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    webhook_endpoint_key: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    webhook_signing_secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Encrypted app webhook signing secret; never returned by an API read.",
        doc="Encrypted app webhook signing secret; never returned by an API read.",
    )
    webhook_signing_secret_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    webhook_authorized_connection_revision: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    vendor_account_external_id: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    vendor_account_display_name: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    config_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    configured_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class SorSourceModel(EyloOrganizationModel):
    """One organization-owned configured vendor source."""

    __tablename__ = "sor_sources"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_sor_sources_id_organization_id",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            "profile",
            name="uq_sor_sources_id_organization_profile",
        ),
        UniqueConstraint(
            "organization_id",
            "onboarding_attempt_id",
            name="uq_sor_sources_organization_onboarding_attempt",
        ),
        ForeignKeyConstraint(
            ["external_connection_id", "organization_id", "vendor_key"],
            [
                "connection_external_connections.id",
                "connection_external_connections.organization_id",
                "connection_external_connections.vendor_key",
            ],
            name="fk_sor_sources_external_connection_organization_vendor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["active_schema_revision_id", "id", "organization_id"],
            [
                "sor_schema_revisions.id",
                "sor_schema_revisions.source_id",
                "sor_schema_revisions.organization_id",
            ],
            name="fk_sor_sources_active_schema_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["active_mapping_revision_id", "id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_sources_active_mapping_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "config_revision > 0",
            name="ck_sor_sources_config_revision_positive",
        ),
        CheckConstraint(
            "freshness_target_seconds > 0 AND required_sync_interval_seconds > 0",
            name="ck_sor_sources_sync_intervals_positive",
        ),
        CheckConstraint(
            "active_mapping_revision_id IS NULL OR active_schema_revision_id IS NOT NULL",
            name="ck_sor_sources_mapping_requires_schema",
        ),
        CheckConstraint(
            "webhook_endpoint_token_hash IS NULL OR "
            "webhook_endpoint_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_sources_webhook_token_hash",
        ),
        CheckConstraint(
            "(webhook_signing_secret IS NULL AND "
            "webhook_signing_secret_revision = 0) OR "
            "(webhook_signing_secret IS NOT NULL AND "
            "webhook_signing_secret_revision > 0)",
            name="ck_sor_sources_webhook_signing_secret_revision",
        ),
        CheckConstraint(
            "jsonb_typeof(configuration) = 'object' "
            "AND octet_length(configuration::text) <= 65536",
            name="ck_sor_sources_configuration",
        ),
        CheckConstraint(
            "jsonb_typeof(selected_objects) = 'array' "
            "AND octet_length(selected_objects::text) <= 65536",
            name="ck_sor_sources_selected_objects",
        ),
        Index(
            "ix_sor_sources_org_profile_state",
            "organization_id",
            "profile",
            "state",
        ),
        Index(
            "uq_sor_sources_webhook_endpoint_token_hash",
            "webhook_endpoint_token_hash",
            unique=True,
            postgresql_where=text("webhook_endpoint_token_hash IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    onboarding_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    profile: Mapped[SorProfile] = mapped_column(
        _enum(SorProfile, "sor_profile_enum"), nullable=False, index=True
    )
    vendor_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    configuration: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    selected_objects: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    config_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state: Mapped[SorSourceState] = mapped_column(
        _enum(SorSourceState, "sor_source_state_enum"),
        nullable=False,
        default=SorSourceState.DRAFT,
        server_default=SorSourceState.DRAFT.value,
        index=True,
    )
    active_schema_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    active_mapping_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    webhook_endpoint_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    webhook_signing_secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Encrypted vendor signing secret; never returned by an API read.",
        doc="Encrypted vendor signing secret; never returned by an API read.",
    )
    webhook_signing_secret_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    webhook_subscription_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    webhook_subscription_status: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    webhook_subscription_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    freshness_target_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=900, server_default="900"
    )
    required_sync_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=900, server_default="900"
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def has_webhook_signing_secret(self) -> bool:
        """Expose secret presence without exposing its encrypted envelope."""
        return self.webhook_signing_secret is not None


class SorCustomDatasetModel(EyloOrganizationModel):
    """One operator-enabled custom vendor object exposed for audit only."""

    __tablename__ = "sor_custom_datasets"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_custom_datasets_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "vendor_object_key",
            name="uq_sor_custom_datasets_source_object",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_custom_datasets_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(btrim(vendor_object_key)) > 0",
            name="ck_sor_custom_datasets_object_key",
        ),
        Index(
            "ix_sor_custom_datasets_org_source",
            "organization_id",
            "source_id",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class SorSchemaRevisionModel(EyloOrganizationModel):
    """Immutable normalized schema discovered from one exact source."""

    __tablename__ = "sor_schema_revisions"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_schema_revisions_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "revision",
            name="uq_sor_schema_revisions_source_revision",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_schema_revisions_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_sor_schema_revisions_revision_positive",
        ),
        CheckConstraint(
            "schema_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_schema_revisions_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(schema_snapshot) = 'object' "
            "AND octet_length(schema_snapshot::text) <= 2097152",
            name="ck_sor_schema_revisions_snapshot",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    vendor_api_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class SorMappingRevisionModel(EyloOrganizationModel):
    """Immutable publishable interpretation of one discovered source schema."""

    __tablename__ = "sor_mapping_revisions"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_mapping_revisions_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "revision",
            name="uq_sor_mapping_revisions_source_revision",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_mapping_revisions_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_schema_revision_id", "source_id", "organization_id"],
            [
                "sor_schema_revisions.id",
                "sor_schema_revisions.source_id",
                "sor_schema_revisions.organization_id",
            ],
            name="fk_sor_mapping_revisions_schema_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision > 0 AND projection_version > 0",
            name="ck_sor_mapping_revisions_revisions_positive",
        ),
        CheckConstraint(
            "(state = 'DRAFT' AND published_at IS NULL) OR "
            "(state <> 'DRAFT' AND published_at IS NOT NULL)",
            name="ck_sor_mapping_revisions_publication_state",
        ),
        Index(
            "uq_sor_mapping_revisions_active_source",
            "source_id",
            unique=True,
            postgresql_where=text("state = 'ACTIVE' AND deleted = false"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_schema_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    state: Mapped[SorMappingState] = mapped_column(
        _enum(SorMappingState, "sor_mapping_state_enum"),
        nullable=False,
        default=SorMappingState.DRAFT,
        server_default=SorMappingState.DRAFT.value,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    projection_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class SorCustomFieldDefinitionModel(EyloOrganizationModel):
    """Stable source field identity independent of labels and schema revisions."""

    __tablename__ = "sor_custom_field_definitions"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_custom_fields_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "vendor_object_key",
            "vendor_field_key",
            name="uq_sor_custom_fields_source_object_field",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_custom_fields_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "jsonb_typeof(choices) = 'array' AND octet_length(choices::text) <= 65536",
            name="ck_sor_custom_fields_choices",
        ),
        CheckConstraint(
            "removed_at IS NULL OR removed_at >= first_seen_at",
            name="ck_sor_custom_fields_removed_after_seen",
        ),
        Index(
            "ix_sor_custom_fields_source_active",
            "source_id",
            "vendor_object_key",
            postgresql_where=text("removed_at IS NULL AND deleted = false"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    vendor_field_key: Mapped[str] = mapped_column(String(256), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[SorCustomFieldType] = mapped_column(
        _enum(SorCustomFieldType, "sor_custom_field_type_enum"), nullable=False
    )
    choices: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_group: Mapped[str | None] = mapped_column(String(256), nullable=True)
    readable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    writable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    sensitivity: Mapped[SorSensitivity] = mapped_column(
        _enum(SorSensitivity, "sor_sensitivity_enum"),
        nullable=False,
        default=SorSensitivity.STANDARD,
        server_default=SorSensitivity.STANDARD.value,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SorFieldMappingModel(EyloOrganizationModel):
    """One selected field and bounded transform inside a mapping revision."""

    __tablename__ = "sor_field_mappings"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "mapping_revision_id",
            "vendor_object_key",
            "vendor_field_key",
            name="uq_sor_field_mappings_revision_object_field",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_field_mappings_revision_source_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["custom_field_definition_id", "source_id", "organization_id"],
            [
                "sor_custom_field_definitions.id",
                "sor_custom_field_definitions.source_id",
                "sor_custom_field_definitions.organization_id",
            ],
            name="fk_sor_field_mappings_custom_definition",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(direction = 'IGNORE' AND canonical_target_path IS NULL "
            "AND custom_field_definition_id IS NULL) OR "
            "(direction <> 'IGNORE' AND "
            "((canonical_target_path IS NOT NULL AND custom_field_definition_id IS NULL) "
            "OR (canonical_target_path IS NULL "
            "AND custom_field_definition_id IS NOT NULL)))",
            name="ck_sor_field_mappings_exact_target",
        ),
        CheckConstraint(
            "(state = 'ACTIVE' AND incompatibility_reason IS NULL) OR "
            "(state = 'INCOMPATIBLE' AND incompatibility_reason IS NOT NULL)",
            name="ck_sor_field_mappings_compatibility_reason",
        ),
        CheckConstraint(
            "jsonb_typeof(transform_config) = 'object' "
            "AND octet_length(transform_config::text) <= 16384",
            name="ck_sor_field_mappings_transform_config",
        ),
        CheckConstraint(
            "jsonb_typeof(enum_choices) = 'array' "
            "AND octet_length(enum_choices::text) <= 65536",
            name="ck_sor_field_mappings_enum_choices",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    vendor_field_key: Mapped[str] = mapped_column(String(256), nullable=False)
    source_label: Mapped[str] = mapped_column(String(256), nullable=False)
    source_data_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_target_path: Mapped[str | None] = mapped_column(
        String(320), nullable=True
    )
    custom_field_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    transform_kind: Mapped[SorTransformKind] = mapped_column(
        _enum(SorTransformKind, "sor_transform_kind_enum"), nullable=False
    )
    transform_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    direction: Mapped[SorFieldMappingDirection] = mapped_column(
        _enum(SorFieldMappingDirection, "sor_field_mapping_direction_enum"),
        nullable=False,
    )
    agent_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    ui_default_column: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enum_choices: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    sensitivity: Mapped[SorSensitivity] = mapped_column(
        _enum(SorSensitivity, "sor_sensitivity_enum"), nullable=False
    )
    writable_capability: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    state: Mapped[SorFieldMappingState] = mapped_column(
        _enum(SorFieldMappingState, "sor_field_mapping_state_enum"),
        nullable=False,
        default=SorFieldMappingState.ACTIVE,
        server_default=SorFieldMappingState.ACTIVE.value,
    )
    incompatibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SorRecordModel(EyloOrganizationModel):
    """One source identity and its mapping-approved projected payload."""

    __tablename__ = "sor_records"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_records_id_source_organization",
        ),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            "profile",
            "canonical_entity_kind",
            name="uq_sor_records_id_source_org_profile_entity",
        ),
        UniqueConstraint(
            "organization_id",
            "source_id",
            "vendor_object_key",
            "vendor_external_id",
            name="uq_sor_records_source_object_external_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id", "profile"],
            ["sor_sources.id", "sor_sources.organization_id", "sor_sources.profile"],
            name="fk_sor_records_source_organization_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_records_mapping_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["last_successful_sync_run_id", "source_id", "organization_id"],
            [
                "sor_sync_runs.id",
                "sor_sync_runs.source_id",
                "sor_sync_runs.organization_id",
            ],
            name="fk_sor_records_last_sync_run",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_records_payload_hash",
        ),
        CheckConstraint(
            "mapping_projection_version > 0",
            name="ck_sor_records_projection_version_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(selected_raw_payload) = 'object' "
            "AND octet_length(selected_raw_payload::text) <= 1048576",
            name="ck_sor_records_selected_payload",
        ),
        CheckConstraint(
            "jsonb_typeof(agent_visible_payload) = 'object' "
            "AND octet_length(agent_visible_payload::text) <= 1048576",
            name="ck_sor_records_agent_visible_payload",
        ),
        CheckConstraint(
            "(tombstoned_at IS NULL AND deletion_reason IS NULL) OR "
            "(tombstoned_at IS NOT NULL AND deletion_reason IS NOT NULL)",
            name="ck_sor_records_tombstone_reason",
        ),
        Index(
            "ix_sor_records_org_source_profile_entity_projected_live",
            "organization_id",
            "source_id",
            "profile",
            "canonical_entity_kind",
            text("projected_at DESC NULLS LAST"),
            text("id DESC"),
            postgresql_where=text("tombstoned_at IS NULL AND deleted = false"),
        ),
        Index(
            "ix_sor_records_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_sor_records_agent_search_vector",
            "agent_search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_sor_records_org_profile_entity_projected_live",
            "organization_id",
            "profile",
            "canonical_entity_kind",
            text("projected_at DESC NULLS LAST"),
            text("id DESC"),
            postgresql_where=text("tombstoned_at IS NULL AND deleted = false"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    profile: Mapped[SorProfile] = mapped_column(
        _enum(SorProfile, "sor_profile_enum"), nullable=False, index=True
    )
    canonical_entity_kind: Mapped[str] = mapped_column(
        String(96), nullable=False, index=True
    )
    vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    vendor_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    human_external_key: Mapped[str | None] = mapped_column(
        String(320), nullable=True, index=True
    )
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    source_revision: Mapped[str | None] = mapped_column(String(512), nullable=True)
    selected_raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    agent_visible_payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    mapping_projection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    projected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
    )
    last_successful_sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    agent_search_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    agent_search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)


class SorProfileRecordModel(EyloOrganizationModel):
    """Typed profile extension linked to one exact canonical source record."""

    __abstract__ = True

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    profile: Mapped[SorProfile] = mapped_column(
        _enum(SorProfile, "sor_profile_enum"), nullable=False
    )
    canonical_entity_kind: Mapped[str] = mapped_column(String(96), nullable=False)

    @staticmethod
    def get_record_constraints(
        tablename: str,
        *,
        profile: SorProfile,
        entity_kind: str,
    ) -> tuple:
        """Bind an extension row to the same tenant, source, profile, and entity."""
        return (
            UniqueConstraint(
                "record_id",
                name=f"uq_{tablename}_record_id",
            ),
            ForeignKeyConstraint(
                [
                    "record_id",
                    "source_id",
                    "organization_id",
                    "profile",
                    "canonical_entity_kind",
                ],
                [
                    "sor_records.id",
                    "sor_records.source_id",
                    "sor_records.organization_id",
                    "sor_records.profile",
                    "sor_records.canonical_entity_kind",
                ],
                name=f"fk_{tablename}_record_identity",
                ondelete="CASCADE",
            ),
            CheckConstraint(
                f"profile = '{profile.value}'",
                name=f"ck_{tablename}_profile",
            ),
            CheckConstraint(
                f"canonical_entity_kind = '{entity_kind}'",
                name=f"ck_{tablename}_entity_kind",
            ),
        )


class SorRecordRelationModel(EyloOrganizationModel):
    """One same-source relationship between two canonical record identities."""

    __tablename__ = "sor_record_relations"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "source_id",
            "from_record_id",
            "to_record_id",
            "canonical_relation_kind",
            "native_relation_kind",
            name="uq_sor_record_relations_identity",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_record_relations_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["from_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_record_relations_from_record",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["to_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_record_relations_to_record",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "from_record_id <> to_record_id",
            name="ck_sor_record_relations_distinct_records",
        ),
        Index(
            "uq_sor_record_relations_external_id",
            "source_id",
            "external_relation_id",
            unique=True,
            postgresql_where=text("external_relation_id IS NOT NULL"),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    from_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    to_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    canonical_relation_kind: Mapped[str] = mapped_column(String(96), nullable=False)
    native_relation_kind: Mapped[str] = mapped_column(String(160), nullable=False)
    external_relation_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SorRelationIntentModel(EyloOrganizationModel):
    """Persisted relationship identity awaiting two canonical endpoints."""

    __tablename__ = "sor_relation_intents"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_relation_intents_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "external_relation_id",
            name="uq_sor_relation_intents_source_external_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_relation_intents_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["origin_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_relation_intents_origin_record",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(from_vendor_object_key)) > 0 "
            "AND length(btrim(from_vendor_external_id)) > 0 "
            "AND length(btrim(to_vendor_object_key)) > 0 "
            "AND length(btrim(to_vendor_external_id)) > 0",
            name="ck_sor_relation_intents_endpoint_identity",
        ),
        CheckConstraint(
            "from_vendor_object_key <> to_vendor_object_key "
            "OR from_vendor_external_id <> to_vendor_external_id",
            name="ck_sor_relation_intents_distinct_endpoints",
        ),
        CheckConstraint(
            "resolution_attempts >= 0",
            name="ck_sor_relation_intents_attempts_nonnegative",
        ),
        Index(
            "ix_sor_relation_intents_source_state",
            "source_id",
            "state",
            "updated_at",
        ),
        Index(
            "ix_sor_relation_intents_from_endpoint",
            "source_id",
            "from_vendor_object_key",
            "from_vendor_external_id",
        ),
        Index(
            "ix_sor_relation_intents_to_endpoint",
            "source_id",
            "to_vendor_object_key",
            "to_vendor_external_id",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    origin_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    from_vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    from_vendor_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    to_vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    to_vendor_external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_relation_kind: Mapped[str] = mapped_column(String(96), nullable=False)
    native_relation_kind: Mapped[str] = mapped_column(String(160), nullable=False)
    external_relation_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(512), nullable=True)
    state: Mapped[SorRelationIntentState] = mapped_column(
        _enum(SorRelationIntentState, "sor_relation_intent_state_enum"),
        nullable=False,
        default=SorRelationIntentState.PENDING,
        server_default=SorRelationIntentState.PENDING.value,
        index=True,
    )
    resolution_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SorCustomFieldValueModel(EyloOrganizationModel):
    """Exactly one typed value for one record and custom field definition."""

    __tablename__ = "sor_custom_field_values"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "record_id",
            "field_definition_id",
            name="uq_sor_custom_field_values_record_field",
        ),
        ForeignKeyConstraint(
            ["record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_custom_field_values_record",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["field_definition_id", "source_id", "organization_id"],
            [
                "sor_custom_field_definitions.id",
                "sor_custom_field_definitions.source_id",
                "sor_custom_field_definitions.organization_id",
            ],
            name="fk_sor_custom_field_values_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reference_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_custom_field_values_reference_record",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(value_type = 'TEXT' AND text_value IS NOT NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'DECIMAL' AND text_value IS NULL "
            "AND decimal_value IS NOT NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'BOOLEAN' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NOT NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'DATE' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NOT NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'TIMESTAMP' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NOT NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'STRING_ARRAY' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NOT NULL AND reference_record_id IS NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'REFERENCE' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NOT NULL "
            "AND json_value IS NULL) OR "
            "(value_type = 'BOUNDED_JSON' AND text_value IS NULL "
            "AND decimal_value IS NULL AND boolean_value IS NULL "
            "AND date_value IS NULL AND timestamp_value IS NULL "
            "AND string_array_value IS NULL AND reference_record_id IS NULL "
            "AND json_value IS NOT NULL)",
            name="ck_sor_custom_field_values_exact_typed_value",
        ),
        CheckConstraint(
            "text_value IS NULL OR octet_length(text_value) <= 65536",
            name="ck_sor_custom_field_values_text_size",
        ),
        CheckConstraint(
            "string_array_value IS NULL OR cardinality(string_array_value) <= 128",
            name="ck_sor_custom_field_values_array_size",
        ),
        CheckConstraint(
            "json_value IS NULL OR octet_length(json_value::text) <= 16384",
            name="ck_sor_custom_field_values_json_size",
        ),
        Index("ix_sor_custom_field_values_text", "field_definition_id", "text_value"),
        Index(
            "ix_sor_custom_field_values_decimal",
            "field_definition_id",
            "decimal_value",
        ),
        Index(
            "ix_sor_custom_field_values_timestamp",
            "field_definition_id",
            "timestamp_value",
        ),
        Index(
            "ix_sor_custom_field_values_boolean",
            "field_definition_id",
            "boolean_value",
        ),
        Index(
            "ix_sor_custom_field_values_date",
            "field_definition_id",
            "date_value",
        ),
        Index(
            "ix_sor_custom_field_values_string_array",
            "string_array_value",
            postgresql_using="gin",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    field_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    value_type: Mapped[SorCustomFieldType] = mapped_column(
        _enum(SorCustomFieldType, "sor_custom_field_type_enum"), nullable=False
    )
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    decimal_value: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12), nullable=True
    )
    boolean_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    date_value: Mapped[date | None] = mapped_column(Date, nullable=True)
    timestamp_value: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    string_array_value: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(512)), nullable=True
    )
    reference_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    json_value: Mapped[dict | list | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )


class SorSourceStreamModel(EyloOrganizationModel):
    """Durable checkpoint and schedule for one enabled source object."""

    __tablename__ = "sor_source_streams"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_source_streams_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "vendor_object_key",
            name="uq_sor_source_streams_source_object",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_source_streams_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "cursor_version > 0 AND lookback_seconds >= 0",
            name="ck_sor_source_streams_cursor_lookback",
        ),
        CheckConstraint(
            "records_added >= 0 AND records_updated >= 0 "
            "AND records_tombstoned >= 0 AND records_unchanged >= 0 "
            "AND records_rejected >= 0",
            name="ck_sor_source_streams_counts_nonnegative",
        ),
        CheckConstraint(
            "checkpoint IS NULL OR octet_length(checkpoint) <= 1048576",
            name="ck_sor_source_streams_checkpoint_size",
        ),
        CheckConstraint(
            "jsonb_typeof(depends_on) = 'array' "
            "AND octet_length(depends_on::text) <= 65536",
            name="ck_sor_source_streams_dependencies",
        ),
        CheckConstraint(
            "jsonb_typeof(relationship_targets) = 'object' "
            "AND octet_length(relationship_targets::text) <= 65536",
            name="ck_sor_source_streams_relationship_targets",
        ),
        Index("ix_sor_source_streams_due", "state", "next_due_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    vendor_object_key: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_entity_kind: Mapped[str] = mapped_column(String(96), nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    relationship_targets: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    strategy: Mapped[SorChangeStrategy] = mapped_column(
        _enum(SorChangeStrategy, "sor_change_strategy_enum"), nullable=False
    )
    checkpoint: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Authenticated encryption envelope for an opaque vendor cursor.",
    )
    lookback_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cursor_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_committed_source_boundary: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    schedule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    state: Mapped[SorStreamState] = mapped_column(
        _enum(SorStreamState, "sor_stream_state_enum"),
        nullable=False,
        default=SorStreamState.ACTIVE,
        server_default=SorStreamState.ACTIVE.value,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    records_added: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_updated: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_tombstoned: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_unchanged: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_rejected: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class SorSyncGenerationModel(EyloOrganizationModel):
    """One source-level set of stream runs ordered by their declared DAG."""

    __tablename__ = "sor_sync_generations"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_sync_generations_id_source_organization",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_sync_generations_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(state IN ('PENDING', 'RUNNING', 'WAITING') AND finished_at IS NULL) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') "
            "AND finished_at IS NOT NULL)",
            name="ck_sor_sync_generations_terminal_time",
        ),
        Index(
            "ix_sor_sync_generations_source_created",
            "source_id",
            "created_at",
        ),
        Index(
            "ix_sor_sync_generations_org_state",
            "organization_id",
            "state",
        ),
        Index(
            "uq_sor_sync_generations_active_source",
            "organization_id",
            "source_id",
            unique=True,
            postgresql_where=text(
                "deleted = false AND state IN ('PENDING', 'RUNNING', 'WAITING')"
            ),
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    kind: Mapped[SorSyncRunKind] = mapped_column(
        _enum(SorSyncRunKind, "sor_sync_run_kind_enum"), nullable=False
    )
    state: Mapped[SorWorkState] = mapped_column(
        _enum(SorWorkState, "sor_work_state_enum"),
        nullable=False,
        default=SorWorkState.PENDING,
        server_default=SorWorkState.PENDING.value,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    safe_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SorSyncRunModel(EyloOrganizationModel):
    """Product-visible state for one Absurd-owned source projection run."""

    __tablename__ = "sor_sync_runs"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_sync_runs_id_source_organization",
        ),
        UniqueConstraint(
            "absurd_task_id",
            name="uq_sor_sync_runs_absurd_task_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_sync_runs_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["stream_id", "source_id", "organization_id"],
            [
                "sor_source_streams.id",
                "sor_source_streams.source_id",
                "sor_source_streams.organization_id",
            ],
            name="fk_sor_sync_runs_stream_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["generation_id", "source_id", "organization_id"],
            [
                "sor_sync_generations.id",
                "sor_sync_generations.source_id",
                "sor_sync_generations.organization_id",
            ],
            name="fk_sor_sync_runs_generation_source_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_sync_runs_mapping_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0",
            name="ck_sor_sync_runs_attempts",
        ),
        CheckConstraint(
            "records_added >= 0 AND records_updated >= 0 "
            "AND records_tombstoned >= 0 AND records_unchanged >= 0 "
            "AND records_rejected >= 0",
            name="ck_sor_sync_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_sync_runs_error_size",
        ),
        CheckConstraint(
            "(state IN ('PENDING', 'RUNNING', 'WAITING') AND finished_at IS NULL) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') "
            "AND finished_at IS NOT NULL)",
            name="ck_sor_sync_runs_terminal_time",
        ),
        Index(
            "uq_sor_sync_runs_active_stream",
            "stream_id",
            unique=True,
            postgresql_where=text(
                "stream_id IS NOT NULL AND deleted = false "
                "AND state IN ('PENDING', 'RUNNING', 'WAITING')"
            ),
        ),
        Index("ix_sor_sync_runs_source_created", "source_id", "created_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    stream_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    mapping_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    kind: Mapped[SorSyncRunKind] = mapped_column(
        _enum(SorSyncRunKind, "sor_sync_run_kind_enum"), nullable=False
    )
    state: Mapped[SorWorkState] = mapped_column(
        _enum(SorWorkState, "sor_work_state_enum"),
        nullable=False,
        default=SorWorkState.PENDING,
        server_default=SorWorkState.PENDING.value,
        index=True,
    )
    absurd_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default="3"
    )
    checkpoint_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkpoint_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    safe_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    records_added: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_updated: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_tombstoned: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_unchanged: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    records_rejected: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class SorWebhookReceiptModel(EyloOrganizationModel):
    """Deduplicated verified webhook hint awaiting durable refetch."""

    __tablename__ = "sor_webhook_receipts"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_webhook_receipts_id_source_organization",
        ),
        UniqueConstraint(
            "source_id",
            "vendor_delivery_id",
            name="uq_sor_webhook_receipts_source_delivery",
        ),
        UniqueConstraint(
            "source_id",
            "fingerprint",
            name="uq_sor_webhook_receipts_source_fingerprint",
        ),
        UniqueConstraint(
            "absurd_task_id",
            name="uq_sor_webhook_receipts_absurd_task_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_webhook_receipts_source_organization",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$' AND payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_webhook_receipts_hashes",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts > 0",
            name="ck_sor_webhook_receipts_attempts",
        ),
        CheckConstraint(
            "(encrypted_raw_body IS NULL AND raw_body_expires_at IS NULL) OR "
            "(encrypted_raw_body IS NOT NULL AND raw_body_expires_at IS NOT NULL)",
            name="ck_sor_webhook_receipts_raw_body_ttl",
        ),
        CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_webhook_receipts_error_size",
        ),
        CheckConstraint(
            "jsonb_typeof(signals) = 'array' AND octet_length(signals::text) <= 262144",
            name="ck_sor_webhook_receipts_signals",
        ),
        Index("ix_sor_webhook_receipts_source_state", "source_id", "state"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    vendor_delivery_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(256), nullable=False)
    vendor_object_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    vendor_external_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    vendor_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    replay_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    signals: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        doc="All normalized signals carried by this one vendor delivery.",
    )
    state: Mapped[SorWebhookReceiptState] = mapped_column(
        _enum(SorWebhookReceiptState, "sor_webhook_receipt_state_enum"),
        nullable=False,
        default=SorWebhookReceiptState.PENDING,
        server_default=SorWebhookReceiptState.PENDING.value,
    )
    encrypted_raw_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_body_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    absurd_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default="3"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    safe_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class SorSourceGrantModel(EyloOrganizationModel):
    """Live Agent authority for one source; revisions invalidate resumed work."""

    __tablename__ = "sor_source_grants"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_source_grants_id_source_organization",
        ),
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent_agents.id", "agent_agents.organization_id"],
            name="fk_sor_source_grants_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_source_grants_source_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "revision > 0",
            name="ck_sor_source_grants_revision_positive",
        ),
        CheckConstraint(
            "(deleted = false AND revoked_at IS NULL) OR "
            "(deleted = true AND revoked_at IS NOT NULL)",
            name="ck_sor_source_grants_revocation_state",
        ),
        Index(
            "uq_sor_source_grants_agent_source_active",
            "agent_id",
            "source_id",
            unique=True,
            postgresql_where=text("deleted = false"),
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    access: Mapped[SorSourceAccess] = mapped_column(
        _enum(SorSourceAccess, "sor_source_access_enum"), nullable=False
    )
    revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class SorAgentRevisionSourceGrantModel(EyloBaseModel):
    """Exact source grant copied into one immutable published Agent revision."""

    __tablename__ = "sor_agent_revision_source_grants"

    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "agent_revision",
            "source_id",
            name="uq_sor_agent_revision_grants_agent_revision_source",
        ),
        ForeignKeyConstraint(
            ["agent_id", "agent_revision", "organization_id"],
            [
                "agent_definition_revisions.agent_id",
                "agent_definition_revisions.revision",
                "agent_definition_revisions.organization_id",
            ],
            name="fk_sor_agent_revision_grants_agent_revision",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_grant_id", "source_id", "organization_id"],
            [
                "sor_source_grants.id",
                "sor_source_grants.source_id",
                "sor_source_grants.organization_id",
            ],
            name="fk_sor_agent_revision_grants_live_grant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "agent_revision > 0 AND source_grant_revision > 0",
            name="ck_sor_agent_revision_grants_revisions_positive",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    agent_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_grant_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    access: Mapped[SorSourceAccess] = mapped_column(
        _enum(SorSourceAccess, "sor_source_access_enum"), nullable=False
    )


class SorCommandModel(EyloOrganizationModel):
    """The sole durable mutation receipt for one Agent tool call."""

    __tablename__ = "sor_commands"

    __table_args__ = (
        *EyloOrganizationModel.get_organization_constraints(__tablename__),
        UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_commands_id_source_organization",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_sor_commands_organization_idempotency",
        ),
        UniqueConstraint(
            "absurd_task_id",
            name="uq_sor_commands_absurd_task_id",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id", "profile"],
            ["sor_sources.id", "sor_sources.organization_id", "sor_sources.profile"],
            name="fk_sor_commands_source_organization_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_commands_target_record",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_grant_id", "source_id", "organization_id"],
            [
                "sor_source_grants.id",
                "sor_source_grants.source_id",
                "sor_source_grants.organization_id",
            ],
            name="fk_sor_commands_source_grant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_id", "agent_revision", "organization_id"],
            [
                "agent_definition_revisions.agent_id",
                "agent_definition_revisions.revision",
                "agent_definition_revisions.organization_id",
            ],
            name="fk_sor_commands_agent_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["agent_run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_sor_commands_agent_run",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_commands_request_hash",
        ),
        CheckConstraint(
            "agent_revision > 0 AND source_grant_revision > 0 "
            "AND attempts >= 0 AND max_attempts > 0",
            name="ck_sor_commands_revisions_attempts",
        ),
        CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 320 "
            "AND length(tool_call_id) BETWEEN 1 AND 320",
            name="ck_sor_commands_identity_sizes",
        ),
        CheckConstraint(
            "octet_length(request_payload) <= 1048576",
            name="ck_sor_commands_request_payload_size",
        ),
        CheckConstraint(
            "safe_result IS NULL OR "
            "(jsonb_typeof(safe_result) = 'object' "
            "AND octet_length(safe_result::text) <= 65536)",
            name="ck_sor_commands_safe_result",
        ),
        CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_commands_error_size",
        ),
        CheckConstraint(
            "(state IN ('PENDING', 'RUNNING') AND finished_at IS NULL) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'CONFLICT', 'CANCELLED') "
            "AND finished_at IS NOT NULL)",
            name="ck_sor_commands_terminal_time",
        ),
        CheckConstraint(
            "(state = 'SUCCEEDED' AND mutation_applied_at IS NOT NULL) OR "
            "(state IN ('CONFLICT', 'CANCELLED') AND mutation_applied_at IS NULL) OR "
            "state IN ('PENDING', 'RUNNING', 'FAILED')",
            name="ck_sor_commands_mutation_checkpoint",
        ),
        Index("ix_sor_commands_source_state", "source_id", "state"),
        Index("ix_sor_commands_agent_run", "agent_run_id", "created_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    profile: Mapped[SorProfile] = mapped_column(
        _enum(SorProfile, "sor_profile_enum"), nullable=False
    )
    profile_tool: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    agent_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tool_call_id: Mapped[str] = mapped_column(String(320), nullable=False)
    source_grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_grant_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(320), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Authenticated encryption envelope for the typed command payload.",
    )
    target_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    expected_source_revision: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    state: Mapped[SorCommandState] = mapped_column(
        _enum(SorCommandState, "sor_command_state_enum"),
        nullable=False,
        default=SorCommandState.PENDING,
        server_default=SorCommandState.PENDING.value,
        index=True,
    )
    safe_result: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    external_request_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_revision_after: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    mutation_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    absurd_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default="3"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    safe_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = [
    "SorAgentRevisionSourceGrantModel",
    "SorCommandModel",
    "SorConnectorModel",
    "SorCustomDatasetModel",
    "SorCustomFieldDefinitionModel",
    "SorCustomFieldValueModel",
    "SorFieldMappingModel",
    "SorMappingRevisionModel",
    "SorRecordModel",
    "SorRecordRelationModel",
    "SorRelationIntentModel",
    "SorSchemaRevisionModel",
    "SorSourceGrantModel",
    "SorSourceModel",
    "SorSourceStreamModel",
    "SorSyncGenerationModel",
    "SorSyncRunModel",
    "SorWebhookReceiptModel",
]
