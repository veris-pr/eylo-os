"""Bind richer SOR product lifecycles to one exact Absurd task."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.database import start_transaction
from eylo.durable_runtime import PlatformDurableRuntime
from eylo.sor.shared.models import SorSourceModel


class SorWorkNotFound(Exception):
    """The task IDs do not resolve to an organization-owned SOR work row."""


class SorWorkBindingPending(Exception):
    """Absurd claimed a row before its task binding became visible."""


class SorWorkConflict(Exception):
    """A SOR work row cannot accept the requested lifecycle transition."""


@dataclass(frozen=True, slots=True)
class SorWorkContract:
    """Describe one persisted SOR lifecycle without flattening its domain enum."""

    model: type[Any]
    pending: Enum
    running: Enum
    succeeded: Enum
    failed: Enum
    terminal: frozenset[Enum]
    error_code_field: str
    error_summary_field: str = "safe_error_summary"
    cancelled: Enum | None = None

    def __post_init__(self) -> None:
        required = {
            self.pending,
            self.running,
            self.succeeded,
            self.failed,
        }
        if not required.issubset(self.terminal | {self.pending, self.running}):
            raise ValueError("SOR work contract states are internally inconsistent.")
        if self.succeeded not in self.terminal or self.failed not in self.terminal:
            raise ValueError("SOR success and failure states must be terminal.")
        if self.cancelled is not None and self.cancelled not in self.terminal:
            raise ValueError("SOR cancellation state must be terminal.")


class SorBoundWorkService:
    """Lock and project one typed SOR lifecycle while Absurd owns execution."""

    def __init__(
        self,
        contract: SorWorkContract,
        session: AsyncSession,
    ) -> None:
        self.contract = contract
        self.session = session

    async def get(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        for_update: bool = False,
    ) -> Any:
        model = self.contract.model
        query = select(model).where(
            model.id == work_id,
            model.organization_id == organization_id,
            model.deleted.is_(False),
        )
        if for_update:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None:
            raise SorWorkNotFound
        return row

    async def begin_attempt(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
    ) -> Any:
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in self.contract.terminal:
            return row
        if row.absurd_task_id is None:
            raise SorWorkBindingPending(
                "Absurd SOR task binding is not visible yet."
            )
        if row.state not in {self.contract.pending, self.contract.running}:
            raise SorWorkConflict(
                f"A {row.state.value} SOR row cannot begin an attempt."
            )
        row.state = self.contract.running
        row.attempts += 1
        row.started_at = row.started_at or datetime.now(timezone.utc)
        row.finished_at = None
        await self.session.flush()
        return row

    async def bind_task(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        task_id: UUID,
    ) -> tuple[bool, bool]:
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.absurd_task_id is not None:
            if row.absurd_task_id != task_id:
                raise SorWorkConflict(
                    "SOR work is already bound to another Absurd task."
                )
            return False, self._cancelled(row)
        bindable = {self.contract.pending}
        if self.contract.cancelled is not None:
            bindable.add(self.contract.cancelled)
        if row.state not in bindable:
            raise SorWorkConflict(
                f"A {row.state.value} SOR row cannot bind an Absurd task."
            )
        row.absurd_task_id = task_id
        await self.session.flush()
        return True, self._cancelled(row)

    async def succeed(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        values: dict[str, Any] | None = None,
    ) -> Any:
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state is self.contract.succeeded:
            return row
        if row.state is not self.contract.running:
            return row
        self._assign(row, values or {})
        row.state = self.contract.succeeded
        setattr(row, self.contract.error_code_field, None)
        setattr(row, self.contract.error_summary_field, None)
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def fail(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        error_code: str,
        error_summary: str,
        permanent: bool,
    ) -> Enum:
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in self.contract.terminal:
            return row.state
        if row.state is not self.contract.running:
            raise SorWorkConflict(
                f"A {row.state.value} SOR row cannot record failure."
            )
        exhausted = permanent or row.attempts >= row.max_attempts
        row.state = self.contract.failed if exhausted else self.contract.pending
        setattr(row, self.contract.error_code_field, error_code[:128])
        setattr(row, self.contract.error_summary_field, error_summary[:8192])
        row.finished_at = datetime.now(timezone.utc) if exhausted else None
        await self.session.flush()
        return row.state

    async def converge_engine_failure(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        task_id: UUID,
        error_code: str,
        error_summary: str,
    ) -> tuple[Any, bool]:
        """Terminalize product work after its exact durable task has stopped."""
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.absurd_task_id != task_id:
            raise SorWorkConflict("SOR work is not bound to the inspected Absurd task.")
        if row.state in self.contract.terminal:
            return row, False
        row.state = self.contract.failed
        setattr(row, self.contract.error_code_field, error_code[:128])
        setattr(row, self.contract.error_summary_field, error_summary[:8192])
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row, True

    async def finish_as(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
        state: Enum,
        values: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> Any:
        """Finish in a nonstandard terminal state such as command conflict."""
        if state not in self.contract.terminal:
            raise SorWorkConflict("Requested SOR state is not terminal.")
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in self.contract.terminal:
            return row
        if row.state is not self.contract.running:
            raise SorWorkConflict(
                f"A {row.state.value} SOR row cannot finish."
            )
        self._assign(row, values or {})
        row.state = state
        setattr(row, self.contract.error_code_field, error_code[:128] if error_code else None)
        setattr(
            row,
            self.contract.error_summary_field,
            error_summary[:8192] if error_summary else None,
        )
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        return row

    async def cancel(
        self,
        *,
        work_id: UUID,
        organization_id: UUID,
    ) -> tuple[bool, UUID | None]:
        if self.contract.cancelled is None:
            raise SorWorkConflict("This SOR work kind cannot be cancelled.")
        row = await self.get(
            work_id=work_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in self.contract.terminal:
            return False, row.absurd_task_id
        row.state = self.contract.cancelled
        row.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True, row.absurd_task_id

    def _cancelled(self, row: Any) -> bool:
        return self.contract.cancelled is not None and row.state is self.contract.cancelled

    def _assign(self, row: Any, values: dict[str, Any]) -> None:
        for field, value in values.items():
            if not hasattr(row, field):
                raise SorWorkConflict(f"Unknown SOR result field {field}.")
            setattr(row, field, value)


async def spawn_sor_bound_work(
    *,
    contract: SorWorkContract,
    organization_id: UUID,
    work_id: UUID,
    workflow_name: str,
    params_name: str,
    idempotency_prefix: str,
    eligible_source_states: frozenset[Enum],
) -> UUID:
    """Idempotently spawn and bind one already-committed SOR product row."""
    async with start_transaction(ro=True) as session:
        row = await SorBoundWorkService(contract, session).get(
            work_id=work_id,
            organization_id=organization_id,
        )
        if row.absurd_task_id is not None:
            return row.absurd_task_id
        if row.state is not contract.pending:
            raise SorWorkConflict(
                f"A {row.state.value} SOR row cannot be spawned."
            )
        await _require_spawn_source_authority(
            session,
            row=row,
            eligible_source_states=eligible_source_states,
        )
        max_attempts = row.max_attempts

    runtime = PlatformDurableRuntime()
    try:
        task_id = await runtime.spawn_task(
            name=workflow_name,
            params={
                "organization_id": str(organization_id),
                params_name: str(work_id),
            },
            idempotency_key=f"{idempotency_prefix}:v1:{organization_id}:{work_id}",
            max_attempts=max_attempts,
        )
        async with start_transaction() as session:
            _, cancellation_pending = await SorBoundWorkService(
                contract,
                session,
            ).bind_task(
                work_id=work_id,
                organization_id=organization_id,
                task_id=task_id,
            )
        if cancellation_pending:
            await runtime.cancel_task(task_id)
        return task_id
    finally:
        await runtime.close()


async def spawn_unbound_sor_work(
    *,
    contract: SorWorkContract,
    spawn: Callable[[UUID, UUID], Awaitable[UUID]],
    eligible_source_states: frozenset[Enum],
    limit: int = 100,
) -> tuple[int, list[tuple[UUID, Exception]]]:
    """Recover committed SOR outbox rows without executing the product work."""
    if not 1 <= limit <= 1000:
        raise ValueError("SOR recovery limit must be between 1 and 1000.")
    model = contract.model
    async with start_transaction(ro=True) as session:
        rows = list(
            (
                await session.execute(
                    select(model.organization_id, model.id)
                    .join(
                        SorSourceModel,
                        (SorSourceModel.id == model.source_id)
                        & (SorSourceModel.organization_id == model.organization_id),
                    )
                    .where(
                        model.state == contract.pending,
                        model.absurd_task_id.is_(None),
                        model.deleted.is_(False),
                        SorSourceModel.state.in_(eligible_source_states),
                        SorSourceModel.deleted.is_(False),
                    )
                    .order_by(model.created_at.asc(), model.id.asc())
                    .limit(limit)
                )
            ).all()
        )
    spawned = 0
    failures: list[tuple[UUID, Exception]] = []
    for organization_id, work_id in rows:
        try:
            await spawn(organization_id, work_id)
            spawned += 1
        except SorWorkConflict:
            continue
        except Exception as error:  # noqa: BLE001 - recover rows independently
            failures.append((work_id, error))
    return spawned, failures


async def _require_spawn_source_authority(
    session: AsyncSession,
    *,
    row: Any,
    eligible_source_states: frozenset[Enum],
) -> None:
    source_id = await session.scalar(
        select(SorSourceModel.id).where(
            SorSourceModel.id == row.source_id,
            SorSourceModel.organization_id == row.organization_id,
            SorSourceModel.state.in_(eligible_source_states),
            SorSourceModel.deleted.is_(False),
        )
    )
    if source_id is None:
        raise SorWorkConflict("SOR work source no longer permits durable spawn.")


async def cancel_sor_bound_work(
    *,
    contract: SorWorkContract,
    organization_id: UUID,
    work_id: UUID,
) -> bool:
    """Commit product cancellation before notifying its exact Absurd task."""
    async with start_transaction() as session:
        cancelled, task_id = await SorBoundWorkService(contract, session).cancel(
            work_id=work_id,
            organization_id=organization_id,
        )
    if cancelled and task_id is not None:
        runtime = PlatformDurableRuntime()
        try:
            await runtime.cancel_task(task_id)
        finally:
            await runtime.close()
    return cancelled


__all__ = [
    "SorBoundWorkService",
    "SorWorkBindingPending",
    "SorWorkConflict",
    "SorWorkContract",
    "SorWorkNotFound",
    "cancel_sor_bound_work",
    "spawn_sor_bound_work",
    "spawn_unbound_sor_work",
]
