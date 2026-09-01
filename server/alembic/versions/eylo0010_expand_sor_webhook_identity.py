"""Allow one managed SOR subscription to identify multiple vendor hooks.

Revision ID: eylo0010
Revises: eylo0009
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "eylo0010"
down_revision: str | None = "eylo0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store bounded composite identities for per-repository webhooks."""
    op.alter_column(
        "sor_sources",
        "webhook_subscription_id",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Refuse lossy downgrade when a composite identity exceeds 512 chars."""
    connection = op.get_bind()
    oversized = connection.execute(
        sa.text(
            """
            SELECT id
            FROM sor_sources
            WHERE length(webhook_subscription_id) > 512
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if oversized is not None:
        raise RuntimeError(
            "Cannot narrow SOR webhook subscription identities while an existing "
            f"source exceeds 512 characters: source_id={oversized}."
        )
    op.alter_column(
        "sor_sources",
        "webhook_subscription_id",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
