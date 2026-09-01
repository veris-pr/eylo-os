"""Represent unknown vendor states without expanding canonical vocabularies.

Revision ID: eylo0011
Revises: eylo0010
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0011"
down_revision: str | None = "eylo0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow the bounded UNKNOWN state already produced by SOR adapters."""
    op.drop_constraint(
        "ck_sor_support_tickets_normalized_status",
        "sor_support_tickets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sor_support_tickets_normalized_status",
        "sor_support_tickets",
        "normalized_status IS NULL OR normalized_status IN "
        "('NEW', 'OPEN', 'PENDING', 'HOLD', 'RESOLVED', 'CLOSED', 'UNKNOWN')",
    )
    op.drop_constraint(
        "ck_sor_support_sla_metrics_normalized_state",
        "sor_support_sla_metrics",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sor_support_sla_metrics_normalized_state",
        "sor_support_sla_metrics",
        "normalized_state IS NULL OR normalized_state IN "
        "('ACTIVE', 'ACHIEVED', 'BREACHED', 'PAUSED', 'UNAVAILABLE', 'UNKNOWN')",
    )


def downgrade() -> None:
    """Refuse to remove UNKNOWN while canonical rows still use it."""
    connection = op.get_bind()
    unknown = connection.execute(
        sa.text(
            """
            SELECT 'ticket' AS entity_kind, id
            FROM sor_support_tickets
            WHERE normalized_status = 'UNKNOWN'
            UNION ALL
            SELECT 'sla_metric' AS entity_kind, id
            FROM sor_support_sla_metrics
            WHERE normalized_state = 'UNKNOWN'
            LIMIT 1
            """
        )
    ).mappings().first()
    if unknown is not None:
        raise RuntimeError(
            "Cannot remove the SOR UNKNOWN state while canonical records use it: "
            f"entity_kind={unknown['entity_kind']} record_id={unknown['id']}."
        )
    op.drop_constraint(
        "ck_sor_support_sla_metrics_normalized_state",
        "sor_support_sla_metrics",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sor_support_sla_metrics_normalized_state",
        "sor_support_sla_metrics",
        "normalized_state IS NULL OR normalized_state IN "
        "('ACTIVE', 'ACHIEVED', 'BREACHED', 'PAUSED', 'UNAVAILABLE')",
    )
    op.drop_constraint(
        "ck_sor_support_tickets_normalized_status",
        "sor_support_tickets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_sor_support_tickets_normalized_status",
        "sor_support_tickets",
        "normalized_status IS NULL OR normalized_status IN "
        "('NEW', 'OPEN', 'PENDING', 'HOLD', 'RESOLVED', 'CLOSED')",
    )
