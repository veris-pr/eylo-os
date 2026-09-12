"""Absurd-owned bootstrap, incremental, and reconciliation execution."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from absurd_sdk import AsyncTaskContext, CancelledTask
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import select

from eylo.common.database import start_transaction
from eylo.durable_runtime import PlatformDurableRuntime, run_with_durable_heartbeat
from eylo.sor.runtime.adapters import (
    SorAdapterUnavailableError,
    acquire_source_adapter,
)
from eylo.sor.runtime.projection import project_source_record
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.runtime.serialization import (
    SorStoredPage,
    SorSyncAttempt,
    SorSyncTaskParams,
    SorSyncWorkReceipt,
    encode_external_record,
)
from eylo.sor.runtime.work import (
    SorBoundWorkService,
    SorWorkBindingPending,
    SorWorkConflict,
    SorWorkContract,
    SorWorkNotFound,
    cancel_sor_bound_work,
    spawn_sor_bound_work,
    spawn_unbound_sor_work,
)
from eylo.sor.shared.contracts import (
    SorChangeStrategy,
    SorExternalRecord,
    SorLifecycleAdapter,
    SorProjectionDisposition,
    SorRecordPage,
    SorRecoveryPolicy,
    SorSourceState,
    SorSyncRunKind,
    SorVendorOperationError,
    SorWorkState,
)
from eylo.sor.shared.models import SorSyncGenerationModel, SorSyncRunModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_cursor,
    encrypt_cursor,
)
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorProjectionError,
)
from eylo.sor.shared.sync_services import SorSyncCounts, SorSyncRunService

logger = logging.getLogger(__name__)

SOR_SYNC_WORKFLOW = "eylo.sor.sync-stream.v1"
SOR_SYNC_PAGE_LIMIT = 200
SOR_RECONCILIATION_TOMBSTONE_LIMIT = 200
SOR_SYNC_RECORD_MAX_BYTES = 1_048_576
SOR_SYNC_PAGE_MAX_BYTES = 8_388_608
SOR_SYNC_SOURCE_STATES = frozenset(
    {
        SorSourceState.BOOTSTRAPPING,
        SorSourceState.ACTIVE,
        SorSourceState.DEGRADED,
    }
)

SOR_SYNC_WORK = SorWorkContract[SorSyncRunModel](
    model=SorSyncRunModel,
    pending=SorWorkState.PENDING,
    running=SorWorkState.RUNNING,
    succeeded=SorWorkState.SUCCEEDED,
    failed=SorWorkState.FAILED,
    cancelled=SorWorkState.CANCELLED,
    terminal=frozenset(
        {
            SorWorkState.SUCCEEDED,
            SorWorkState.FAILED,
            SorWorkState.CANCELLED,
        }
    ),
)

_NONTERMINAL_SYNC_STATES = (
    SorWorkState.PENDING,
    SorWorkState.RUNNING,
    SorWorkState.WAITING,
)
SOR_SYNC_RECOVERY_LIMIT = 100
SOR_SYNC_RECOVERY_MAX_LIMIT = 1_000


class _TerminalEngineState(StrEnum):
    """Absurd terminal values interpreted at the SOR recovery boundary."""

    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class _SyncErrorCode(StrEnum):
    DURABLE_EXECUTION_FAILED = "DURABLE_EXECUTION_FAILED"
    DURABLE_RESULT_MISSING = "DURABLE_RESULT_MISSING"
    CURSOR_AUTHENTICATION_FAILED = "CURSOR_AUTHENTICATION_FAILED"
    SYNC_CONTRACT_INVALID = "SYNC_CONTRACT_INVALID"
    SYNC_PROVIDER_FAILED = "SYNC_PROVIDER_FAILED"


class _SyncFailure(BaseModel):
    """Safe failure projection; recovery policy owns retry and reauth decisions."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    code: str
    summary: str
    recovery: SorRecoveryPolicy


