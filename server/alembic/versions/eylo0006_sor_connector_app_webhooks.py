"""Move app-owned SOR webhook authority onto OAuth connectors.

Revision ID: eylo0006
Revises: eylo0005
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "eylo0006"
down_revision: str | None = "eylo0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sor_connectors",
        sa.Column("webhook_endpoint_key", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sor_connectors",
        sa.Column(
            "webhook_signing_secret",
            sa.Text(),
            nullable=True,
            comment=(
                "Encrypted app webhook signing secret; never returned by an API read."
            ),
        ),
    )
    op.add_column(
        "sor_connectors",
        sa.Column(
            "webhook_signing_secret_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "sor_connectors",
        sa.Column("webhook_authorized_connection_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sor_connectors",
        sa.Column("vendor_account_external_id", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "sor_connectors",
        sa.Column("vendor_account_display_name", sa.String(length=512), nullable=True),
    )
    op.execute(
        "UPDATE sor_connectors SET webhook_endpoint_key = gen_random_uuid() "
        "WHERE vendor_key = 'linear' AND deleted = false"
    )
    op.create_check_constraint(
        "ck_sor_connectors_webhook_signing_secret_revision",
        "sor_connectors",
        "(webhook_signing_secret IS NULL AND webhook_signing_secret_revision = 0) "
        "OR (webhook_signing_secret IS NOT NULL "
        "AND webhook_signing_secret_revision > 0)",
    )
    op.create_check_constraint(
        "ck_sor_connectors_webhook_authorized_revision_positive",
        "sor_connectors",
        "webhook_authorized_connection_revision IS NULL "
        "OR webhook_authorized_connection_revision > 0",
    )
    op.create_index(
        "uq_sor_connectors_webhook_endpoint_key_active",
        "sor_connectors",
        ["webhook_endpoint_key"],
        unique=True,
        postgresql_where=sa.text(
            "webhook_endpoint_key IS NOT NULL AND deleted = false"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_sor_connectors_webhook_endpoint_key_active",
        table_name="sor_connectors",
    )
    op.drop_constraint(
        "ck_sor_connectors_webhook_authorized_revision_positive",
        "sor_connectors",
        type_="check",
    )
    op.drop_constraint(
        "ck_sor_connectors_webhook_signing_secret_revision",
        "sor_connectors",
        type_="check",
    )
    op.drop_column("sor_connectors", "vendor_account_display_name")
    op.drop_column("sor_connectors", "vendor_account_external_id")
    op.drop_column("sor_connectors", "webhook_authorized_connection_revision")
    op.drop_column("sor_connectors", "webhook_signing_secret_revision")
    op.drop_column("sor_connectors", "webhook_signing_secret")
    op.drop_column("sor_connectors", "webhook_endpoint_key")
