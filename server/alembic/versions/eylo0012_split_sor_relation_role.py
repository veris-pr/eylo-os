"""Separate platform relationship roles from vendor-native relation kinds.

Revision ID: eylo0012
Revises: eylo0011
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0012"
down_revision: str | None = "eylo0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLATFORM_ROLES = (
    "assignee",
    "author",
    "company",
    "contact",
    "cycle",
    "deal",
    "document",
    "inbox",
    "issue",
    "label",
    "message",
    "parent",
    "project",
    "queue",
    "reporter",
    "requester",
    "space",
    "tag",
    "team",
    "ticket",
)


def upgrade() -> None:
    """Preserve existing edges while giving each kind one unambiguous owner."""
    op.drop_constraint(
        "uq_sor_record_relations_identity",
        "sor_record_relations",
        type_="unique",
    )
    for table_name in ("sor_record_relations", "sor_relation_intents"):
        op.alter_column(
            table_name,
            "native_relation_kind",
            new_column_name="relationship_role",
            existing_type=sa.String(length=160),
            existing_nullable=False,
        )
        op.add_column(
            table_name,
            sa.Column(
                "vendor_relation_kind",
                sa.String(length=160),
                nullable=False,
                server_default="",
            ),
        )

    connection = op.get_bind()
    role_values = ", ".join(f"'{role}'" for role in _PLATFORM_ROLES)
    for table_name in ("sor_record_relations", "sor_relation_intents"):
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET vendor_relation_kind = relationship_role,
                    relationship_role = 'explicit_issue_relation'
                WHERE relationship_role NOT IN ({role_values})
                """
            )
        )

    op.create_unique_constraint(
        "uq_sor_record_relations_identity",
        "sor_record_relations",
        [
            "source_id",
            "from_record_id",
            "to_record_id",
            "canonical_relation_kind",
            "relationship_role",
            "vendor_relation_kind",
        ],
    )


def downgrade() -> None:
    """Recombine relation kinds into the legacy overloaded column."""
    op.drop_constraint(
        "uq_sor_record_relations_identity",
        "sor_record_relations",
        type_="unique",
    )
    connection = op.get_bind()
    for table_name in ("sor_record_relations", "sor_relation_intents"):
        connection.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET relationship_role = vendor_relation_kind
                WHERE relationship_role = 'explicit_issue_relation'
                  AND vendor_relation_kind <> ''
                """
            )
        )
        op.drop_column(table_name, "vendor_relation_kind")
        op.alter_column(
            table_name,
            "relationship_role",
            new_column_name="native_relation_kind",
            existing_type=sa.String(length=160),
            existing_nullable=False,
        )
    op.create_unique_constraint(
        "uq_sor_record_relations_identity",
        "sor_record_relations",
        [
            "source_id",
            "from_record_id",
            "to_record_id",
            "canonical_relation_kind",
            "native_relation_kind",
        ],
    )
