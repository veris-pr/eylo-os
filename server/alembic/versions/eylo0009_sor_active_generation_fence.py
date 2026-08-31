"""Fence each SOR source to one active synchronization generation.

Revision ID: eylo0009
Revises: eylo0008
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0009"
down_revision: str | None = "eylo0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_GENERATION_PREDICATE = (
    "deleted = false AND state IN ('PENDING', 'RUNNING', 'WAITING')"
)


def upgrade() -> None:
    """Reject unsafe existing overlap, then enforce one active source DAG."""
    connection = op.get_bind()
    overlap = connection.execute(
        sa.text(
            """
            SELECT organization_id, source_id, count(*) AS generation_count
            FROM sor_sync_generations
            WHERE deleted = false
              AND state IN ('PENDING', 'RUNNING', 'WAITING')
            GROUP BY organization_id, source_id
            HAVING count(*) > 1
            ORDER BY organization_id, source_id
            LIMIT 1
            """
        )
    ).mappings().first()
    if overlap is not None:
        raise RuntimeError(
            "Cannot fence active SOR generations while a source has overlapping work: "
            f"organization_id={overlap['organization_id']} "
            f"source_id={overlap['source_id']} "
            f"generation_count={overlap['generation_count']}. "
            "Allow or cancel the active generations, then retry the migration."
        )
    op.create_index(
        "uq_sor_sync_generations_active_source",
        "sor_sync_generations",
        ["organization_id", "source_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_GENERATION_PREDICATE),
    )


def downgrade() -> None:
    """Remove the DB fence without changing existing synchronization data."""
    op.drop_index(
        "uq_sor_sync_generations_active_source",
        table_name="sor_sync_generations",
    )
