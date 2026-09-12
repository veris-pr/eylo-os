"""Product lifecycle projected from execution by an exact Absurd task."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID as UUIDValue

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

DEFAULT_MAX_ATTEMPTS = 3
# Keep copied mixin columns after the dynamically declared state column.
_AFTER_DYNAMIC_STATE = 1


class DurableState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset(
    {DurableState.SUCCEEDED, DurableState.FAILED, DurableState.CANCELLED}
)


class BoundWorkRow(Protocol):
    """ORM fields required by lifecycle operations; defines no database columns."""

    id: Mapped[UUIDValue]
    organization_id: Mapped[UUIDValue]
    deleted: Mapped[bool]
    created_at: Mapped[datetime]
    state: Mapped[DurableState]
    absurd_task_id: Mapped[UUIDValue | None]
    attempts: Mapped[int]
    max_attempts: Mapped[int]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    last_error: Mapped[str | None]


class AbsurdBoundWorkMixin:
    """Product columns for work whose execution authority is Absurd.

    These columns project user-visible state only. No worker identity, claim,
    lease, or retry schedule exists on the product row; those belong to Absurd.
    """

    __durable_enum_name__: str = "durable_state_enum"

    if TYPE_CHECKING:
        # SQLAlchemy installs a Mapped descriptor, but declared_attr's typed
        # setter accepts Any. Expose the actual mapped write contract instead.
        state: Mapped[DurableState]
    else:

        @declared_attr
        def state(cls) -> Mapped[DurableState]:
            return mapped_column(
                ENUM(
                    DurableState,
                    name=cls.__durable_enum_name__,
                    values_callable=lambda enum: [member.value for member in enum],
                    create_type=False,
                ),
                nullable=False,
                default=DurableState.PENDING,
                server_default=DurableState.PENDING.value,
                index=True,
            )

    absurd_task_id: Mapped[UUIDValue | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True, sort_order=_AFTER_DYNAMIC_STATE
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", sort_order=_AFTER_DYNAMIC_STATE
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, sort_order=_AFTER_DYNAMIC_STATE
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=_AFTER_DYNAMIC_STATE
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=_AFTER_DYNAMIC_STATE
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, sort_order=_AFTER_DYNAMIC_STATE
    )
