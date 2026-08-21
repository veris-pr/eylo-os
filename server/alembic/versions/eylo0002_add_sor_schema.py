"""Reconcile the legacy baseline and add SOR persistence.

Revision ID: eylo0002
Revises: eylo0001
Create Date: 2026-08-21 05:09:34.185438

"""

import base64
import json
import os
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eylo0002"
down_revision: str | None = "eylo0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CURRENT_TABLES = frozenset(
    {
        "connection_external_connections",
        "integration_v2_connection_links",
        "sor_agent_revision_source_grants",
        "sor_commands",
        "sor_connectors",
        "sor_crm_activities",
        "sor_crm_companies",
        "sor_crm_contacts",
        "sor_crm_deals",
        "sor_custom_datasets",
        "sor_custom_field_definitions",
        "sor_custom_field_values",
        "sor_field_mappings",
        "sor_knowledge_attachments",
        "sor_knowledge_authors",
        "sor_knowledge_blocks",
        "sor_knowledge_documents",
        "sor_knowledge_properties",
        "sor_knowledge_spaces",
        "sor_knowledge_versions",
        "sor_mapping_revisions",
        "sor_record_relations",
        "sor_records",
        "sor_schema_revisions",
        "sor_source_grants",
        "sor_source_streams",
        "sor_sources",
        "sor_support_agents",
        "sor_support_attachments",
        "sor_support_customers",
        "sor_support_inboxes",
        "sor_support_messages",
        "sor_support_queues",
        "sor_support_sla_metrics",
        "sor_support_tags",
        "sor_support_tickets",
        "sor_sync_runs",
        "sor_ticketing_comments",
        "sor_ticketing_cycles",
        "sor_ticketing_issue_relations",
        "sor_ticketing_issues",
        "sor_ticketing_labels",
        "sor_ticketing_projects",
        "sor_ticketing_users",
        "sor_ticketing_workflow_states",
        "sor_webhook_receipts",
    }
)
_LEGACY_TABLES = frozenset(
    {
        "agent_runs",
        "connection_connections",
        "connection_oauth_states",
        "integration_v2_installations",
    }
)
_CURRENT_COLUMNS = {
    "agent_runs": {"waiting_tool_owner_id", "waiting_tool_owner_kind"},
    "connection_oauth_states": {
        "expected_connection_revision",
        "external_connection_id",
        "requested_scopes",
    },
}
_CONNECTION_STATUS_MAP = {
    "ACTIVE": "ACTIVE",
    "FAILED": "DEGRADED",
    "INACTIVE": "REAUTH_REQUIRED",
    "INITIATED": "INITIATED",
    "REVOKED": "REVOKED",
}


def upgrade() -> None:
    """Reconcile the legacy `eylo0001` shape with the current baseline."""
    inspector = sa.inspect(op.get_bind())
    tables = frozenset(inspector.get_table_names())
    current_tables = tables & _CURRENT_TABLES

    if current_tables == _CURRENT_TABLES:
        _assert_current_columns(inspector)
        return
    if current_tables:
        unexpected = ", ".join(sorted(current_tables))
        raise RuntimeError(
            "Refusing a partial SOR schema migration. Existing current tables: "
            f"{unexpected}."
        )

    missing_legacy_tables = _LEGACY_TABLES - tables
    if missing_legacy_tables:
        missing = ", ".join(sorted(missing_legacy_tables))
        raise RuntimeError(
            "The database does not match the supported legacy eylo0001 shape. "
            f"Missing tables: {missing}."
        )

    _upgrade_legacy_schema()


def _assert_current_columns(inspector: Inspector) -> None:
    for table_name, expected_columns in _CURRENT_COLUMNS.items():
        present_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        missing_columns = expected_columns - present_columns
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise RuntimeError(
                f"Refusing a partial schema migration for {table_name}. "
                f"Missing columns: {missing}."
            )


