"""Make SOR source creation idempotent per onboarding attempt.

Revision ID: eylo0003
Revises: eylo0002
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0003"
down_revision: str | None = "eylo0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill existing sources, then enforce one source per attempt and tenant."""
    op.add_column(
        "sor_sources",
        sa.Column("onboarding_attempt_id", sa.UUID(), nullable=True),
    )
    op.execute(
        "UPDATE sor_sources SET onboarding_attempt_id = id "
        "WHERE onboarding_attempt_id IS NULL"
    )
    op.alter_column(
        "sor_sources",
        "onboarding_attempt_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_sor_sources_organization_onboarding_attempt",
        "sor_sources",
        ["organization_id", "onboarding_attempt_id"],
    )


def downgrade() -> None:
    """Remove source-attempt idempotency without deleting source data."""
    op.drop_constraint(
        "uq_sor_sources_organization_onboarding_attempt",
        "sor_sources",
        type_="unique",
    )
    op.drop_column("sor_sources", "onboarding_attempt_id")
