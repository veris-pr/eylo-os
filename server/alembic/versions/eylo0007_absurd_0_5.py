"""Upgrade the embedded Absurd schema from 0.4.0 to 0.5.0.

Revision ID: eylo0007
Revises: eylo0006
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "eylo0007"
down_revision: str | None = "eylo0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Use PostgreSQL's built-in random UUID source and mark schema 0.5.0."""
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION absurd.portable_uuidv7()
          RETURNS uuid
          LANGUAGE plpgsql
          VOLATILE
        AS $$
        DECLARE
          ts_ms bigint;
          b bytea;
          rnd bytea;
          i int;
        BEGIN
          IF to_regprocedure('pg_catalog.uuidv7()') IS NOT NULL THEN
            RETURN pg_catalog.uuidv7();
          END IF;
          ts_ms := floor(extract(epoch FROM absurd.current_time()) * 1000)::bigint;
          rnd := uuid_send(pg_catalog.gen_random_uuid());
          b := repeat(E'\\000', 16)::bytea;
          FOR i IN 0..5 LOOP
            b := set_byte(b, i, ((ts_ms >> ((5 - i) * 8)) & 255)::int);
          END LOOP;
          FOR i IN 6..15 LOOP
            b := set_byte(b, i, get_byte(rnd, i));
          END LOOP;
          b := set_byte(b, 6, ((get_byte(b, 6) & 15) | (7 << 4)));
          b := set_byte(b, 8, ((get_byte(b, 8) & 63) | 128));
          RETURN encode(b, 'hex')::uuid;
        END;
        $$;
        """
    )
    _set_absurd_schema_version("0.5.0")


def downgrade() -> None:
    """Restore Absurd 0.4.0 UUID generation and schema version."""
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION absurd.portable_uuidv7()
          RETURNS uuid
          LANGUAGE plpgsql
          VOLATILE
        AS $$
        DECLARE
          v_server_num integer := current_setting('server_version_num')::int;
          ts_ms bigint;
          b bytea;
          rnd bytea;
          i int;
        BEGIN
          IF v_server_num >= 180000 THEN
            RETURN uuidv7();
          END IF;
          ts_ms := floor(extract(epoch FROM absurd.current_time()) * 1000)::bigint;
          rnd := uuid_send(uuid_generate_v4());
          b := repeat(E'\\000', 16)::bytea;
          FOR i IN 0..5 LOOP
            b := set_byte(b, i, ((ts_ms >> ((5 - i) * 8)) & 255)::int);
          END LOOP;
          FOR i IN 6..15 LOOP
            b := set_byte(b, i, get_byte(rnd, i));
          END LOOP;
          b := set_byte(b, 6, ((get_byte(b, 6) & 15) | (7 << 4)));
          b := set_byte(b, 8, ((get_byte(b, 8) & 63) | 128));
          RETURN encode(b, 'hex')::uuid;
        END;
        $$;
        """
    )
    _set_absurd_schema_version("0.4.0")


def _set_absurd_schema_version(version: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION absurd.get_schema_version()
          RETURNS text
          LANGUAGE sql
        AS $$
          SELECT '{version}'::text;
        $$;
        """
    )
