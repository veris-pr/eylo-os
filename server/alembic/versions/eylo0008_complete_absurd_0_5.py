"""Complete the embedded Absurd 0.5.0 schema migration.

Revision ID: eylo0008
Revises: eylo0007
Create Date: 2026-08-27
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "eylo0008"
down_revision: str | None = "eylo0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VENDOR_DIRECTORY = Path(__file__).resolve().parents[1] / "vendor"
_ABSURD_0_4_SCHEMA_PATH = _VENDOR_DIRECTORY / "absurd-0.4.0.sql"
_ABSURD_0_5_MIGRATION_PATH = (
    _VENDOR_DIRECTORY / "absurd-0.4.0-0.5.0.sql"
)
_ABSURD_0_4_FUNCTIONS = (
    "portable_uuidv7",
    "spawn_task",
    "fail_run",
    "get_schema_version",
)


def upgrade() -> None:
    """Apply the exact upstream Absurd 0.4.0 to 0.5.0 migration."""
    _execute_sql(_ABSURD_0_5_MIGRATION_PATH.read_text(encoding="utf-8"))


def downgrade() -> None:
    """Restore the frozen Absurd 0.4.0 functions required by eylo0007."""
    statements = ['CREATE EXTENSION IF NOT EXISTS "uuid-ossp";']
    statements.extend(
        _load_absurd_0_4_function(function_name)
        for function_name in _ABSURD_0_4_FUNCTIONS
    )
    _execute_sql("\n\n".join(statements))


def _load_absurd_0_4_function(function_name: str) -> str:
    schema_sql = _ABSURD_0_4_SCHEMA_PATH.read_text(encoding="utf-8")
    markers = (
        f"create function absurd.{function_name} (",
        f"create or replace function absurd.{function_name} (",
    )
    start = next(
        (schema_sql.find(marker) for marker in markers if marker in schema_sql),
        -1,
    )
    if start < 0:
        raise RuntimeError(
            f"Absurd 0.4.0 function {function_name!r} is missing from the baseline."
        )
    terminator = "\n$$;"
    end = schema_sql.find(terminator, start)
    if end < 0:
        raise RuntimeError(
            f"Absurd 0.4.0 function {function_name!r} has no SQL terminator."
        )
    statement = schema_sql[start : end + len(terminator)]
    if statement.startswith("create function"):
        statement = statement.replace(
            "create function",
            "create or replace function",
            1,
        )
    return statement


def _execute_sql(schema_sql: str) -> None:
    adapted_connection = op.get_bind().connection.dbapi_connection
    adapted_connection.run_async(lambda connection: connection.execute(schema_sql))
