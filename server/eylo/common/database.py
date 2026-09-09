"""Async SQLAlchemy sessions, transactions, and post-commit event emission."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar

import sqlparse
from pydantic import BaseModel
from pydantic_core import to_jsonable_python
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, SessionTransaction

from eylo.common.config import settings
from eylo.events.py_events.emitter import emit_ephemeral

logger = logging.getLogger(__name__)

_POOL_RECYCLE_SECONDS = 3_600
_APPLICATION_NAME_SETTING = "application_name"
_AFTER_COMMIT_EVENT = "after_commit"
_AFTER_TRANSACTION_END_EVENT = "after_transaction_end"


def json_serializer(obj: object) -> str:
    """Serialize JSON-column values, including Pydantic and dataclass objects."""
    return json.dumps(to_jsonable_python(obj))


# Create async SQLAlchemy engine with custom JSON serializer and connection pooling
async_engine_instance = create_async_engine(
    settings.DATABASE_URL,
    json_serializer=json_serializer,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    # Connection lifecycle management (prevents stale connections and memory leaks)
    pool_recycle=_POOL_RECYCLE_SECONDS,  # Recycle connections after 1 hour (prevents stale connections)
    pool_reset_on_return="rollback",  # Reset connection state on return (ensures clean state)
    pool_use_lifo=True,  # Use LIFO for better memory locality (reduces working set)
    echo=False,  # Set to True for SQL query logging
)


# Event listener to log SQL shape without bound values.
@event.listens_for(async_engine_instance.sync_engine, "before_cursor_execute")
def _log_sql_queries(
    _connection: Connection,
    _cursor: object,
    statement: str,
    parameters: Sequence[object] | Mapping[str, object] | None,
    _context: ExecutionContext,
    executemany: bool,
) -> None:
    """Log SQL shape and parameter count, never bound credentials or user content."""
    if settings.DEBUG_QUERY_LOGGING:
        try:
            formatted_query = sqlparse.format(
                statement, reindent=True, keyword_case="upper", indent_width=2
            )
            logger.debug(
                "SQL query shape executemany=%s parameter_count=%d\n%s",
                executemany,
                len(parameters) if parameters else 0,
                formatted_query,
            )
        except Exception as error:
            logger.debug(
                "SQL query-shape formatting failed error_type=%s",
                type(error).__name__,
            )


async_session_factory = async_sessionmaker(
    async_engine_instance,
    expire_on_commit=False,
    close_resets_only=False,
)

_session: ContextVar[AsyncSession | None] = ContextVar("eylo_session", default=None)
_pending_events: ContextVar["_PostCommitEvents | None"] = ContextVar(
    "eylo_post_commit_events", default=None
)


class TransactionContextError(RuntimeError):
    """A caller requires a transaction but no owned scope is active."""


def _emit_events(events: Sequence[BaseModel]) -> None:
    """Publish detached notifications; listeners must acquire their own session."""
    session_token = _session.set(None)
    events_token = _pending_events.set(None)
    try:
        for value in events:
            logger.info("Emitting post-commit event name=%s", type(value).__name__)
            emit_ephemeral(value)
    finally:
        _pending_events.reset(events_token)
        _session.reset(session_token)


class _PostCommitEvents:
    """Tie event batches to native transaction/savepoint ownership."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._batches: dict[SessionTransaction, list[BaseModel]] = {}
        event.listen(session, _AFTER_COMMIT_EVENT, self._after_commit)
        event.listen(session, _AFTER_TRANSACTION_END_EVENT, self._after_transaction_end)

    def register(self, value: BaseModel) -> None:
        transaction = (
            self._session.get_nested_transaction() or self._session.get_transaction()
        )
        if transaction is None:
            transaction = self._session.begin()
        self._batches.setdefault(transaction, []).append(value)

    def _after_commit(self, session: Session) -> None:
        transaction = session.get_nested_transaction() or session.get_transaction()
        if transaction is None:
            return
        batch = self._batches.pop(transaction, [])
        if transaction.parent is not None:
            self._batches.setdefault(transaction.parent, []).extend(batch)
            return
        self._batches.clear()
        _emit_events(batch)

    def _after_transaction_end(
        self, _session: Session, transaction: SessionTransaction
    ) -> None:
        # Successful savepoints already transferred their batch in after_commit.
        # Any batch still owned by this closed scope was not committed.
        for owner in tuple(self._batches):
            if _transaction_descends_from(owner, transaction):
                del self._batches[owner]

    def close(self) -> None:
        self._batches.clear()
        event.remove(self._session, _AFTER_COMMIT_EVENT, self._after_commit)
        event.remove(
            self._session, _AFTER_TRANSACTION_END_EVENT, self._after_transaction_end
        )


def _transaction_descends_from(
    candidate: SessionTransaction, ancestor: SessionTransaction
) -> bool:
    current: SessionTransaction | None = candidate
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


@asynccontextmanager
async def start_transaction(
    *,
    connection_name: str | None = None,
    ro: bool = False,
) -> AsyncIterator[AsyncSession]:
    """Own one session, publish only committed events, and restore caller context.

    An explicit commit publishes its batch immediately. Rollback or abandoned
    savepoints discard only their batch. A failed commit propagates to the caller.
    """
    session = async_session_factory()
    pending_events = _PostCommitEvents(session.sync_session)
    events_token = _pending_events.set(pending_events)
    session_token = _session.set(session)
    try:
        if connection_name:
            await session.execute(
                select(
                    func.set_config(_APPLICATION_NAME_SETTING, connection_name, True)
                )
            )
        if ro:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        try:
            await session.close()
        finally:
            try:
                pending_events.close()
            finally:
                _session.reset(session_token)
                _pending_events.reset(events_token)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a session from the transaction context manager."""
    async with start_transaction() as session:
        yield session


def current_transaction() -> AsyncSession | None:
    """Return the caller-owned session without allocating or changing its scope."""
    return _session.get()


def get_transaction() -> AsyncSession:
    """Require the current caller-owned session; never allocate a fallback."""
    session = current_transaction()
    if session is None:
        raise TransactionContextError(
            "DB Session is not defined in the current context"
        )

    return session


P = ParamSpec("P")
R = TypeVar("R")


def with_transaction(
    connection_name: str | None = None, ro: bool = False
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Preserve the wrapped async signature while owning its DB transaction."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            async with start_transaction(connection_name=connection_name, ro=ro):
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def register_ephemeral_event_post_txn(event: BaseModel) -> None:
    """Queue a local event for this transaction; rollback never publishes it."""
    pending = _pending_events.get()
    if pending is None:
        raise TransactionContextError("Cannot register event: no active transaction")
    pending.register(event)


async def cleanup_database() -> None:
    """Clean up the database connection pool."""
    try:
        logger.info("Disposing database connection pool...")
        await async_engine_instance.dispose()
        logger.info("Database connection pool disposed successfully")
    except Exception as error:
        logger.error(
            "Database engine disposal failed error_type=%s",
            type(error).__name__,
        )