class _SyncRecoveryCandidate(BaseModel):
    """Detached identity only; the task binding is rechecked under the write lock."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", from_attributes=True
    )

    id: UUID
    organization_id: UUID
    absurd_task_id: UUID | None


class _SyncRecoveryCounts(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)

    checked: int = 0
    failed: int = 0
    cancelled: int = 0
    raced: int = 0
    errors: int = 0


def register_sor_sync_workflow(runtime: PlatformDurableRuntime) -> None:
    """Register one shared workflow for every source stream run kind."""
    runtime.register_task(
        name=SOR_SYNC_WORKFLOW,
        handler=SorSyncWorkflow().execute,
    )


async def spawn_sor_sync_run(*, organization_id: UUID, run_id: UUID) -> UUID:
    """Idempotently bind a committed sync run to its sole executor."""
    return await spawn_sor_bound_work(
        contract=SOR_SYNC_WORK,
        organization_id=organization_id,
        work_id=run_id,
        workflow_name=SOR_SYNC_WORKFLOW,
        idempotency_prefix="sor-sync",
        eligible_source_states=SOR_SYNC_SOURCE_STATES,
    )


async def spawn_unbound_sor_sync_runs(*, limit: int = 100) -> int:
    """Recover committed sync intent after producer callback loss."""

    async def spawn(organization_id: UUID, run_id: UUID) -> UUID:
        return await spawn_sor_sync_run(
            organization_id=organization_id,
            run_id=run_id,
        )

    spawned, failures = await spawn_unbound_sor_work(
        contract=SOR_SYNC_WORK,
        spawn=spawn,
        eligible_source_states=SOR_SYNC_SOURCE_STATES,
        limit=limit,
    )
    for run_id, error in failures:
        logger.error(
            "Could not spawn SOR sync run id=%s error_type=%s",
            run_id,
            type(error).__name__,
        )
    return spawned


async def cancel_sor_sync_run(*, organization_id: UUID, run_id: UUID) -> bool:
    """Cancel product state first, then notify the bound Absurd task."""
    async with start_transaction(ro=True) as session:
        run = await SorRepository(session).get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
        )
        generation_id = run.generation_id if run is not None else None
    cancelled = await cancel_sor_bound_work(
        contract=SOR_SYNC_WORK,
        organization_id=organization_id,
        work_id=run_id,
    )
    if cancelled and generation_id is not None:
        await _advance_and_spawn(
            organization_id=organization_id,
            generation_id=generation_id,
        )
    return cancelled


async def reconcile_terminal_sor_sync_runs(
    *, limit: int = SOR_SYNC_RECOVERY_LIMIT
) -> dict[str, int]:
    """Converge nonterminal sync receipts whose exact Absurd task has stopped."""
    if isinstance(limit, bool) or not 1 <= limit <= SOR_SYNC_RECOVERY_MAX_LIMIT:
        raise ValueError("SOR sync reconciliation limit must be between 1 and 1000.")
    async with start_transaction(ro=True) as session:
        rows = tuple(
            _SyncRecoveryCandidate.model_validate(row)
            for row in (
                await session.execute(
                    select(
                        SorSyncRunModel.id,
                        SorSyncRunModel.organization_id,
                        SorSyncRunModel.absurd_task_id,
                    )
                    .where(
                        SorSyncRunModel.state.in_(_NONTERMINAL_SYNC_STATES),
                        SorSyncRunModel.absurd_task_id.is_not(None),
                        SorSyncRunModel.deleted.is_(False),
                    )
                    .order_by(SorSyncRunModel.created_at.asc())
                    .limit(limit)
                )
            ).all()
        )

    counts = _SyncRecoveryCounts()
    runtime = PlatformDurableRuntime()
    try:
        for candidate in rows:
            task_id = candidate.absurd_task_id
            if task_id is None:
                continue
            try:
                engine_state = await runtime.task_state(task_id)
            except Exception as error:  # noqa: BLE001 - one task must not block others
                counts.errors += 1
                logger.error(
                    "Could not inspect SOR sync task run_id=%s error_type=%s",
                    candidate.id,
                    type(error).__name__,
                )
                continue
            counts.checked += 1
            if engine_state is None:
                continue
            try:
                terminal_state = _TerminalEngineState(engine_state)
            except ValueError:
                continue
            failure = _engine_terminal_failure(terminal_state)

            try:
                async with start_transaction() as session:
                    work = SorBoundWorkService(SOR_SYNC_WORK, session)
                    row = await work.get(
                        work_id=candidate.id,
                        organization_id=candidate.organization_id,
                        for_update=True,
                    )
                    if row.absurd_task_id != task_id:
                        raise SorWorkConflict(
                            "SOR sync task binding changed during reconciliation."
                        )
                    if failure is None:
                        changed, _ = await work.cancel(
                            work_id=candidate.id,
                            organization_id=candidate.organization_id,
                        )
                    else:
                        row, changed = await work.converge_engine_failure(
                            work_id=candidate.id,
                            organization_id=candidate.organization_id,
                            task_id=task_id,
                            error_code=failure.code,
                            error_summary=failure.summary,
                        )
                    generation_id = row.generation_id
                if not changed:
                    counts.raced += 1
                    continue
                if failure is None:
                    await _advance_and_spawn(
                        organization_id=candidate.organization_id,
                        generation_id=generation_id,
                    )
                    counts.cancelled += 1
                    continue
                await _project_sync_failure(
                    organization_id=candidate.organization_id,
                    run_id=candidate.id,
                    error_code=failure.code,
                    requires_reauthorization=False,
                )
                await _advance_and_spawn(
                    organization_id=candidate.organization_id,
                    generation_id=generation_id,
                )
                counts.failed += 1
            except (SorWorkConflict, SorWorkNotFound):
                counts.raced += 1
    finally:
        await runtime.close()
    return counts.model_dump()


async def reconcile_unadvanced_sor_sync_generations(
    *, limit: int = 100
) -> dict[str, int]:
    """Repair the commit-to-generation-advance seam without vendor I/O."""
    if isinstance(limit, bool) or not 1 <= limit <= 1_000:
        raise ValueError(
            "SOR generation reconciliation limit must be between 1 and 1000."
        )
    terminal_run_changed = (
        select(SorSyncRunModel.id)
        .where(
            SorSyncRunModel.organization_id == SorSyncGenerationModel.organization_id,
            SorSyncRunModel.generation_id == SorSyncGenerationModel.id,
            SorSyncRunModel.state.in_(
                (
                    SorWorkState.SUCCEEDED,
                    SorWorkState.FAILED,
                    SorWorkState.CANCELLED,
                )
            ),
            SorSyncRunModel.updated_at > SorSyncGenerationModel.updated_at,
            SorSyncRunModel.deleted.is_(False),
        )
        .exists()
    )
    async with start_transaction(ro=True) as session:
        candidates = list(
            (
                await session.execute(
                    select(
                        SorSyncGenerationModel.id,
                        SorSyncGenerationModel.organization_id,
                    )
                    .where(
                        SorSyncGenerationModel.state.in_(
                            (SorWorkState.PENDING, SorWorkState.RUNNING)
                        ),
                        SorSyncGenerationModel.deleted.is_(False),
                        terminal_run_changed,
                    )
                    .order_by(SorSyncGenerationModel.updated_at.asc())
                    .limit(limit)
                )
            ).all()
        )

    reconciled = 0
    errors = 0
    for candidate in candidates:
        try:
            await _advance_and_spawn(
                organization_id=candidate.organization_id,
                generation_id=candidate.id,
            )
            reconciled += 1
        except Exception as error:  # noqa: BLE001 - later nudges retry the seam
            errors += 1
            logger.error(
                "Could not reconcile SOR sync generation id=%s error_type=%s",
                candidate.id,
                type(error).__name__,
            )
    return {
        "checked": len(candidates),
        "reconciled": reconciled,
        "errors": errors,
    }


class SorSyncWorkflow:
    """Fetch outside DB transactions and checkpoint only committed projections."""

    def __init__(self, *, registry: SorRegistry | None = None) -> None:
        self.registry = registry

    async def execute(
        self,
        params: dict[str, JsonValue],
        task_context: AsyncTaskContext,
    ) -> dict[str, JsonValue]:
        request = _parse_params(params)
        organization_id, run_id = request.organization_id, request.run_id
        try:
            receipt = await self._execute(
                organization_id=organization_id,
                run_id=run_id,
                task_context=task_context,
            )
            return receipt.model_dump(mode="json")
        except CancelledTask:
            async with start_transaction() as session:
                work = SorBoundWorkService(SOR_SYNC_WORK, session)
                row = await work.get(
                    work_id=run_id,
                    organization_id=organization_id,
                    for_update=True,
                )
                await work.cancel(
                    work_id=run_id,
                    organization_id=organization_id,
                )
                generation_id = row.generation_id
            await _advance_and_spawn(
                organization_id=organization_id,
                generation_id=generation_id,
            )
            raise

    async def _execute(
        self,
        *,
        organization_id: UUID,
        run_id: UUID,
        task_context: AsyncTaskContext,
    ) -> SorSyncWorkReceipt:
        try:
            attempt = await _begin_attempt(
                organization_id=organization_id,
                run_id=run_id,
            )
        except SorWorkBindingPending:
            raise
        except Exception as error:  # noqa: BLE001 - project load failure into row
            return await _handle_failure(
                organization_id=organization_id,
                run_id=run_id,
                error=error,
            )
        if isinstance(attempt, SorSyncWorkReceipt):
            return attempt

        source_id = attempt.receipt.source_id
        stream_id = attempt.stream_id
        kind = attempt.receipt.kind
        strategy = attempt.strategy
        cursor_version = attempt.cursor_version
        expected_checkpoint = attempt.checkpoint
        try:
            cursor = decrypt_cursor(
                expected_checkpoint,
                organization_id=organization_id,
                stream_id=stream_id,
                cursor_version=cursor_version,
            )
        except Exception as error:
            return await _handle_failure(
                organization_id=organization_id,
                run_id=run_id,
                error=error,
            )

        total = attempt.receipt.counts
        scan_complete = attempt.scan_complete
        if not scan_complete:
            try:
                async with acquire_source_adapter(
                    organization_id=organization_id,
                    source_id=source_id,
                    registry=self.registry,
                    invocation_budget_seconds=120.0,
                ) as adapter:
                    while not scan_complete:
                        page = await run_with_durable_heartbeat(
                            task_context,
                            lambda: _fetch_page(
                                adapter=adapter,
                                kind=kind,
                                stream_key=attempt.stream_key,
                                cursor=cursor,
                            ),
                        )
                        _validate_cursor_progress(page=page, current=cursor)
                        next_cursor = (
                            page.next_cursor if page.next_cursor is not None else cursor
                        )
                        checkpoint_after = (
                            encrypt_cursor(
                                next_cursor,
                                organization_id=organization_id,
                                stream_id=stream_id,
                                cursor_version=cursor_version,
                            )
                            if next_cursor is not None
                            else None
                        )
                        page_counts = await _commit_page(
                            organization_id=organization_id,
                            run_id=run_id,
                            expected_checkpoint=expected_checkpoint,
                            checkpoint_after=checkpoint_after,
                            scan_complete=not page.has_more,
                            page=page,
                            adapter=adapter,
                        )
                        total = total.add(page_counts)
                        expected_checkpoint = checkpoint_after
                        cursor = next_cursor
                        scan_complete = not page.has_more
            except CancelledTask:
                raise
            except Exception as error:  # noqa: BLE001 - failure controls retry state
                return await _handle_failure(
                    organization_id=organization_id,
                    run_id=run_id,
                    error=error,
                )

        if strategy is SorChangeStrategy.FULL_RECONCILE and kind in {
            SorSyncRunKind.BOOTSTRAP,
            SorSyncRunKind.RECONCILIATION,
        }:
            while True:
                tombstoned = await _tombstone_full_scan_batch(
                    organization_id=organization_id,
                    run_id=run_id,
                    expected_checkpoint=expected_checkpoint,
                )
                if tombstoned == 0:
                    break
                total = total.add(SorSyncCounts(tombstoned=tombstoned))

        async with start_transaction() as session:
            sync = SorSyncRunService(session)
            context = await sync.lock_finalization_context(
                organization_id=organization_id,
                run_id=run_id,
                expected_checkpoint=expected_checkpoint,
            )
            await sync.finish_success(context=context, counts=total)
            row = await SorBoundWorkService(SOR_SYNC_WORK, session).succeed(
                work_id=run_id,
                organization_id=organization_id,
                values=total,
            )
            generation_id = row.generation_id
            receipt = _receipt(row)
        await _advance_and_spawn(
            organization_id=organization_id,
            generation_id=generation_id,
        )
        return receipt


async def _begin_attempt(
    *, organization_id: UUID, run_id: UUID
) -> SorSyncWorkReceipt | SorSyncAttempt:
    async with start_transaction() as session:
        row = await SorBoundWorkService(SOR_SYNC_WORK, session).begin_attempt(
            work_id=run_id,
            organization_id=organization_id,
        )
        terminal = row.state in SOR_SYNC_WORK.terminal
        generation_id = row.generation_id
        receipt = _receipt(row, terminal=terminal)

    if terminal:
        return receipt

    async with start_transaction() as session:
        await SorSyncRunService(session).mark_generation_started(
            organization_id=organization_id,
            generation_id=generation_id,
        )

    async with start_transaction(ro=True) as session:
        repository = SorRepository(session)
        current = await repository.get_sync_run(
            organization_id=organization_id,
            run_id=run_id,
        )
        if current is None or current.stream_id is None:
            raise SorConfigurationError("SOR sync run has no source stream.")
        stream = await repository.get_stream(
            organization_id=organization_id,
            source_id=current.source_id,
            stream_id=current.stream_id,
        )
        if stream is None:
            raise SorConfigurationError("SOR sync stream no longer exists.")
        checkpoint = (
            current.checkpoint_after
            if current.kind in {SorSyncRunKind.BOOTSTRAP, SorSyncRunKind.RECONCILIATION}
            else stream.checkpoint
        )
        return SorSyncAttempt(
            receipt=receipt,
            stream_id=stream.id,
            stream_key=stream.vendor_object_key,
            strategy=stream.strategy,
            cursor_version=stream.cursor_version,
            checkpoint=checkpoint,
            scan_complete=current.scan_complete,
        )


async def _fetch_page(
    *,
    adapter: SorLifecycleAdapter,
    kind: SorSyncRunKind,
    stream_key: str,
    cursor: str | None,
) -> SorRecordPage:
    if kind in {SorSyncRunKind.BOOTSTRAP, SorSyncRunKind.RECONCILIATION}:
        page = await adapter.bootstrap_stream(
            stream_key=stream_key,
            cursor=cursor,
            limit=SOR_SYNC_PAGE_LIMIT,
        )
    else:
        page = await adapter.pull_changes(
            stream_key=stream_key,
            cursor=cursor,
            limit=SOR_SYNC_PAGE_LIMIT,
        )
    return _decode_page(_encode_page(page))


async def _commit_page(
    *,
    organization_id: UUID,
    run_id: UUID,
    expected_checkpoint: str | None,
    checkpoint_after: str | None,
    scan_complete: bool,
    page: SorRecordPage,
    adapter: SorLifecycleAdapter,
) -> SorSyncCounts:
    identities = [
        (record.vendor_object_key, record.external_id) for record in page.records
    ]
    if len(identities) != len(set(identities)):
        raise SorProjectionError("SOR page contains duplicate source identities.")
    async with start_transaction() as session:
        sync = SorSyncRunService(session)
        context = await sync.lock_page_context(
            organization_id=organization_id,
            run_id=run_id,
            expected_checkpoint=expected_checkpoint,
        )
        dispositions: list[SorProjectionDisposition] = []
        for record in page.records:
            outcome = await project_source_record(
                session,
                organization_id=organization_id,
                source=context.source,
                stream=context.stream,
                adapter=adapter,
                record=record,
                sync_run_id=run_id,
            )
            dispositions.append(outcome.disposition)
        counts = SorSyncCounts.from_dispositions(dispositions)
        await sync.commit_page(
            context=context,
            checkpoint_after=checkpoint_after,
            counts=counts,
            scan_complete=scan_complete,
        )
    return counts


async def _tombstone_full_scan_batch(
    *,
    organization_id: UUID,
    run_id: UUID,
    expected_checkpoint: str | None,
) -> int:
    """Tombstone one bounded page missing from a completed full source scan."""
    async with start_transaction() as session:
        sync = SorSyncRunService(session)
        context = await sync.lock_finalization_context(
            organization_id=organization_id,
            run_id=run_id,
            expected_checkpoint=expected_checkpoint,
        )
        return await sync.tombstone_missing_batch(
            context=context,
            limit=SOR_RECONCILIATION_TOMBSTONE_LIMIT,
        )


async def _handle_failure(
    *,
    organization_id: UUID,
    run_id: UUID,
    error: Exception,
) -> SorSyncWorkReceipt:
    failure = _classify_failure(error)
    async with start_transaction() as session:
        work = SorBoundWorkService(SOR_SYNC_WORK, session)
        row = await work.get(
            work_id=run_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_SYNC_WORK.terminal:
            return _receipt(row)
        state = await work.fail(
            work_id=run_id,
            organization_id=organization_id,
            error_code=failure.code,
            error_summary=failure.summary,
            permanent=not failure.recovery.retryable,
        )
        generation_id = row.generation_id
        receipt = _receipt(row)
    if state is SorWorkState.PENDING:
        raise error
    if state is SorWorkState.FAILED:
        await _project_sync_failure(
            organization_id=organization_id,
            run_id=run_id,
            error_code=failure.code,
            requires_reauthorization=failure.recovery.requires_reauthorization,
        )
        await _advance_and_spawn(
            organization_id=organization_id,
            generation_id=generation_id,
        )
    logger.warning("SOR sync failed id=%s code=%s", run_id, failure.code)
    return receipt


async def _project_sync_failure(
    *,
    organization_id: UUID,
    run_id: UUID,
    error_code: str,
    requires_reauthorization: bool,
) -> None:
    """Best-effort source projection after the authoritative receipt commits."""
    try:
        async with start_transaction() as session:
            await SorSyncRunService(session).mark_failure(
                organization_id=organization_id,
                run_id=run_id,
                error_code=error_code,
                requires_reauthorization=requires_reauthorization,
            )
    except Exception as projection_error:  # noqa: BLE001 - receipt is authoritative
        logger.error(
            "SOR sync failure committed but source projection failed "
            "id=%s error_type=%s",
            run_id,
            type(projection_error).__name__,
        )


def _engine_terminal_failure(engine_state: _TerminalEngineState) -> _SyncFailure | None:
    """A stopped engine without a product result fails, except explicit cancellation."""
    if engine_state is _TerminalEngineState.CANCELLED:
        return None
    if engine_state is _TerminalEngineState.FAILED:
        return _SyncFailure(
            code=_SyncErrorCode.DURABLE_EXECUTION_FAILED,
            summary="Durable synchronization exhausted its execution attempts.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _SyncFailure(
        code=_SyncErrorCode.DURABLE_RESULT_MISSING,
        summary="Durable synchronization completed without committing a product result.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )


def _classify_failure(error: Exception) -> _SyncFailure:
    if isinstance(error, ValidationError):
        error = SorProjectionError("SOR adapter returned an invalid typed contract.")
    if isinstance(error, SorAdapterUnavailableError):
        return _SyncFailure(
            code=error.error_code,
            summary=str(error),
            recovery=(
                SorRecoveryPolicy.REAUTH_REQUIRED
                if error.requires_reauthorization
                else SorRecoveryPolicy.RETRY
            ),
        )
    if isinstance(error, SorVendorOperationError):
        return _SyncFailure(
            code=error.code.value,
            summary=str(error),
            recovery=error.recovery,
        )
    if isinstance(error, SorSecretEnvelopeError):
        return _SyncFailure(
            code=_SyncErrorCode.CURSOR_AUTHENTICATION_FAILED,
            summary=str(error),
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if isinstance(error, (SorConfigurationError, SorConflictError, SorProjectionError)):
        return _SyncFailure(
            code=_SyncErrorCode.SYNC_CONTRACT_INVALID,
            summary=str(error),
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return _SyncFailure(
        code=_SyncErrorCode.SYNC_PROVIDER_FAILED,
        summary="SOR provider synchronization failed.",
        recovery=SorRecoveryPolicy.RETRY,
    )


def _encode_page(page: SorRecordPage) -> dict[str, JsonValue]:
    if not isinstance(page, SorRecordPage):
        raise SorProjectionError("SOR adapter returned an invalid record page.")
    if len(page.records) > SOR_SYNC_PAGE_LIMIT:
        raise SorProjectionError("SOR adapter returned more records than requested.")
    records = [_encode_record(record) for record in page.records]
    encoded: dict[str, JsonValue] = {
        "records": records,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }
    _require_json_size(
        encoded,
        maximum=SOR_SYNC_PAGE_MAX_BYTES,
        field_name="SOR durable page",
    )
    return encoded


def _encode_record(record: SorExternalRecord) -> dict[str, JsonValue]:
    encoded = encode_external_record(record)
    _require_json_size(
        encoded,
        maximum=SOR_SYNC_RECORD_MAX_BYTES,
        field_name="SOR durable record",
    )
    return encoded


def _decode_page(value: object) -> SorRecordPage:
    _require_json_size(
        value,
        maximum=SOR_SYNC_PAGE_MAX_BYTES,
        field_name="Durable SOR page",
    )
    try:
        stored = SorStoredPage.model_validate(value)
    except ValidationError as error:
        raise SorProjectionError("Durable SOR page result is malformed.") from error
    if len(stored.records) > SOR_SYNC_PAGE_LIMIT:
        raise SorProjectionError("Durable SOR page records are malformed.")
    for record in stored.records:
        _require_json_size(
            record.model_dump(mode="json"),
            maximum=SOR_SYNC_RECORD_MAX_BYTES,
            field_name="Durable SOR record",
        )
    return stored.to_page()


def _require_json_size(value: object, *, maximum: int, field_name: str) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SorProjectionError(f"{field_name} is not JSON-compatible.") from error
    if len(encoded) > maximum:
        raise SorProjectionError(f"{field_name} exceeds its size limit.")


def _validate_cursor_progress(*, page: SorRecordPage, current: str | None) -> None:
    if page.has_more and page.next_cursor is None:
        raise SorProjectionError("A partial SOR page must return its next cursor.")
    if page.has_more and page.next_cursor == current:
        raise SorProjectionError("SOR adapter cursor did not advance.")


async def _advance_and_spawn(
    *,
    organization_id: UUID,
    generation_id: UUID,
) -> None:
    async with start_transaction() as session:
        ready = await SorSyncRunService(session).advance_generation(
            organization_id=organization_id,
            generation_id=generation_id,
        )
    await _spawn_ready_runs(organization_id=organization_id, run_ids=ready)


async def _spawn_ready_runs(
    *,
    organization_id: UUID,
    run_ids: tuple[UUID, ...],
) -> None:
    for ready_run_id in run_ids:
        try:
            await spawn_sor_sync_run(
                organization_id=organization_id,
                run_id=ready_run_id,
            )
        except Exception as error:  # noqa: BLE001 - outbox recovery owns retries
            logger.error(
                "SOR dependency released; spawn recovery remains pending "
                "run_id=%s error_type=%s",
                ready_run_id,
                type(error).__name__,
            )


def _parse_params(params: object) -> SorSyncTaskParams:
    if (
        not isinstance(params, dict)
        or set(params) != SorSyncTaskParams.model_fields.keys()
    ):
        raise ValueError("SOR sync task params must contain IDs only.")
    try:
        return SorSyncTaskParams.model_validate(params)
    except ValidationError as error:
        raise ValueError("SOR sync task params contain an invalid UUID.") from error


def _receipt(
    row: SorSyncRunModel, *, terminal: bool | None = None
) -> SorSyncWorkReceipt:
    return SorSyncWorkReceipt(
        organization_id=row.organization_id,
        run_id=row.id,
        source_id=row.source_id,
        kind=row.kind,
        state=row.state,
        terminal=row.state in SOR_SYNC_WORK.terminal if terminal is None else terminal,
        records_added=row.records_added,
        records_updated=row.records_updated,
        records_tombstoned=row.records_tombstoned,
        records_unchanged=row.records_unchanged,
        records_rejected=row.records_rejected,
    )


__all__ = [
    "SOR_SYNC_PAGE_LIMIT",
    "SOR_SYNC_WORKFLOW",
    "SorSyncWorkflow",
    "cancel_sor_sync_run",
    "reconcile_unadvanced_sor_sync_generations",
    "reconcile_terminal_sor_sync_runs",
    "register_sor_sync_workflow",
    "spawn_sor_sync_run",
    "spawn_unbound_sor_sync_runs",
]