def _migrate_legacy_connections() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                connection.id,
                connection.organization_id,
                connection.contact_id,
                connection.connection_kind,
                connection.status,
                connection.credentials,
                connection.credentials_expires_at,
                connection.last_refresh_success_at,
                connection.last_refresh_failure_at,
                connection.refresh_attempts,
                connection.is_refresh_exhausted,
                connection.external_id,
                connection.deleted,
                connection.created_at,
                connection.updated_at,
                installation.id AS installation_id,
                installation.vendor,
                installation.auth_kind,
                installation.instance_url
            FROM connection_connections AS connection
            JOIN integration_v2_installations AS installation
              ON installation.id = connection.integration_id
             AND installation.organization_id = connection.organization_id
            """
        )
    ).mappings()

    for row in rows:
        credentials = row["credentials"]
        encrypted_credentials = (
            _encrypt_legacy_credentials(
                credentials,
                organization_id=row["organization_id"],
                connection_id=row["id"],
            )
            if credentials is not None
            else None
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO connection_external_connections (
                    id, organization_id, contact_id, owner_kind, vendor_key,
                    auth_kind, instance_origin, granted_scopes, credentials,
                    credentials_expires_at, revision, status,
                    last_refresh_success_at, last_refresh_failure_at,
                    refresh_attempts, last_error_code, external_id, deleted,
                    created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :contact_id,
                    CAST(:owner_kind AS external_connection_owner_kind_enum),
                    :vendor_key, :auth_kind, :instance_origin,
                    CAST(:granted_scopes AS jsonb), :credentials,
                    :credentials_expires_at, 1,
                    CAST(:status AS external_connection_status_enum),
                    :last_refresh_success_at, :last_refresh_failure_at,
                    :refresh_attempts, :last_error_code, :external_id, :deleted,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": row["id"],
                "organization_id": row["organization_id"],
                "contact_id": row["contact_id"],
                "owner_kind": str(row["connection_kind"]),
                "vendor_key": row["vendor"],
                "auth_kind": row["auth_kind"],
                "instance_origin": row["instance_url"],
                "granted_scopes": json.dumps(_legacy_scopes(credentials)),
                "credentials": encrypted_credentials,
                "credentials_expires_at": row["credentials_expires_at"],
                "status": _CONNECTION_STATUS_MAP[str(row["status"])],
                "last_refresh_success_at": row["last_refresh_success_at"],
                "last_refresh_failure_at": row["last_refresh_failure_at"],
                "refresh_attempts": row["refresh_attempts"],
                "last_error_code": _legacy_error_code(row),
                "external_id": row["external_id"],
                "deleted": row["deleted"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO integration_v2_connection_links (
                    id, organization_id, installation_id,
                    external_connection_id, vendor, deleted,
                    created_at, updated_at
                ) VALUES (
                    :id, :organization_id, :installation_id,
                    :external_connection_id, :vendor, :deleted,
                    :created_at, :updated_at
                )
                """
            ),
            {
                "id": row["id"],
                "organization_id": row["organization_id"],
                "installation_id": row["installation_id"],
                "external_connection_id": row["id"],
                "vendor": row["vendor"],
                "deleted": row["deleted"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )


def _encrypt_legacy_credentials(
    credentials: Mapping[str, object],
    *,
    organization_id: object,
    connection_id: object,
) -> str:
    if not isinstance(credentials, Mapping):
        raise RuntimeError("Legacy connection credentials have an invalid shape.")
    key_hex = os.environ.get("ENCRYPTION_KEY", "")
    try:
        key = bytes.fromhex(key_hex)
    except ValueError as error:
        raise RuntimeError(
            "ENCRYPTION_KEY must be 64 hexadecimal characters."
        ) from error
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must be 64 hexadecimal characters.")

    nonce = os.urandom(12)
    plaintext = json.dumps(
        dict(credentials),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    associated_data = (
        f"provider-config:{organization_id}:{connection_id}:external_connection:1"
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    return ".".join(("v1", _base64url(nonce), _base64url(ciphertext)))


def _legacy_scopes(credentials: object) -> list[str]:
    if not isinstance(credentials, Mapping):
        return []
    for key in ("granted_scopes", "scopes"):
        value = credentials.get(key)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return list(dict.fromkeys(value))
    scope = credentials.get("scope")
    if isinstance(scope, str):
        return list(dict.fromkeys(scope.split()))
    return []


def _legacy_error_code(row: Mapping[str, object]) -> str | None:
    if row["is_refresh_exhausted"]:
        return "REFRESH_EXHAUSTED"
    if str(row["status"]) == "FAILED":
        return "LEGACY_CONNECTION_FAILED"
    if str(row["status"]) == "INACTIVE":
        return "LEGACY_CONNECTION_INACTIVE"
    return None


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _upgrade_legacy_schema() -> None:
    # OAuth state is short-lived and tied to the removed connection contract.
    op.execute(sa.text("DELETE FROM connection_oauth_states"))
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE agent_run_lifecycle_enum "
            "ADD VALUE IF NOT EXISTS 'waiting_for_tool' "
            "AFTER 'waiting_for_approval'"
        )

    op.create_table(
        "connection_external_connections",
        sa.Column("contact_id", sa.UUID(), nullable=True),
        sa.Column(
            "owner_kind",
            postgresql.ENUM(
                "ORGANIZATION", "CONTACT", name="external_connection_owner_kind_enum"
            ),
            nullable=False,
        ),
        sa.Column("vendor_key", sa.String(length=64), nullable=False),
        sa.Column("auth_kind", sa.String(length=32), nullable=False),
        sa.Column("instance_origin", sa.String(length=512), nullable=True),
        sa.Column(
            "granted_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("credentials", sa.Text(), nullable=True),
        sa.Column("credentials_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "INITIATED",
                "ACTIVE",
                "DEGRADED",
                "REAUTH_REQUIRED",
                "REVOKED",
                name="external_connection_status_enum",
            ),
            server_default="INITIATED",
            nullable=False,
        ),
        sa.Column("last_refresh_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "refresh_attempts", sa.SmallInteger(), server_default="0", nullable=False
        ),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(owner_kind = 'CONTACT' AND contact_id IS NOT NULL) OR (owner_kind = 'ORGANIZATION' AND contact_id IS NULL)",
            name="ck_connection_external_connections_exact_owner",
        ),
        sa.CheckConstraint(
            "auth_kind IN ('no_auth', 'api_key', 'basic', 'oauth2')",
            name="ck_connection_external_connections_auth_kind",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_connection_external_connections_positive_revision"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id", "organization_id"],
            ["contact_contacts.id", "contact_contacts.organization_id"],
            name="fk_connection_external_connections_contact_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            "vendor_key",
            name="uq_connection_external_connections_id_org_vendor",
        ),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_connection_external_connections_id_organization_id",
        ),
    )
    op.create_index(
        op.f("ix_connection_external_connections_contact_id"),
        "connection_external_connections",
        ["contact_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_created_at"),
        "connection_external_connections",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_credentials_expires_at"),
        "connection_external_connections",
        ["credentials_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_last_refresh_failure_at"),
        "connection_external_connections",
        ["last_refresh_failure_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_last_refresh_success_at"),
        "connection_external_connections",
        ["last_refresh_success_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_organization_id"),
        "connection_external_connections",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_connection_external_connections_vendor_key"),
        "connection_external_connections",
        ["vendor_key"],
        unique=False,
    )
    op.create_index(
        "ix_unq_connection_external_connections_ext_id_org_id",
        "connection_external_connections",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_unique_constraint(
        "uq_integration_v2_installations_id_org_vendor",
        "integration_v2_installations",
        ["id", "organization_id", "vendor"],
    )
    op.create_table(
        "integration_v2_connection_links",
        sa.Column("installation_id", sa.UUID(), nullable=False),
        sa.Column("external_connection_id", sa.UUID(), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["external_connection_id", "organization_id", "vendor"],
            [
                "connection_external_connections.id",
                "connection_external_connections.organization_id",
                "connection_external_connections.vendor_key",
            ],
            name="fk_integration_v2_connection_links_external_connection",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id", "organization_id", "vendor"],
            [
                "integration_v2_installations.id",
                "integration_v2_installations.organization_id",
                "integration_v2_installations.vendor",
            ],
            name="fk_integration_v2_connection_links_installation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_connection_id",
            "organization_id",
            name="uq_integration_v2_connection_links_connection_org",
        ),
        sa.UniqueConstraint(
            "installation_id",
            "external_connection_id",
            "organization_id",
            name="uq_integration_v2_connection_links_installation_connection",
        ),
    )
    op.create_index(
        op.f("ix_integration_v2_connection_links_created_at"),
        "integration_v2_connection_links",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_v2_connection_links_external_connection_id"),
        "integration_v2_connection_links",
        ["external_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_v2_connection_links_installation_id"),
        "integration_v2_connection_links",
        ["installation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_integration_v2_connection_links_organization_id"),
        "integration_v2_connection_links",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_integration_v2_connection_links_ext_id_org_id",
        "integration_v2_connection_links",
        ["external_id", "organization_id"],
        unique=True,
    )
    _migrate_legacy_connections()
    op.create_table(
        "sor_connectors",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("vendor_key", sa.String(length=64), nullable=False),
        sa.Column(
            "auth_kind", sa.String(length=32), server_default="oauth2", nullable=False
        ),
        sa.Column("oauth_client_id", sa.String(length=512), nullable=False),
        sa.Column(
            "oauth_client_secret",
            sa.Text(),
            nullable=False,
            comment="Encrypted client secret; never returned by an API read.",
        ),
        sa.Column("external_connection_id", sa.UUID(), nullable=True),
        sa.Column("config_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("configured_by", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "auth_kind = 'oauth2'", name="ck_sor_connectors_oauth2_only"
        ),
        sa.CheckConstraint(
            "config_revision > 0", name="ck_sor_connectors_config_revision_positive"
        ),
        sa.ForeignKeyConstraint(
            ["external_connection_id", "organization_id", "vendor_key"],
            [
                "connection_external_connections.id",
                "connection_external_connections.organization_id",
                "connection_external_connections.vendor_key",
            ],
            name="fk_sor_connectors_external_connection_organization_vendor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            "vendor_key",
            name="uq_sor_connectors_id_organization_vendor",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_sor_connectors_id_organization_id"
        ),
    )
    op.create_index(
        op.f("ix_sor_connectors_created_at"),
        "sor_connectors",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_connectors_external_connection_id"),
        "sor_connectors",
        ["external_connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_connectors_org_profile_vendor",
        "sor_connectors",
        ["organization_id", "profile", "vendor_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_connectors_organization_id"),
        "sor_connectors",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_connectors_profile"), "sor_connectors", ["profile"], unique=False
    )
    op.create_index(
        op.f("ix_sor_connectors_vendor_key"),
        "sor_connectors",
        ["vendor_key"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_connectors_ext_id_org_id",
        "sor_connectors",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_connectors_external_connection_org_active",
        "sor_connectors",
        ["external_connection_id", "organization_id"],
        unique=True,
        postgresql_where=sa.text(
            "external_connection_id IS NOT NULL AND deleted = false"
        ),
    )
    op.create_table(
        "sor_sources",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("vendor_key", sa.String(length=64), nullable=False),
        sa.Column("external_connection_id", sa.UUID(), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "selected_objects",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("config_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(
                "DRAFT",
                "VERIFYING",
                "DISCOVERING",
                "BOOTSTRAPPING",
                "ACTIVE",
                "DEGRADED",
                "REAUTH_REQUIRED",
                "DISABLED",
                name="sor_source_state_enum",
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("active_schema_revision_id", sa.UUID(), nullable=True),
        sa.Column("active_mapping_revision_id", sa.UUID(), nullable=True),
        sa.Column("webhook_endpoint_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "webhook_signing_secret",
            sa.Text(),
            nullable=True,
            comment="Encrypted vendor signing secret; never returned by an API read.",
        ),
        sa.Column(
            "webhook_signing_secret_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("webhook_subscription_id", sa.String(length=512), nullable=True),
        sa.Column("webhook_subscription_status", sa.String(length=64), nullable=True),
        sa.Column(
            "webhook_subscription_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "freshness_target_seconds",
            sa.Integer(),
            server_default="900",
            nullable=False,
        ),
        sa.Column(
            "required_sync_interval_seconds",
            sa.Integer(),
            server_default="900",
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reconciliation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_summary", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(configuration) = 'object' AND octet_length(configuration::text) <= 65536",
            name="ck_sor_sources_configuration",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_objects) = 'array' AND octet_length(selected_objects::text) <= 65536",
            name="ck_sor_sources_selected_objects",
        ),
        sa.CheckConstraint(
            "webhook_endpoint_token_hash IS NULL OR webhook_endpoint_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_sources_webhook_token_hash",
        ),
        sa.CheckConstraint(
            "(webhook_signing_secret IS NULL AND webhook_signing_secret_revision = 0) OR (webhook_signing_secret IS NOT NULL AND webhook_signing_secret_revision > 0)",
            name="ck_sor_sources_webhook_signing_secret_revision",
        ),
        sa.CheckConstraint(
            "active_mapping_revision_id IS NULL OR active_schema_revision_id IS NOT NULL",
            name="ck_sor_sources_mapping_requires_schema",
        ),
        sa.CheckConstraint(
            "config_revision > 0", name="ck_sor_sources_config_revision_positive"
        ),
        sa.CheckConstraint(
            "freshness_target_seconds > 0 AND required_sync_interval_seconds > 0",
            name="ck_sor_sources_sync_intervals_positive",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["external_connection_id", "organization_id", "vendor_key"],
            [
                "connection_external_connections.id",
                "connection_external_connections.organization_id",
                "connection_external_connections.vendor_key",
            ],
            name="fk_sor_sources_external_connection_organization_vendor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            "profile",
            name="uq_sor_sources_id_organization_profile",
        ),
        sa.UniqueConstraint(
            "id", "organization_id", name="uq_sor_sources_id_organization_id"
        ),
    )
    op.create_index(
        op.f("ix_sor_sources_created_at"), "sor_sources", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sources_external_connection_id"),
        "sor_sources",
        ["external_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sources_last_successful_sync_at"),
        "sor_sources",
        ["last_successful_sync_at"],
        unique=False,
    )
    op.create_index(
        "ix_sor_sources_org_profile_state",
        "sor_sources",
        ["organization_id", "profile", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sources_organization_id"),
        "sor_sources",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sources_profile"), "sor_sources", ["profile"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sources_state"), "sor_sources", ["state"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sources_vendor_key"), "sor_sources", ["vendor_key"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sources_webhook_subscription_expires_at"),
        "sor_sources",
        ["webhook_subscription_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_sources_ext_id_org_id",
        "sor_sources",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_sources_webhook_endpoint_token_hash",
        "sor_sources",
        ["webhook_endpoint_token_hash"],
        unique=True,
        postgresql_where=sa.text("webhook_endpoint_token_hash IS NOT NULL"),
    )
    op.create_table(
        "sor_custom_datasets",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(vendor_object_key)) > 0",
            name="ck_sor_custom_datasets_object_key",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_custom_datasets_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_custom_datasets_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id",
            "vendor_object_key",
            name="uq_sor_custom_datasets_source_object",
        ),
    )
    op.create_index(
        op.f("ix_sor_custom_datasets_created_at"),
        "sor_custom_datasets",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_datasets_org_source",
        "sor_custom_datasets",
        ["organization_id", "source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_datasets_organization_id"),
        "sor_custom_datasets",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_datasets_source_id"),
        "sor_custom_datasets",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_custom_datasets_ext_id_org_id",
        "sor_custom_datasets",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_custom_field_definitions",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("vendor_field_key", sa.String(length=256), nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "data_type",
            postgresql.ENUM(
                "TEXT",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "TIMESTAMP",
                "STRING_ARRAY",
                "REFERENCE",
                "BOUNDED_JSON",
                name="sor_custom_field_type_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "choices",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_group", sa.String(length=256), nullable=True),
        sa.Column("readable", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("writable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "sensitivity",
            postgresql.ENUM(
                "STANDARD", "PERSONAL", "SENSITIVE", name="sor_sensitivity_enum"
            ),
            server_default="STANDARD",
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(choices) = 'array' AND octet_length(choices::text) <= 65536",
            name="ck_sor_custom_fields_choices",
        ),
        sa.CheckConstraint(
            "removed_at IS NULL OR removed_at >= first_seen_at",
            name="ck_sor_custom_fields_removed_after_seen",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_custom_fields_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_custom_fields_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id",
            "vendor_object_key",
            "vendor_field_key",
            name="uq_sor_custom_fields_source_object_field",
        ),
    )
    op.create_index(
        op.f("ix_sor_custom_field_definitions_created_at"),
        "sor_custom_field_definitions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_definitions_organization_id"),
        "sor_custom_field_definitions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_definitions_source_id"),
        "sor_custom_field_definitions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_fields_source_active",
        "sor_custom_field_definitions",
        ["source_id", "vendor_object_key"],
        unique=False,
        postgresql_where=sa.text("removed_at IS NULL AND deleted = false"),
    )
    op.create_index(
        "ix_unq_sor_custom_field_definitions_ext_id_org_id",
        "sor_custom_field_definitions",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_schema_revisions",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "schema_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("vendor_api_version", sa.String(length=128), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("discovery_run_id", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(schema_snapshot) = 'object' AND octet_length(schema_snapshot::text) <= 2097152",
            name="ck_sor_schema_revisions_snapshot",
        ),
        sa.CheckConstraint(
            "schema_hash ~ '^[0-9a-f]{64}$'", name="ck_sor_schema_revisions_hash"
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_sor_schema_revisions_revision_positive"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_schema_revisions_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_schema_revisions_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id", "revision", name="uq_sor_schema_revisions_source_revision"
        ),
    )
    op.create_index(
        op.f("ix_sor_schema_revisions_created_at"),
        "sor_schema_revisions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_schema_revisions_organization_id"),
        "sor_schema_revisions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_schema_revisions_schema_hash"),
        "sor_schema_revisions",
        ["schema_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_schema_revisions_source_id"),
        "sor_schema_revisions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_schema_revisions_ext_id_org_id",
        "sor_schema_revisions",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_source_grants",
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "access",
            postgresql.ENUM("READ", "READ_WRITE", name="sor_source_access_enum"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(deleted = false AND revoked_at IS NULL) OR (deleted = true AND revoked_at IS NOT NULL)",
            name="ck_sor_source_grants_revocation_state",
        ),
        sa.CheckConstraint(
            "revision > 0", name="ck_sor_source_grants_revision_positive"
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent_agents.id", "agent_agents.organization_id"],
            name="fk_sor_source_grants_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_source_grants_source_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_source_grants_id_source_organization",
        ),
    )
    op.create_index(
        op.f("ix_sor_source_grants_agent_id"),
        "sor_source_grants",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_grants_created_at"),
        "sor_source_grants",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_grants_organization_id"),
        "sor_source_grants",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_grants_source_id"),
        "sor_source_grants",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_source_grants_ext_id_org_id",
        "sor_source_grants",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_source_grants_agent_source_active",
        "sor_source_grants",
        ["agent_id", "source_id"],
        unique=True,
        postgresql_where=sa.text("deleted = false"),
    )
    op.create_table(
        "sor_source_streams",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column(
            "strategy",
            postgresql.ENUM(
                "DELTA",
                "CURSOR",
                "UPDATED_AT",
                "FULL_RECONCILE",
                name="sor_change_strategy_enum",
            ),
            nullable=False,
        ),
        sa.Column("checkpoint", sa.Text(), nullable=True),
        sa.Column("lookback_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cursor_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "last_committed_source_boundary", sa.String(length=512), nullable=True
        ),
        sa.Column("schedule", sa.String(length=128), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(
                "ACTIVE", "PAUSED", "DEGRADED", name="sor_stream_state_enum"
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("records_added", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "records_updated", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_tombstoned", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_unchanged", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_rejected", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "checkpoint IS NULL OR octet_length(checkpoint) <= 1048576",
            name="ck_sor_source_streams_checkpoint_size",
        ),
        sa.CheckConstraint(
            "cursor_version > 0 AND lookback_seconds >= 0",
            name="ck_sor_source_streams_cursor_lookback",
        ),
        sa.CheckConstraint(
            "records_added >= 0 AND records_updated >= 0 AND records_tombstoned >= 0 AND records_unchanged >= 0 AND records_rejected >= 0",
            name="ck_sor_source_streams_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_source_streams_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_source_streams_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id", "vendor_object_key", name="uq_sor_source_streams_source_object"
        ),
    )
    op.create_index(
        op.f("ix_sor_source_streams_created_at"),
        "sor_source_streams",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sor_source_streams_due",
        "sor_source_streams",
        ["state", "next_due_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_streams_next_due_at"),
        "sor_source_streams",
        ["next_due_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_streams_organization_id"),
        "sor_source_streams",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_source_streams_source_id"),
        "sor_source_streams",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_source_streams_ext_id_org_id",
        "sor_source_streams",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_webhook_receipts",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("vendor_delivery_id", sa.String(length=512), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=256), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=True),
        sa.Column("vendor_external_id", sa.String(length=512), nullable=True),
        sa.Column("vendor_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "replay_detected", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "signals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(
                "PENDING",
                "PROCESSING",
                "SUCCEEDED",
                "FAILED",
                "EXPIRED",
                name="sor_webhook_receipt_state_enum",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("encrypted_raw_body", sa.Text(), nullable=True),
        sa.Column("raw_body_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("absurd_task_id", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "max_attempts", sa.SmallInteger(), server_default="3", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=128), nullable=True),
        sa.Column("safe_error_summary", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "fingerprint ~ '^[0-9a-f]{64}$' AND payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_webhook_receipts_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(signals) = 'array' AND octet_length(signals::text) <= 262144",
            name="ck_sor_webhook_receipts_signals",
        ),
        sa.CheckConstraint(
            "(encrypted_raw_body IS NULL AND raw_body_expires_at IS NULL) OR (encrypted_raw_body IS NOT NULL AND raw_body_expires_at IS NOT NULL)",
            name="ck_sor_webhook_receipts_raw_body_ttl",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0",
            name="ck_sor_webhook_receipts_attempts",
        ),
        sa.CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_webhook_receipts_error_size",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_webhook_receipts_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "absurd_task_id", name="uq_sor_webhook_receipts_absurd_task_id"
        ),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_webhook_receipts_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id",
            "fingerprint",
            name="uq_sor_webhook_receipts_source_fingerprint",
        ),
        sa.UniqueConstraint(
            "source_id",
            "vendor_delivery_id",
            name="uq_sor_webhook_receipts_source_delivery",
        ),
    )
    op.create_index(
        op.f("ix_sor_webhook_receipts_created_at"),
        "sor_webhook_receipts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_webhook_receipts_organization_id"),
        "sor_webhook_receipts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_webhook_receipts_raw_body_expires_at"),
        "sor_webhook_receipts",
        ["raw_body_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_webhook_receipts_source_id"),
        "sor_webhook_receipts",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_webhook_receipts_source_state",
        "sor_webhook_receipts",
        ["source_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_webhook_receipts_ext_id_org_id",
        "sor_webhook_receipts",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_agent_revision_source_grants",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_revision", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("source_grant_id", sa.UUID(), nullable=False),
        sa.Column("source_grant_revision", sa.Integer(), nullable=False),
        sa.Column(
            "access",
            postgresql.ENUM("READ", "READ_WRITE", name="sor_source_access_enum"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent_revision > 0 AND source_grant_revision > 0",
            name="ck_sor_agent_revision_grants_revisions_positive",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "agent_revision", "organization_id"],
            [
                "agent_definition_revisions.agent_id",
                "agent_definition_revisions.revision",
                "agent_definition_revisions.organization_id",
            ],
            name="fk_sor_agent_revision_grants_agent_revision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_grant_id", "source_id", "organization_id"],
            [
                "sor_source_grants.id",
                "sor_source_grants.source_id",
                "sor_source_grants.organization_id",
            ],
            name="fk_sor_agent_revision_grants_live_grant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "agent_revision",
            "source_id",
            name="uq_sor_agent_revision_grants_agent_revision_source",
        ),
    )
    op.create_index(
        op.f("ix_sor_agent_revision_source_grants_agent_id"),
        "sor_agent_revision_source_grants",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_agent_revision_source_grants_created_at"),
        "sor_agent_revision_source_grants",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_agent_revision_source_grants_organization_id"),
        "sor_agent_revision_source_grants",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_agent_revision_source_grants_source_grant_id"),
        "sor_agent_revision_source_grants",
        ["source_grant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_agent_revision_source_grants_source_id"),
        "sor_agent_revision_source_grants",
        ["source_id"],
        unique=False,
    )
    op.create_table(
        "sor_mapping_revisions",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_schema_revision_id", sa.UUID(), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(
                "DRAFT",
                "ACTIVE",
                "STALE",
                "INVALID",
                "SUPERSEDED",
                name="sor_mapping_state_enum",
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "projection_version", sa.Integer(), server_default="1", nullable=False
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'DRAFT' AND published_at IS NULL) OR (state <> 'DRAFT' AND published_at IS NOT NULL)",
            name="ck_sor_mapping_revisions_publication_state",
        ),
        sa.CheckConstraint(
            "revision > 0 AND projection_version > 0",
            name="ck_sor_mapping_revisions_revisions_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_mapping_revisions_source_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_schema_revision_id", "source_id", "organization_id"],
            [
                "sor_schema_revisions.id",
                "sor_schema_revisions.source_id",
                "sor_schema_revisions.organization_id",
            ],
            name="fk_sor_mapping_revisions_schema_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_mapping_revisions_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id", "revision", name="uq_sor_mapping_revisions_source_revision"
        ),
    )
    op.create_index(
        op.f("ix_sor_mapping_revisions_created_at"),
        "sor_mapping_revisions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_mapping_revisions_organization_id"),
        "sor_mapping_revisions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_mapping_revisions_source_id"),
        "sor_mapping_revisions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_mapping_revisions_source_schema_revision_id"),
        "sor_mapping_revisions",
        ["source_schema_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_mapping_revisions_state"),
        "sor_mapping_revisions",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_mapping_revisions_ext_id_org_id",
        "sor_mapping_revisions",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_mapping_revisions_active_source",
        "sor_mapping_revisions",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("state = 'ACTIVE' AND deleted = false"),
    )
    op.create_table(
        "sor_field_mappings",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("mapping_revision_id", sa.UUID(), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("vendor_field_key", sa.String(length=256), nullable=False),
        sa.Column("source_label", sa.String(length=256), nullable=False),
        sa.Column("source_data_type", sa.String(length=64), nullable=False),
        sa.Column("canonical_target_path", sa.String(length=320), nullable=True),
        sa.Column("custom_field_definition_id", sa.UUID(), nullable=True),
        sa.Column(
            "transform_kind",
            postgresql.ENUM(
                "DIRECT",
                "BOOLEAN",
                "DATE",
                "TIMESTAMP",
                "MONEY",
                "RICH_TEXT_TO_PLAIN_TEXT",
                "ENUM",
                "IDENTITY_REFERENCE",
                "ARRAY",
                name="sor_transform_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "transform_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "direction",
            postgresql.ENUM(
                "READ_ONLY",
                "READ_WRITE",
                "IGNORE",
                name="sor_field_mapping_direction_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "agent_visible", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "ui_default_column", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("nullable", sa.Boolean(), nullable=False),
        sa.Column(
            "enum_choices",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "sensitivity",
            postgresql.ENUM(
                "STANDARD", "PERSONAL", "SENSITIVE", name="sor_sensitivity_enum"
            ),
            nullable=False,
        ),
        sa.Column(
            "writable_capability", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "state",
            postgresql.ENUM(
                "ACTIVE", "INCOMPATIBLE", name="sor_field_mapping_state_enum"
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("incompatibility_reason", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(direction = 'IGNORE' AND canonical_target_path IS NULL AND custom_field_definition_id IS NULL) OR (direction <> 'IGNORE' AND ((canonical_target_path IS NOT NULL AND custom_field_definition_id IS NULL) OR (canonical_target_path IS NULL AND custom_field_definition_id IS NOT NULL)))",
            name="ck_sor_field_mappings_exact_target",
        ),
        sa.CheckConstraint(
            "(state = 'ACTIVE' AND incompatibility_reason IS NULL) OR (state = 'INCOMPATIBLE' AND incompatibility_reason IS NOT NULL)",
            name="ck_sor_field_mappings_compatibility_reason",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(enum_choices) = 'array' AND octet_length(enum_choices::text) <= 65536",
            name="ck_sor_field_mappings_enum_choices",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(transform_config) = 'object' AND octet_length(transform_config::text) <= 16384",
            name="ck_sor_field_mappings_transform_config",
        ),
        sa.ForeignKeyConstraint(
            ["custom_field_definition_id", "source_id", "organization_id"],
            [
                "sor_custom_field_definitions.id",
                "sor_custom_field_definitions.source_id",
                "sor_custom_field_definitions.organization_id",
            ],
            name="fk_sor_field_mappings_custom_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_field_mappings_revision_source_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "vendor_object_key",
            "vendor_field_key",
            name="uq_sor_field_mappings_revision_object_field",
        ),
    )
    op.create_index(
        op.f("ix_sor_field_mappings_created_at"),
        "sor_field_mappings",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_field_mappings_custom_field_definition_id"),
        "sor_field_mappings",
        ["custom_field_definition_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_field_mappings_mapping_revision_id"),
        "sor_field_mappings",
        ["mapping_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_field_mappings_organization_id"),
        "sor_field_mappings",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_field_mappings_source_id"),
        "sor_field_mappings",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_field_mappings_ext_id_org_id",
        "sor_field_mappings",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_records",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("vendor_external_id", sa.String(length=512), nullable=False),
        sa.Column("human_external_key", sa.String(length=320), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_revision", sa.String(length=512), nullable=True),
        sa.Column(
            "selected_raw_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "agent_visible_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("mapping_revision_id", sa.UUID(), nullable=False),
        sa.Column("mapping_projection_version", sa.Integer(), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_successful_sync_run_id", sa.UUID(), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_reason", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), server_default="", nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("agent_search_text", sa.Text(), server_default="", nullable=False),
        sa.Column("agent_search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(agent_visible_payload) = 'object' AND octet_length(agent_visible_payload::text) <= 1048576",
            name="ck_sor_records_agent_visible_payload",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_raw_payload) = 'object' AND octet_length(selected_raw_payload::text) <= 1048576",
            name="ck_sor_records_selected_payload",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'", name="ck_sor_records_payload_hash"
        ),
        sa.CheckConstraint(
            "(tombstoned_at IS NULL AND deletion_reason IS NULL) OR (tombstoned_at IS NOT NULL AND deletion_reason IS NOT NULL)",
            name="ck_sor_records_tombstone_reason",
        ),
        sa.CheckConstraint(
            "mapping_projection_version > 0",
            name="ck_sor_records_projection_version_positive",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_records_mapping_source_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id", "profile"],
            ["sor_sources.id", "sor_sources.organization_id", "sor_sources.profile"],
            name="fk_sor_records_source_organization_profile",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            "profile",
            "canonical_entity_kind",
            name="uq_sor_records_id_source_org_profile_entity",
        ),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_records_id_source_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_id",
            "vendor_object_key",
            "vendor_external_id",
            name="uq_sor_records_source_object_external_id",
        ),
    )
    op.create_index(
        "ix_sor_records_agent_search_vector",
        "sor_records",
        ["agent_search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        op.f("ix_sor_records_canonical_entity_kind"),
        "sor_records",
        ["canonical_entity_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_records_created_at"), "sor_records", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sor_records_human_external_key"),
        "sor_records",
        ["human_external_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_records_mapping_revision_id"),
        "sor_records",
        ["mapping_revision_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_records_org_profile_entity_projected_live",
        "sor_records",
        [
            "organization_id",
            "profile",
            "canonical_entity_kind",
            sa.literal_column("projected_at DESC NULLS LAST"),
            sa.literal_column("id DESC"),
        ],
        unique=False,
        postgresql_where=sa.text("tombstoned_at IS NULL AND deleted = false"),
    )
    op.create_index(
        "ix_sor_records_org_source_profile_entity_projected_live",
        "sor_records",
        [
            "organization_id",
            "source_id",
            "profile",
            "canonical_entity_kind",
            sa.literal_column("projected_at DESC NULLS LAST"),
            sa.literal_column("id DESC"),
        ],
        unique=False,
        postgresql_where=sa.text("tombstoned_at IS NULL AND deleted = false"),
    )
    op.create_index(
        op.f("ix_sor_records_organization_id"),
        "sor_records",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_records_profile"), "sor_records", ["profile"], unique=False
    )
    op.create_index(
        op.f("ix_sor_records_projected_at"),
        "sor_records",
        ["projected_at"],
        unique=False,
    )
    op.create_index(
        "ix_sor_records_search_vector",
        "sor_records",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        op.f("ix_sor_records_source_id"), "sor_records", ["source_id"], unique=False
    )
    op.create_index(
        op.f("ix_sor_records_source_updated_at"),
        "sor_records",
        ["source_updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_records_tombstoned_at"),
        "sor_records",
        ["tombstoned_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_records_ext_id_org_id",
        "sor_records",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_sync_runs",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("stream_id", sa.UUID(), nullable=True),
        sa.Column("mapping_revision_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "SCHEMA",
                "BOOTSTRAP",
                "INCREMENTAL",
                "WEBHOOK_REFETCH",
                "RECONCILIATION",
                "REPROJECTION",
                name="sor_sync_run_kind_enum",
            ),
            nullable=False,
        ),
        sa.Column(
            "state",
            postgresql.ENUM(
                "PENDING",
                "RUNNING",
                "WAITING",
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                name="sor_work_state_enum",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("absurd_task_id", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "max_attempts", sa.SmallInteger(), server_default="3", nullable=False
        ),
        sa.Column("checkpoint_before", sa.Text(), nullable=True),
        sa.Column("checkpoint_after", sa.Text(), nullable=True),
        sa.Column(
            "scan_complete",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(length=128), nullable=True),
        sa.Column("safe_error_summary", sa.Text(), nullable=True),
        sa.Column("records_added", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "records_updated", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_tombstoned", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_unchanged", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column(
            "records_rejected", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state IN ('PENDING', 'RUNNING', 'WAITING') AND finished_at IS NULL) OR (state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') AND finished_at IS NOT NULL)",
            name="ck_sor_sync_runs_terminal_time",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0", name="ck_sor_sync_runs_attempts"
        ),
        sa.CheckConstraint(
            "records_added >= 0 AND records_updated >= 0 AND records_tombstoned >= 0 AND records_unchanged >= 0 AND records_rejected >= 0",
            name="ck_sor_sync_runs_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_sync_runs_error_size",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "source_id", "organization_id"],
            [
                "sor_mapping_revisions.id",
                "sor_mapping_revisions.source_id",
                "sor_mapping_revisions.organization_id",
            ],
            name="fk_sor_sync_runs_mapping_source_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_sync_runs_source_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stream_id", "source_id", "organization_id"],
            [
                "sor_source_streams.id",
                "sor_source_streams.source_id",
                "sor_source_streams.organization_id",
            ],
            name="fk_sor_sync_runs_stream_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("absurd_task_id", name="uq_sor_sync_runs_absurd_task_id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_sync_runs_id_source_organization",
        ),
    )
    op.create_index(
        op.f("ix_sor_sync_runs_created_at"),
        "sor_sync_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sync_runs_mapping_revision_id"),
        "sor_sync_runs",
        ["mapping_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sync_runs_organization_id"),
        "sor_sync_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_sync_runs_source_created",
        "sor_sync_runs",
        ["source_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_sync_runs_source_id"), "sor_sync_runs", ["source_id"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sync_runs_state"), "sor_sync_runs", ["state"], unique=False
    )
    op.create_index(
        op.f("ix_sor_sync_runs_stream_id"), "sor_sync_runs", ["stream_id"], unique=False
    )
    op.create_index(
        "ix_unq_sor_sync_runs_ext_id_org_id",
        "sor_sync_runs",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_sync_runs_active_stream",
        "sor_sync_runs",
        ["stream_id"],
        unique=True,
        postgresql_where=sa.text(
            "stream_id IS NOT NULL AND deleted = false AND state IN ('PENDING', 'RUNNING', 'WAITING')"
        ),
    )
    op.create_table(
        "sor_commands",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("profile_tool", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_revision", sa.Integer(), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=320), nullable=False),
        sa.Column("source_grant_id", sa.UUID(), nullable=False),
        sa.Column("source_grant_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=320), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.Text(), nullable=False),
        sa.Column("target_record_id", sa.UUID(), nullable=True),
        sa.Column("expected_source_revision", sa.String(length=512), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(
                "PENDING",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "CONFLICT",
                "CANCELLED",
                name="sor_command_state_enum",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "safe_result",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("external_request_id", sa.String(length=512), nullable=True),
        sa.Column("source_revision_after", sa.String(length=512), nullable=True),
        sa.Column("mutation_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("absurd_task_id", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "max_attempts", sa.SmallInteger(), server_default="3", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_category", sa.String(length=128), nullable=True),
        sa.Column("safe_error_summary", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(state = 'SUCCEEDED' AND mutation_applied_at IS NOT NULL) OR (state IN ('CONFLICT', 'CANCELLED') AND mutation_applied_at IS NULL) OR state IN ('PENDING', 'RUNNING', 'FAILED')",
            name="ck_sor_commands_mutation_checkpoint",
        ),
        sa.CheckConstraint(
            "(state IN ('PENDING', 'RUNNING') AND finished_at IS NULL) OR (state IN ('SUCCEEDED', 'FAILED', 'CONFLICT', 'CANCELLED') AND finished_at IS NOT NULL)",
            name="ck_sor_commands_terminal_time",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_sor_commands_request_hash"
        ),
        sa.CheckConstraint(
            "safe_result IS NULL OR (jsonb_typeof(safe_result) = 'object' AND octet_length(safe_result::text) <= 65536)",
            name="ck_sor_commands_safe_result",
        ),
        sa.CheckConstraint(
            "agent_revision > 0 AND source_grant_revision > 0 AND attempts >= 0 AND max_attempts > 0",
            name="ck_sor_commands_revisions_attempts",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 320 AND length(tool_call_id) BETWEEN 1 AND 320",
            name="ck_sor_commands_identity_sizes",
        ),
        sa.CheckConstraint(
            "octet_length(request_payload) <= 1048576",
            name="ck_sor_commands_request_payload_size",
        ),
        sa.CheckConstraint(
            "safe_error_summary IS NULL OR octet_length(safe_error_summary) <= 8192",
            name="ck_sor_commands_error_size",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "agent_revision", "organization_id"],
            [
                "agent_definition_revisions.agent_id",
                "agent_definition_revisions.revision",
                "agent_definition_revisions.organization_id",
            ],
            name="fk_sor_commands_agent_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_sor_commands_agent_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_grant_id", "source_id", "organization_id"],
            [
                "sor_source_grants.id",
                "sor_source_grants.source_id",
                "sor_source_grants.organization_id",
            ],
            name="fk_sor_commands_source_grant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id", "profile"],
            ["sor_sources.id", "sor_sources.organization_id", "sor_sources.profile"],
            name="fk_sor_commands_source_organization_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_commands_target_record",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("absurd_task_id", name="uq_sor_commands_absurd_task_id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_commands_id_source_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_sor_commands_organization_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_sor_commands_agent_id"), "sor_commands", ["agent_id"], unique=False
    )
    op.create_index(
        "ix_sor_commands_agent_run",
        "sor_commands",
        ["agent_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_commands_agent_run_id"),
        "sor_commands",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_commands_created_at"), "sor_commands", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sor_commands_organization_id"),
        "sor_commands",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_commands_source_grant_id"),
        "sor_commands",
        ["source_grant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_commands_source_id"), "sor_commands", ["source_id"], unique=False
    )
    op.create_index(
        "ix_sor_commands_source_state",
        "sor_commands",
        ["source_id", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_commands_state"), "sor_commands", ["state"], unique=False
    )
    op.create_index(
        op.f("ix_sor_commands_target_record_id"),
        "sor_commands",
        ["target_record_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_commands_ext_id_org_id",
        "sor_commands",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_crm_activities",
        sa.Column("kind", sa.String(length=96), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_external_id", sa.String(length=512), nullable=True),
        sa.Column(
            "participant_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "related_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'activity'",
            name="ck_sor_crm_activities_entity_kind",
        ),
        sa.CheckConstraint("profile = 'crm'", name="ck_sor_crm_activities_profile"),
        sa.CheckConstraint(
            "cardinality(participant_external_ids) <= 10000 AND cardinality(related_external_ids) <= 10000",
            name="ck_sor_crm_activities_relationship_counts",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_crm_activities_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_crm_activities_record_id"),
    )
    op.create_index(
        op.f("ix_sor_crm_activities_created_at"),
        "sor_crm_activities",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_activities_organization_id"),
        "sor_crm_activities",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_activities_record_id"),
        "sor_crm_activities",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_activities_source_id"),
        "sor_crm_activities",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_activities_source_kind",
        "sor_crm_activities",
        ["source_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_activities_source_occurred",
        "sor_crm_activities",
        ["source_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_crm_activities_ext_id_org_id",
        "sor_crm_activities",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_crm_companies",
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=1024), nullable=True),
        sa.Column("industry", sa.String(length=320), nullable=True),
        sa.Column("owner_external_id", sa.String(length=512), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'company'", name="ck_sor_crm_companies_entity_kind"
        ),
        sa.CheckConstraint("profile = 'crm'", name="ck_sor_crm_companies_profile"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_crm_companies_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_crm_companies_record_id"),
    )
    op.create_index(
        op.f("ix_sor_crm_companies_created_at"),
        "sor_crm_companies",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_companies_organization_id"),
        "sor_crm_companies",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_companies_record_id"),
        "sor_crm_companies",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_companies_source_domain",
        "sor_crm_companies",
        ["source_id", "domain"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_companies_source_id"),
        "sor_crm_companies",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_companies_source_industry",
        "sor_crm_companies",
        ["source_id", "industry"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_companies_source_owner",
        "sor_crm_companies",
        ["source_id", "owner_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_crm_companies_ext_id_org_id",
        "sor_crm_companies",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_crm_contacts",
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.String(length=1024), nullable=True),
        sa.Column("primary_phone", sa.String(length=320), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("lifecycle_stage", sa.String(length=160), nullable=True),
        sa.Column("owner_external_id", sa.String(length=512), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'contact'", name="ck_sor_crm_contacts_entity_kind"
        ),
        sa.CheckConstraint("profile = 'crm'", name="ck_sor_crm_contacts_profile"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_crm_contacts_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_crm_contacts_record_id"),
    )
    op.create_index(
        op.f("ix_sor_crm_contacts_created_at"),
        "sor_crm_contacts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_contacts_organization_id"),
        "sor_crm_contacts",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_contacts_record_id"),
        "sor_crm_contacts",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_contacts_source_email",
        "sor_crm_contacts",
        ["source_id", "primary_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_contacts_source_id"),
        "sor_crm_contacts",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_contacts_source_lifecycle",
        "sor_crm_contacts",
        ["source_id", "lifecycle_stage"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_contacts_source_owner",
        "sor_crm_contacts",
        ["source_id", "owner_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_crm_contacts_ext_id_org_id",
        "sor_crm_contacts",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_crm_deals",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("pipeline_external_id", sa.String(length=512), nullable=True),
        sa.Column("stage_external_id", sa.String(length=512), nullable=True),
        sa.Column("native_stage", sa.String(length=320), nullable=True),
        sa.Column("normalized_state", sa.String(length=96), nullable=True),
        sa.Column("amount", sa.Numeric(precision=30, scale=8), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("probability", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("owner_external_id", sa.String(length=512), nullable=True),
        sa.Column(
            "contact_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "company_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'deal'", name="ck_sor_crm_deals_entity_kind"
        ),
        sa.CheckConstraint("profile = 'crm'", name="ck_sor_crm_deals_profile"),
        sa.CheckConstraint(
            "cardinality(contact_external_ids) <= 10000 AND cardinality(company_external_ids) <= 10000",
            name="ck_sor_crm_deals_relationship_counts",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_crm_deals_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_crm_deals_record_id"),
    )
    op.create_index(
        op.f("ix_sor_crm_deals_created_at"),
        "sor_crm_deals",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_deals_organization_id"),
        "sor_crm_deals",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_deals_record_id"), "sor_crm_deals", ["record_id"], unique=False
    )
    op.create_index(
        "ix_sor_crm_deals_source_close",
        "sor_crm_deals",
        ["source_id", "expected_close_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_crm_deals_source_id"), "sor_crm_deals", ["source_id"], unique=False
    )
    op.create_index(
        "ix_sor_crm_deals_source_owner",
        "sor_crm_deals",
        ["source_id", "owner_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_deals_source_stage",
        "sor_crm_deals",
        ["source_id", "stage_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_crm_deals_source_state",
        "sor_crm_deals",
        ["source_id", "normalized_state"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_crm_deals_ext_id_org_id",
        "sor_crm_deals",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_custom_field_values",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("field_definition_id", sa.UUID(), nullable=False),
        sa.Column(
            "value_type",
            postgresql.ENUM(
                "TEXT",
                "DECIMAL",
                "BOOLEAN",
                "DATE",
                "TIMESTAMP",
                "STRING_ARRAY",
                "REFERENCE",
                "BOUNDED_JSON",
                name="sor_custom_field_type_enum",
            ),
            nullable=False,
        ),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("decimal_value", sa.Numeric(precision=38, scale=12), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("date_value", sa.Date(), nullable=True),
        sa.Column("timestamp_value", sa.DateTime(timezone=True), nullable=True),
        sa.Column("string_array_value", sa.ARRAY(sa.String(length=512)), nullable=True),
        sa.Column("reference_record_id", sa.UUID(), nullable=True),
        sa.Column(
            "json_value",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(value_type = 'TEXT' AND text_value IS NOT NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'DECIMAL' AND text_value IS NULL AND decimal_value IS NOT NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'BOOLEAN' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NOT NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'DATE' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NOT NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'TIMESTAMP' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NOT NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'STRING_ARRAY' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NOT NULL AND reference_record_id IS NULL AND json_value IS NULL) OR (value_type = 'REFERENCE' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NOT NULL AND json_value IS NULL) OR (value_type = 'BOUNDED_JSON' AND text_value IS NULL AND decimal_value IS NULL AND boolean_value IS NULL AND date_value IS NULL AND timestamp_value IS NULL AND string_array_value IS NULL AND reference_record_id IS NULL AND json_value IS NOT NULL)",
            name="ck_sor_custom_field_values_exact_typed_value",
        ),
        sa.CheckConstraint(
            "json_value IS NULL OR octet_length(json_value::text) <= 16384",
            name="ck_sor_custom_field_values_json_size",
        ),
        sa.CheckConstraint(
            "string_array_value IS NULL OR cardinality(string_array_value) <= 128",
            name="ck_sor_custom_field_values_array_size",
        ),
        sa.CheckConstraint(
            "text_value IS NULL OR octet_length(text_value) <= 65536",
            name="ck_sor_custom_field_values_text_size",
        ),
        sa.ForeignKeyConstraint(
            ["field_definition_id", "source_id", "organization_id"],
            [
                "sor_custom_field_definitions.id",
                "sor_custom_field_definitions.source_id",
                "sor_custom_field_definitions.organization_id",
            ],
            name="fk_sor_custom_field_values_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_custom_field_values_record",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_custom_field_values_reference_record",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "record_id",
            "field_definition_id",
            name="uq_sor_custom_field_values_record_field",
        ),
    )
    op.create_index(
        "ix_sor_custom_field_values_boolean",
        "sor_custom_field_values",
        ["field_definition_id", "boolean_value"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_created_at"),
        "sor_custom_field_values",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_field_values_date",
        "sor_custom_field_values",
        ["field_definition_id", "date_value"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_field_values_decimal",
        "sor_custom_field_values",
        ["field_definition_id", "decimal_value"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_field_definition_id"),
        "sor_custom_field_values",
        ["field_definition_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_organization_id"),
        "sor_custom_field_values",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_record_id"),
        "sor_custom_field_values",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_reference_record_id"),
        "sor_custom_field_values",
        ["reference_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_custom_field_values_source_id"),
        "sor_custom_field_values",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_field_values_string_array",
        "sor_custom_field_values",
        ["string_array_value"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_sor_custom_field_values_text",
        "sor_custom_field_values",
        ["field_definition_id", "text_value"],
        unique=False,
    )
    op.create_index(
        "ix_sor_custom_field_values_timestamp",
        "sor_custom_field_values",
        ["field_definition_id", "timestamp_value"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_custom_field_values_ext_id_org_id",
        "sor_custom_field_values",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_attachments",
        sa.Column("document_external_id", sa.String(length=512), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=320), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_url_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'attachment'",
            name="ck_sor_knowledge_attachments_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_attachments_profile"
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_sor_knowledge_attachments_size",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_attachments_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_attachments_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_attachments_created_at"),
        "sor_knowledge_attachments",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_attachments_organization_id"),
        "sor_knowledge_attachments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_attachments_record_id"),
        "sor_knowledge_attachments",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_attachments_source_document",
        "sor_knowledge_attachments",
        ["source_id", "document_external_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_attachments_source_id"),
        "sor_knowledge_attachments",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_attachments_source_name",
        "sor_knowledge_attachments",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_attachments_ext_id_org_id",
        "sor_knowledge_attachments",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_authors",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("primary_email", sa.String(length=1024), nullable=True),
        sa.Column("kind", sa.String(length=96), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'author'",
            name="ck_sor_knowledge_authors_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_authors_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_authors_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_authors_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_authors_created_at"),
        "sor_knowledge_authors",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_authors_organization_id"),
        "sor_knowledge_authors",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_authors_record_id"),
        "sor_knowledge_authors",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_authors_source_email",
        "sor_knowledge_authors",
        ["source_id", "primary_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_authors_source_id"),
        "sor_knowledge_authors",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_authors_source_name",
        "sor_knowledge_authors",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_authors_ext_id_org_id",
        "sor_knowledge_authors",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_blocks",
        sa.Column("document_external_id", sa.String(length=512), nullable=False),
        sa.Column("parent_external_id", sa.String(length=512), nullable=True),
        sa.Column("kind", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column(
            "source_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("supported", sa.Boolean(), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'block'",
            name="ck_sor_knowledge_blocks_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_blocks_profile"
        ),
        sa.CheckConstraint("position >= 0", name="ck_sor_knowledge_blocks_position"),
        sa.CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_blocks_source_body",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_blocks_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_blocks_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_blocks_created_at"),
        "sor_knowledge_blocks",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_blocks_organization_id"),
        "sor_knowledge_blocks",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_blocks_record_id"),
        "sor_knowledge_blocks",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_blocks_source_document_position",
        "sor_knowledge_blocks",
        ["source_id", "document_external_id", "position"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_blocks_source_id"),
        "sor_knowledge_blocks",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_blocks_source_parent",
        "sor_knowledge_blocks",
        ["source_id", "parent_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_blocks_ext_id_org_id",
        "sor_knowledge_blocks",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_documents",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("space_external_id", sa.String(length=512), nullable=True),
        sa.Column("parent_external_id", sa.String(length=512), nullable=True),
        sa.Column(
            "path",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("source_format", sa.String(length=96), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column(
            "source_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=160), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=96), nullable=True),
        sa.Column("author_external_id", sa.String(length=512), nullable=True),
        sa.Column(
            "label_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "unsupported_blocks",
            sa.ARRAY(sa.String(length=160)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'document'",
            name="ck_sor_knowledge_documents_entity_kind",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sor_knowledge_documents_content_hash",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_documents_profile"
        ),
        sa.CheckConstraint(
            "cardinality(label_external_ids) <= 256",
            name="ck_sor_knowledge_documents_labels",
        ),
        sa.CheckConstraint(
            "cardinality(path) <= 128", name="ck_sor_knowledge_documents_path"
        ),
        sa.CheckConstraint(
            "cardinality(unsupported_blocks) <= 128",
            name="ck_sor_knowledge_documents_unsupported_blocks",
        ),
        sa.CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_documents_source_body",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_documents_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_documents_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_documents_created_at"),
        "sor_knowledge_documents",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_documents_organization_id"),
        "sor_knowledge_documents",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_documents_record_id"),
        "sor_knowledge_documents",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_documents_source_id"),
        "sor_knowledge_documents",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_documents_source_parent",
        "sor_knowledge_documents",
        ["source_id", "parent_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_documents_source_space",
        "sor_knowledge_documents",
        ["source_id", "space_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_documents_source_title",
        "sor_knowledge_documents",
        ["source_id", "title"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_documents_source_updated",
        "sor_knowledge_documents",
        ["source_id", "source_updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_documents_ext_id_org_id",
        "sor_knowledge_documents",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_properties",
        sa.Column("document_external_id", sa.String(length=512), nullable=False),
        sa.Column("property_key", sa.String(length=512), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=160), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'property'",
            name="ck_sor_knowledge_properties_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_properties_profile"
        ),
        sa.CheckConstraint(
            "octet_length(value::text) <= 1048576",
            name="ck_sor_knowledge_properties_value",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_properties_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_properties_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_properties_created_at"),
        "sor_knowledge_properties",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_properties_organization_id"),
        "sor_knowledge_properties",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_properties_record_id"),
        "sor_knowledge_properties",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_properties_source_document_key",
        "sor_knowledge_properties",
        ["source_id", "document_external_id", "property_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_properties_source_id"),
        "sor_knowledge_properties",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_properties_ext_id_org_id",
        "sor_knowledge_properties",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_spaces",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=96), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'space'",
            name="ck_sor_knowledge_spaces_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_spaces_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_spaces_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_spaces_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_spaces_created_at"),
        "sor_knowledge_spaces",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_spaces_organization_id"),
        "sor_knowledge_spaces",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_spaces_record_id"),
        "sor_knowledge_spaces",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_spaces_source_id"),
        "sor_knowledge_spaces",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_spaces_source_kind",
        "sor_knowledge_spaces",
        ["source_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_spaces_source_name",
        "sor_knowledge_spaces",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_spaces_ext_id_org_id",
        "sor_knowledge_spaces",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_knowledge_versions",
        sa.Column("document_external_id", sa.String(length=512), nullable=False),
        sa.Column("number", sa.String(length=160), nullable=False),
        sa.Column("author_external_id", sa.String(length=512), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source_format", sa.String(length=96), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column(
            "source_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'version'",
            name="ck_sor_knowledge_versions_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'knowledge'", name="ck_sor_knowledge_versions_profile"
        ),
        sa.CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_knowledge_versions_source_body",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_knowledge_versions_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_knowledge_versions_record_id"),
    )
    op.create_index(
        op.f("ix_sor_knowledge_versions_created_at"),
        "sor_knowledge_versions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_versions_organization_id"),
        "sor_knowledge_versions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_versions_record_id"),
        "sor_knowledge_versions",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_knowledge_versions_source_document_created",
        "sor_knowledge_versions",
        ["source_id", "document_external_id", "source_created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_knowledge_versions_source_id"),
        "sor_knowledge_versions",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_knowledge_versions_ext_id_org_id",
        "sor_knowledge_versions",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_record_relations",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("from_record_id", sa.UUID(), nullable=False),
        sa.Column("to_record_id", sa.UUID(), nullable=False),
        sa.Column("canonical_relation_kind", sa.String(length=96), nullable=False),
        sa.Column("native_relation_kind", sa.String(length=160), nullable=False),
        sa.Column("external_relation_id", sa.String(length=512), nullable=True),
        sa.Column("source_revision", sa.String(length=512), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_record_id <> to_record_id",
            name="ck_sor_record_relations_distinct_records",
        ),
        sa.ForeignKeyConstraint(
            ["from_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_record_relations_from_record",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_record_relations_source_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_record_relations_to_record",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "from_record_id",
            "to_record_id",
            "canonical_relation_kind",
            "native_relation_kind",
            name="uq_sor_record_relations_identity",
        ),
    )
    op.create_index(
        op.f("ix_sor_record_relations_created_at"),
        "sor_record_relations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_record_relations_from_record_id"),
        "sor_record_relations",
        ["from_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_record_relations_organization_id"),
        "sor_record_relations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_record_relations_source_id"),
        "sor_record_relations",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_record_relations_to_record_id"),
        "sor_record_relations",
        ["to_record_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_record_relations_ext_id_org_id",
        "sor_record_relations",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_index(
        "uq_sor_record_relations_external_id",
        "sor_record_relations",
        ["source_id", "external_relation_id"],
        unique=True,
        postgresql_where=sa.text("external_relation_id IS NOT NULL"),
    )
    op.create_table(
        "sor_support_agents",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("primary_email", sa.String(length=1024), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("assignable", sa.Boolean(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'agent'", name="ck_sor_support_agents_entity_kind"
        ),
        sa.CheckConstraint("profile = 'support'", name="ck_sor_support_agents_profile"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_agents_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_agents_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_agents_created_at"),
        "sor_support_agents",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_agents_organization_id"),
        "sor_support_agents",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_agents_record_id"),
        "sor_support_agents",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_agents_source_active",
        "sor_support_agents",
        ["source_id", "active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_agents_source_id"),
        "sor_support_agents",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_agents_source_name",
        "sor_support_agents",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_agents_ext_id_org_id",
        "sor_support_agents",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_attachments",
        sa.Column("ticket_external_id", sa.String(length=512), nullable=False),
        sa.Column("message_external_id", sa.String(length=512), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=320), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'attachment'",
            name="ck_sor_support_attachments_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_attachments_profile"
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_sor_support_attachments_size_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_attachments_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_attachments_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_attachments_created_at"),
        "sor_support_attachments",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_attachments_organization_id"),
        "sor_support_attachments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_attachments_record_id"),
        "sor_support_attachments",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_attachments_source_id"),
        "sor_support_attachments",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_attachments_source_message",
        "sor_support_attachments",
        ["source_id", "message_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_attachments_source_ticket",
        "sor_support_attachments",
        ["source_id", "ticket_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_attachments_ext_id_org_id",
        "sor_support_attachments",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_customers",
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.String(length=1024), nullable=True),
        sa.Column("primary_phone", sa.String(length=320), nullable=True),
        sa.Column("company_external_id", sa.String(length=512), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'customer'",
            name="ck_sor_support_customers_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_customers_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_customers_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_customers_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_customers_created_at"),
        "sor_support_customers",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_customers_organization_id"),
        "sor_support_customers",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_customers_record_id"),
        "sor_support_customers",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_customers_source_company",
        "sor_support_customers",
        ["source_id", "company_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_customers_source_email",
        "sor_support_customers",
        ["source_id", "primary_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_customers_source_id"),
        "sor_support_customers",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_customers_source_name",
        "sor_support_customers",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_customers_ext_id_org_id",
        "sor_support_customers",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_inboxes",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'inbox'", name="ck_sor_support_inboxes_entity_kind"
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_inboxes_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_inboxes_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_inboxes_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_inboxes_created_at"),
        "sor_support_inboxes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_inboxes_organization_id"),
        "sor_support_inboxes",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_inboxes_record_id"),
        "sor_support_inboxes",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_inboxes_source_id"),
        "sor_support_inboxes",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_inboxes_source_name",
        "sor_support_inboxes",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_inboxes_ext_id_org_id",
        "sor_support_inboxes",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_messages",
        sa.Column("ticket_external_id", sa.String(length=512), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=32), nullable=True),
        sa.Column("author_external_id", sa.String(length=512), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column(
            "source_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("body_format", sa.String(length=96), nullable=True),
        sa.Column(
            "attachment_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'message'",
            name="ck_sor_support_messages_entity_kind",
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('INBOUND', 'OUTBOUND', 'SYSTEM', 'UNKNOWN')",
            name="ck_sor_support_messages_direction",
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_messages_profile"
        ),
        sa.CheckConstraint(
            "visibility IN ('PUBLIC', 'PRIVATE')",
            name="ck_sor_support_messages_visibility",
        ),
        sa.CheckConstraint(
            "cardinality(attachment_external_ids) <= 256",
            name="ck_sor_support_messages_attachments",
        ),
        sa.CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_support_messages_source_body",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_messages_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_messages_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_messages_created_at"),
        "sor_support_messages",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_messages_organization_id"),
        "sor_support_messages",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_messages_record_id"),
        "sor_support_messages",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_messages_source_id"),
        "sor_support_messages",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_messages_source_ticket_created",
        "sor_support_messages",
        ["source_id", "ticket_external_id", "source_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_messages_ext_id_org_id",
        "sor_support_messages",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_queues",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'queue'", name="ck_sor_support_queues_entity_kind"
        ),
        sa.CheckConstraint("profile = 'support'", name="ck_sor_support_queues_profile"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_queues_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_queues_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_queues_created_at"),
        "sor_support_queues",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_queues_organization_id"),
        "sor_support_queues",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_queues_record_id"),
        "sor_support_queues",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_queues_source_id"),
        "sor_support_queues",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_queues_source_name",
        "sor_support_queues",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_queues_ext_id_org_id",
        "sor_support_queues",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_sla_metrics",
        sa.Column("ticket_external_id", sa.String(length=512), nullable=False),
        sa.Column("metric", sa.String(length=160), nullable=False),
        sa.Column("value", sa.Numeric(precision=24, scale=6), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("native_state", sa.String(length=160), nullable=True),
        sa.Column("normalized_state", sa.String(length=96), nullable=True),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("achieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'sla_metric'",
            name="ck_sor_support_sla_metrics_entity_kind",
        ),
        sa.CheckConstraint(
            "normalized_state IS NULL OR normalized_state IN ('ACTIVE', 'ACHIEVED', 'BREACHED', 'PAUSED', 'UNAVAILABLE')",
            name="ck_sor_support_sla_metrics_normalized_state",
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_sla_metrics_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_sla_metrics_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_sla_metrics_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_sla_metrics_created_at"),
        "sor_support_sla_metrics",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_sla_metrics_organization_id"),
        "sor_support_sla_metrics",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_sla_metrics_record_id"),
        "sor_support_sla_metrics",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_sla_metrics_source_id"),
        "sor_support_sla_metrics",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_sla_metrics_source_ticket",
        "sor_support_sla_metrics",
        ["source_id", "ticket_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_sla_metrics_ext_id_org_id",
        "sor_support_sla_metrics",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_tags",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'tag'", name="ck_sor_support_tags_entity_kind"
        ),
        sa.CheckConstraint("profile = 'support'", name="ck_sor_support_tags_profile"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_tags_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_tags_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_tags_created_at"),
        "sor_support_tags",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tags_organization_id"),
        "sor_support_tags",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tags_record_id"),
        "sor_support_tags",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tags_source_id"),
        "sor_support_tags",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_tags_source_name",
        "sor_support_tags",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_tags_ext_id_org_id",
        "sor_support_tags",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_support_tickets",
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("normalized_description", sa.Text(), nullable=True),
        sa.Column("requester_external_id", sa.String(length=512), nullable=True),
        sa.Column("assignee_external_id", sa.String(length=512), nullable=True),
        sa.Column("group_external_id", sa.String(length=512), nullable=True),
        sa.Column("inbox_external_id", sa.String(length=512), nullable=True),
        sa.Column("native_status", sa.String(length=160), nullable=True),
        sa.Column("normalized_status", sa.String(length=96), nullable=True),
        sa.Column("priority", sa.String(length=96), nullable=True),
        sa.Column("category", sa.String(length=160), nullable=True),
        sa.Column("channel", sa.String(length=160), nullable=True),
        sa.Column(
            "tag_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_state", sa.String(length=96), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'ticket'",
            name="ck_sor_support_tickets_entity_kind",
        ),
        sa.CheckConstraint(
            "normalized_status IS NULL OR normalized_status IN ('NEW', 'OPEN', 'PENDING', 'HOLD', 'RESOLVED', 'CLOSED')",
            name="ck_sor_support_tickets_normalized_status",
        ),
        sa.CheckConstraint(
            "profile = 'support'", name="ck_sor_support_tickets_profile"
        ),
        sa.CheckConstraint(
            "cardinality(tag_external_ids) <= 256", name="ck_sor_support_tickets_tags"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_support_tickets_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_support_tickets_record_id"),
    )
    op.create_index(
        op.f("ix_sor_support_tickets_created_at"),
        "sor_support_tickets",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tickets_organization_id"),
        "sor_support_tickets",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tickets_record_id"),
        "sor_support_tickets",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_tickets_source_assignee",
        "sor_support_tickets",
        ["source_id", "assignee_external_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_support_tickets_source_id"),
        "sor_support_tickets",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_tickets_source_requester",
        "sor_support_tickets",
        ["source_id", "requester_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_support_tickets_source_status",
        "sor_support_tickets",
        ["source_id", "normalized_status"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_support_tickets_ext_id_org_id",
        "sor_support_tickets",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_comments",
        sa.Column("issue_external_id", sa.String(length=512), nullable=False),
        sa.Column("author_external_id", sa.String(length=512), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column(
            "source_body",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'comment'",
            name="ck_sor_ticketing_comments_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_comments_profile"
        ),
        sa.CheckConstraint(
            "source_body IS NULL OR octet_length(source_body::text) <= 1048576",
            name="ck_sor_ticketing_comments_source_body",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_comments_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_comments_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_comments_created_at"),
        "sor_ticketing_comments",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_comments_organization_id"),
        "sor_ticketing_comments",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_comments_record_id"),
        "sor_ticketing_comments",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_comments_source_id"),
        "sor_ticketing_comments",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_comments_source_issue_created",
        "sor_ticketing_comments",
        ["source_id", "issue_external_id", "source_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_comments_ext_id_org_id",
        "sor_ticketing_comments",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_cycles",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("project_external_id", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'cycle'",
            name="ck_sor_ticketing_cycles_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_cycles_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_cycles_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_cycles_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_cycles_created_at"),
        "sor_ticketing_cycles",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_cycles_organization_id"),
        "sor_ticketing_cycles",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_cycles_record_id"),
        "sor_ticketing_cycles",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_cycles_source_dates",
        "sor_ticketing_cycles",
        ["source_id", "starts_at", "ends_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_cycles_source_id"),
        "sor_ticketing_cycles",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_cycles_source_name",
        "sor_ticketing_cycles",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_cycles_source_project",
        "sor_ticketing_cycles",
        ["source_id", "project_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_cycles_ext_id_org_id",
        "sor_ticketing_cycles",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_issue_relations",
        sa.Column("issue_vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("from_issue_external_id", sa.String(length=512), nullable=False),
        sa.Column("to_issue_external_id", sa.String(length=512), nullable=False),
        sa.Column("canonical_relation_kind", sa.String(length=96), nullable=False),
        sa.Column("native_relation_kind", sa.String(length=160), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'relation'",
            name="ck_sor_ticketing_issue_relations_entity_kind",
        ),
        sa.CheckConstraint(
            "canonical_relation_kind IN ('PARENT', 'CHILD', 'BLOCKS', 'BLOCKED_BY', 'RELATED', 'DUPLICATE')",
            name="ck_sor_ticketing_issue_relations_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_issue_relations_profile"
        ),
        sa.CheckConstraint(
            "from_issue_external_id <> to_issue_external_id",
            name="ck_sor_ticketing_issue_relations_distinct_issues",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_issue_relations_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "record_id", name="uq_sor_ticketing_issue_relations_record_id"
        ),
    )
    op.create_index(
        op.f("ix_sor_ticketing_issue_relations_created_at"),
        "sor_ticketing_issue_relations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issue_relations_organization_id"),
        "sor_ticketing_issue_relations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issue_relations_record_id"),
        "sor_ticketing_issue_relations",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issue_relations_source_from",
        "sor_ticketing_issue_relations",
        ["source_id", "issue_vendor_object_key", "from_issue_external_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issue_relations_source_id"),
        "sor_ticketing_issue_relations",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issue_relations_source_kind",
        "sor_ticketing_issue_relations",
        ["source_id", "canonical_relation_kind"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issue_relations_source_to",
        "sor_ticketing_issue_relations",
        ["source_id", "issue_vendor_object_key", "to_issue_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_issue_relations_ext_id_org_id",
        "sor_ticketing_issue_relations",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_issues",
        sa.Column("key", sa.String(length=320), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("normalized_description", sa.Text(), nullable=True),
        sa.Column(
            "source_description",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("issue_type", sa.String(length=160), nullable=True),
        sa.Column("native_status", sa.String(length=160), nullable=True),
        sa.Column("normalized_status", sa.String(length=96), nullable=True),
        sa.Column("priority", sa.String(length=96), nullable=True),
        sa.Column("project_external_id", sa.String(length=512), nullable=True),
        sa.Column("team_external_id", sa.String(length=512), nullable=True),
        sa.Column("assignee_external_id", sa.String(length=512), nullable=True),
        sa.Column("reporter_external_id", sa.String(length=512), nullable=True),
        sa.Column("estimate", sa.Numeric(precision=30, scale=8), nullable=True),
        sa.Column(
            "label_external_ids",
            sa.ARRAY(sa.String(length=512)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("parent_external_id", sa.String(length=512), nullable=True),
        sa.Column("cycle_external_id", sa.String(length=512), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'issue'",
            name="ck_sor_ticketing_issues_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_issues_profile"
        ),
        sa.CheckConstraint(
            "cardinality(label_external_ids) <= 256",
            name="ck_sor_ticketing_issues_labels",
        ),
        sa.CheckConstraint(
            "source_description IS NULL OR octet_length(source_description::text) <= 1048576",
            name="ck_sor_ticketing_issues_source_description",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_issues_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_issues_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_issues_created_at"),
        "sor_ticketing_issues",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issues_key"),
        "sor_ticketing_issues",
        ["key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issues_organization_id"),
        "sor_ticketing_issues",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issues_record_id"),
        "sor_ticketing_issues",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_issues_source_id"),
        "sor_ticketing_issues",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issues_source_project",
        "sor_ticketing_issues",
        ["source_id", "project_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issues_source_status",
        "sor_ticketing_issues",
        ["source_id", "normalized_status"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_issues_source_team",
        "sor_ticketing_issues",
        ["source_id", "team_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_issues_ext_id_org_id",
        "sor_ticketing_issues",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_labels",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=160), nullable=True),
        sa.Column("project_external_id", sa.String(length=512), nullable=True),
        sa.Column("parent_external_id", sa.String(length=512), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'label'",
            name="ck_sor_ticketing_labels_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_labels_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_labels_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_labels_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_labels_created_at"),
        "sor_ticketing_labels",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_labels_organization_id"),
        "sor_ticketing_labels",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_labels_record_id"),
        "sor_ticketing_labels",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_labels_source_id"),
        "sor_ticketing_labels",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_labels_source_name",
        "sor_ticketing_labels",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_labels_source_parent",
        "sor_ticketing_labels",
        ["source_id", "parent_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_labels_source_project",
        "sor_ticketing_labels",
        ["source_id", "project_external_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_labels_ext_id_org_id",
        "sor_ticketing_labels",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_projects",
        sa.Column("key", sa.String(length=320), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'project'",
            name="ck_sor_ticketing_projects_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_projects_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_projects_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_projects_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_projects_created_at"),
        "sor_ticketing_projects",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_projects_key"),
        "sor_ticketing_projects",
        ["key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_projects_organization_id"),
        "sor_ticketing_projects",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_projects_record_id"),
        "sor_ticketing_projects",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_projects_source_id"),
        "sor_ticketing_projects",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_projects_source_name",
        "sor_ticketing_projects",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_projects_ext_id_org_id",
        "sor_ticketing_projects",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_users",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("primary_email", sa.String(length=1024), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("assignable", sa.Boolean(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'user'", name="ck_sor_ticketing_users_entity_kind"
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_users_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_users_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id", name="uq_sor_ticketing_users_record_id"),
    )
    op.create_index(
        op.f("ix_sor_ticketing_users_created_at"),
        "sor_ticketing_users",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_users_organization_id"),
        "sor_ticketing_users",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_users_record_id"),
        "sor_ticketing_users",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_users_source_active",
        "sor_ticketing_users",
        ["source_id", "active"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_users_source_email",
        "sor_ticketing_users",
        ["source_id", "primary_email"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_users_source_id"),
        "sor_ticketing_users",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_users_source_name",
        "sor_ticketing_users",
        ["source_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_users_ext_id_org_id",
        "sor_ticketing_users",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_table(
        "sor_ticketing_workflow_states",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("native_category", sa.String(length=160), nullable=True),
        sa.Column("normalized_category", sa.String(length=96), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.ENUM(
                "crm", "ticketing", "support", "knowledge", name="sor_profile_enum"
            ),
            nullable=False,
        ),
        sa.Column("canonical_entity_kind", sa.String(length=96), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=320), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "canonical_entity_kind = 'workflow_state'",
            name="ck_sor_ticketing_workflow_states_entity_kind",
        ),
        sa.CheckConstraint(
            "profile = 'ticketing'", name="ck_sor_ticketing_workflow_states_profile"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization_organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
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
            name="fk_sor_ticketing_workflow_states_record_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "record_id", name="uq_sor_ticketing_workflow_states_record_id"
        ),
    )
    op.create_index(
        op.f("ix_sor_ticketing_workflow_states_created_at"),
        "sor_ticketing_workflow_states",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_workflow_states_organization_id"),
        "sor_ticketing_workflow_states",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_workflow_states_record_id"),
        "sor_ticketing_workflow_states",
        ["record_id"],
        unique=False,
    )
    op.create_index(
        "ix_sor_ticketing_workflow_states_source_category",
        "sor_ticketing_workflow_states",
        ["source_id", "normalized_category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sor_ticketing_workflow_states_source_id"),
        "sor_ticketing_workflow_states",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "ix_unq_sor_ticketing_workflow_states_ext_id_org_id",
        "sor_ticketing_workflow_states",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.create_foreign_key(
        "fk_sor_sources_active_schema_revision",
        "sor_sources",
        "sor_schema_revisions",
        ["active_schema_revision_id", "id", "organization_id"],
        ["id", "source_id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_sor_sources_active_mapping_revision",
        "sor_sources",
        "sor_mapping_revisions",
        ["active_mapping_revision_id", "id", "organization_id"],
        ["id", "source_id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_sor_records_last_sync_run",
        "sor_records",
        "sor_sync_runs",
        ["last_successful_sync_run_id", "source_id", "organization_id"],
        ["id", "source_id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.drop_index(
        op.f("ix_connection_connections_contact_id"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_created_at"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_credentials_expires_at"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_integration_id"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_last_refresh_failure_at"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_last_refresh_success_at"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_connection_connections_organization_id"),
        table_name="connection_connections",
    )
    op.drop_index(
        op.f("ix_unq_connection_connections_ext_id_org_id"),
        table_name="connection_connections",
    )
    op.drop_table("connection_connections")
    op.execute("DROP TYPE IF EXISTS connection_kind_enum")
    op.execute("DROP TYPE IF EXISTS connection_status_enum")
    op.add_column(
        "agent_runs",
        sa.Column("waiting_tool_owner_kind", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "agent_runs", sa.Column("waiting_tool_owner_id", sa.UUID(), nullable=True)
    )
    op.drop_constraint("ck_agent_runs_waiting_time", "agent_runs", type_="check")
    op.create_check_constraint(
        "ck_agent_runs_waiting_time",
        "agent_runs",
        "lifecycle NOT IN ('waiting_for_input', 'waiting_for_approval', "
        "'waiting_for_tool') OR waiting_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_agent_runs_tool_wait_identity",
        "agent_runs",
        "(lifecycle = 'waiting_for_tool' "
        "AND waiting_tool_owner_kind ~ '^[a-z][a-z0-9_]{0,63}$' "
        "AND waiting_tool_owner_id IS NOT NULL) OR "
        "(lifecycle <> 'waiting_for_tool' "
        "AND waiting_tool_owner_kind IS NULL "
        "AND waiting_tool_owner_id IS NULL)",
    )
    op.add_column(
        "connection_oauth_states",
        sa.Column(
            "external_connection_id",
            sa.UUID(),
            nullable=False,
            comment="Initiated external connection this OAuth flow will activate.",
        ),
    )
    op.add_column(
        "connection_oauth_states",
        sa.Column(
            "requested_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
            comment="Scopes requested by this exact authorization attempt.",
        ),
    )
    op.add_column(
        "connection_oauth_states",
        sa.Column(
            "expected_connection_revision",
            sa.Integer(),
            nullable=True,
            comment="Connection revision this callback may activate or renew.",
        ),
    )
    op.create_check_constraint(
        "ck_connection_oauth_states_expected_revision",
        "connection_oauth_states",
        "expected_connection_revision IS NULL OR expected_connection_revision >= 1",
    )
    op.create_check_constraint(
        "ck_connection_oauth_states_requested_scopes",
        "connection_oauth_states",
        "jsonb_typeof(requested_scopes) = 'array' "
        "AND octet_length(requested_scopes::text) <= 65536",
    )
    op.drop_index(
        op.f("ix_connection_oauth_states_integration_id"),
        table_name="connection_oauth_states",
    )
    op.create_index(
        op.f("ix_connection_oauth_states_external_connection_id"),
        "connection_oauth_states",
        ["external_connection_id"],
        unique=False,
    )
    op.drop_constraint(
        op.f("fk_connection_oauth_states_contact_organization"),
        "connection_oauth_states",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_connection_oauth_states_installation_organization"),
        "connection_oauth_states",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_connection_oauth_states_external_connection_organization",
        "connection_oauth_states",
        "connection_external_connections",
        ["external_connection_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.drop_column("connection_oauth_states", "integration_id")
    op.drop_column("connection_oauth_states", "contact_id")
    # ### end Alembic commands ###


def downgrade() -> None:
    """Keep the schema owned by the current eylo0001 compatibility baseline."""
