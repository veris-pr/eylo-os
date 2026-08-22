"""Add SOR sync generations and durable relationship intents.

Revision ID: eylo0004
Revises: eylo0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "eylo0004"
down_revision: str | None = "eylo0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve existing runs while introducing source-level orchestration."""
    relation_state = postgresql.ENUM(
        "PENDING",
        "RESOLVED",
        "TOMBSTONED",
        name="sor_relation_intent_state_enum",
    )
    relation_state.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "sor_source_streams",
        sa.Column(
            "depends_on",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "sor_source_streams",
        sa.Column(
            "relationship_targets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_sor_source_streams_dependencies",
        "sor_source_streams",
        "jsonb_typeof(depends_on) = 'array' "
        "AND octet_length(depends_on::text) <= 65536",
    )
    op.create_check_constraint(
        "ck_sor_source_streams_relationship_targets",
        "sor_source_streams",
        "jsonb_typeof(relationship_targets) = 'object' "
        "AND octet_length(relationship_targets::text) <= 65536",
    )

    op.create_table(
        "sor_sync_generations",
        sa.Column("source_id", sa.UUID(), nullable=False),
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
                create_type=False,
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
                create_type=False,
            ),
            server_default="PENDING",
            nullable=False,
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
            "(state IN ('PENDING', 'RUNNING', 'WAITING') "
            "AND finished_at IS NULL) OR "
            "(state IN ('SUCCEEDED', 'FAILED', 'CANCELLED') "
            "AND finished_at IS NOT NULL)",
            name="ck_sor_sync_generations_terminal_time",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization_organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_sync_generations_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_sync_generations_id_source_organization",
        ),
    )
    op.create_index(
        op.f("ix_sor_sync_generations_created_at"),
        "sor_sync_generations",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_sor_sync_generations_organization_id"),
        "sor_sync_generations",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_sor_sync_generations_source_id"),
        "sor_sync_generations",
        ["source_id"],
    )
    op.create_index(
        "ix_sor_sync_generations_source_created",
        "sor_sync_generations",
        ["source_id", "created_at"],
    )
    op.create_index(
        "ix_sor_sync_generations_org_state",
        "sor_sync_generations",
        ["organization_id", "state"],
    )
    op.create_index(
        op.f("ix_sor_sync_generations_state"),
        "sor_sync_generations",
        ["state"],
    )
    op.create_index(
        "ix_unq_sor_sync_generations_ext_id_org_id",
        "sor_sync_generations",
        ["external_id", "organization_id"],
        unique=True,
    )

    op.add_column(
        "sor_sync_runs",
        sa.Column("generation_id", sa.UUID(), nullable=True),
    )
    op.execute(
        """
        INSERT INTO sor_sync_generations (
            id, source_id, kind, state, started_at, finished_at,
            safe_error_code, safe_error_summary, organization_id, external_id,
            deleted, created_at, updated_at
        )
        SELECT
            id, source_id, kind, state, started_at, finished_at,
            safe_error_code, safe_error_summary, organization_id, NULL,
            deleted, created_at, updated_at
        FROM sor_sync_runs
        """
    )
    op.execute("UPDATE sor_sync_runs SET generation_id = id")
    op.alter_column(
        "sor_sync_runs",
        "generation_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_sor_sync_runs_generation_source_organization",
        "sor_sync_runs",
        "sor_sync_generations",
        ["generation_id", "source_id", "organization_id"],
        ["id", "source_id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_sor_sync_runs_generation_id"),
        "sor_sync_runs",
        ["generation_id"],
    )

    op.create_table(
        "sor_relation_intents",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("origin_record_id", sa.UUID(), nullable=False),
        sa.Column("from_vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("from_vendor_external_id", sa.String(length=512), nullable=False),
        sa.Column("to_vendor_object_key", sa.String(length=160), nullable=False),
        sa.Column("to_vendor_external_id", sa.String(length=512), nullable=False),
        sa.Column("canonical_relation_kind", sa.String(length=96), nullable=False),
        sa.Column("native_relation_kind", sa.String(length=160), nullable=False),
        sa.Column("external_relation_id", sa.String(length=512), nullable=False),
        sa.Column("source_revision", sa.String(length=512), nullable=True),
        sa.Column(
            "state",
            postgresql.ENUM(
                "PENDING",
                "RESOLVED",
                "TOMBSTONED",
                name="sor_relation_intent_state_enum",
                create_type=False,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "resolution_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
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
            "length(btrim(from_vendor_object_key)) > 0 "
            "AND length(btrim(from_vendor_external_id)) > 0 "
            "AND length(btrim(to_vendor_object_key)) > 0 "
            "AND length(btrim(to_vendor_external_id)) > 0",
            name="ck_sor_relation_intents_endpoint_identity",
        ),
        sa.CheckConstraint(
            "from_vendor_object_key <> to_vendor_object_key "
            "OR from_vendor_external_id <> to_vendor_external_id",
            name="ck_sor_relation_intents_distinct_endpoints",
        ),
        sa.CheckConstraint(
            "resolution_attempts >= 0",
            name="ck_sor_relation_intents_attempts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization_organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_record_id", "source_id", "organization_id"],
            ["sor_records.id", "sor_records.source_id", "sor_records.organization_id"],
            name="fk_sor_relation_intents_origin_record",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["sor_sources.id", "sor_sources.organization_id"],
            name="fk_sor_relation_intents_source_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "organization_id",
            name="uq_sor_relation_intents_id_source_organization",
        ),
        sa.UniqueConstraint(
            "source_id",
            "external_relation_id",
            name="uq_sor_relation_intents_source_external_id",
        ),
    )
    for column in (
        "created_at",
        "organization_id",
        "origin_record_id",
        "source_id",
        "state",
    ):
        op.create_index(
            op.f(f"ix_sor_relation_intents_{column}"),
            "sor_relation_intents",
            [column],
        )
    op.create_index(
        "ix_sor_relation_intents_source_state",
        "sor_relation_intents",
        ["source_id", "state", "updated_at"],
    )
    op.create_index(
        "ix_sor_relation_intents_from_endpoint",
        "sor_relation_intents",
        ["source_id", "from_vendor_object_key", "from_vendor_external_id"],
    )
    op.create_index(
        "ix_sor_relation_intents_to_endpoint",
        "sor_relation_intents",
        ["source_id", "to_vendor_object_key", "to_vendor_external_id"],
    )
    op.create_index(
        "ix_unq_sor_relation_intents_ext_id_org_id",
        "sor_relation_intents",
        ["external_id", "organization_id"],
        unique=True,
    )
    op.execute(
        """
        INSERT INTO sor_relation_intents (
            source_id, origin_record_id,
            from_vendor_object_key, from_vendor_external_id,
            to_vendor_object_key, to_vendor_external_id,
            canonical_relation_kind, native_relation_kind,
            external_relation_id, source_revision, state,
            resolution_attempts, last_attempt_at, last_error_code, tombstoned_at,
            organization_id, external_id, id, deleted, created_at, updated_at
        )
        SELECT
            relation.source_id, relation.from_record_id,
            from_record.vendor_object_key, from_record.vendor_external_id,
            to_record.vendor_object_key, to_record.vendor_external_id,
            relation.canonical_relation_kind, relation.native_relation_kind,
            relation.external_relation_id, relation.source_revision,
            CASE
                WHEN relation.tombstoned_at IS NULL THEN 'RESOLVED'
                ELSE 'TOMBSTONED'
            END::sor_relation_intent_state_enum,
            0, NULL, NULL, relation.tombstoned_at,
            relation.organization_id, gen_random_uuid()::text,
            gen_random_uuid(), false, relation.created_at, relation.updated_at
        FROM sor_record_relations AS relation
        JOIN sor_records AS from_record
          ON from_record.id = relation.from_record_id
         AND from_record.source_id = relation.source_id
         AND from_record.organization_id = relation.organization_id
        JOIN sor_records AS to_record
          ON to_record.id = relation.to_record_id
         AND to_record.source_id = relation.source_id
         AND to_record.organization_id = relation.organization_id
        WHERE relation.deleted = false
          AND relation.external_relation_id IS NOT NULL
        ON CONFLICT (source_id, external_relation_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """Remove orchestration state after preserving pre-existing sync runs."""
    op.drop_index(
        "ix_unq_sor_relation_intents_ext_id_org_id",
        table_name="sor_relation_intents",
    )
    op.drop_index(
        "ix_sor_relation_intents_to_endpoint",
        table_name="sor_relation_intents",
    )
    op.drop_index(
        "ix_sor_relation_intents_from_endpoint",
        table_name="sor_relation_intents",
    )
    op.drop_index(
        "ix_sor_relation_intents_source_state",
        table_name="sor_relation_intents",
    )
    for column in (
        "state",
        "source_id",
        "origin_record_id",
        "organization_id",
        "created_at",
    ):
        op.drop_index(
            op.f(f"ix_sor_relation_intents_{column}"),
            table_name="sor_relation_intents",
        )
    op.drop_table("sor_relation_intents")
    postgresql.ENUM(
        name="sor_relation_intent_state_enum"
    ).drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        op.f("ix_sor_sync_runs_generation_id"),
        table_name="sor_sync_runs",
    )
    op.drop_constraint(
        "fk_sor_sync_runs_generation_source_organization",
        "sor_sync_runs",
        type_="foreignkey",
    )
    op.drop_column("sor_sync_runs", "generation_id")
    op.drop_index(
        "ix_sor_sync_generations_org_state",
        table_name="sor_sync_generations",
    )
    op.drop_index(
        "ix_unq_sor_sync_generations_ext_id_org_id",
        table_name="sor_sync_generations",
    )
    op.drop_index(
        op.f("ix_sor_sync_generations_state"),
        table_name="sor_sync_generations",
    )
    op.drop_index(
        "ix_sor_sync_generations_source_created",
        table_name="sor_sync_generations",
    )
    op.drop_index(
        op.f("ix_sor_sync_generations_source_id"),
        table_name="sor_sync_generations",
    )
    op.drop_index(
        op.f("ix_sor_sync_generations_organization_id"),
        table_name="sor_sync_generations",
    )
    op.drop_index(
        op.f("ix_sor_sync_generations_created_at"),
        table_name="sor_sync_generations",
    )
    op.drop_table("sor_sync_generations")

    op.drop_constraint(
        "ck_sor_source_streams_relationship_targets",
        "sor_source_streams",
        type_="check",
    )
    op.drop_constraint(
        "ck_sor_source_streams_dependencies",
        "sor_source_streams",
        type_="check",
    )
    op.drop_column("sor_source_streams", "relationship_targets")
    op.drop_column("sor_source_streams", "depends_on")
