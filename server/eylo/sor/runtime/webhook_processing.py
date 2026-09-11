"""Absurd-owned processing for verified SOR webhook receipts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from absurd_sdk import AsyncTaskContext, CancelledTask
from pydantic import ValidationError

from eylo.common.database import start_transaction
from eylo.durable_runtime import PlatformDurableRuntime, run_with_durable_heartbeat
from eylo.sor.runtime.adapters import (
    SorAdapterUnavailableError,
    acquire_source_adapter,
)
from eylo.sor.runtime.projection import project_source_record
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.runtime.serialization import (
    decode_external_record,
    encode_external_record,
)
from eylo.sor.runtime.sync import spawn_sor_sync_run
from eylo.sor.runtime.webhook_definition import (
    SOR_WEBHOOK_SOURCE_STATES,
    SOR_WEBHOOK_WORK,
    SOR_WEBHOOK_WORKFLOW,
)
from eylo.sor.runtime.work import (
    SorBoundWorkService,
    spawn_sor_bound_work,
    spawn_unbound_sor_work,
)
from eylo.sor.shared.contracts import (
    SorChangeStrategy,
    SorExternalRecord,
    SorExternalRecordNotFound,
    SorSourceState,
    SorSyncRunKind,
    SorWebhookReceiptState,
    SorWebhookSignal,
)
from eylo.sor.shared.events import register_records_tombstoned
from eylo.sor.shared.models import SorWebhookReceiptModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
    SorProjectionError,
    SorProjectionService,
)
from eylo.sor.shared.sync_services import SorSyncRunService

logger = logging.getLogger(__name__)


def register_sor_webhook_workflow(runtime: PlatformDurableRuntime) -> None:
    """Register the verified-delivery refetch workflow."""
    runtime.register_task(
        name=SOR_WEBHOOK_WORKFLOW,
        handler=SorWebhookWorkflow().execute,
    )


async def spawn_sor_webhook_receipt(
    *,
    organization_id: UUID,
    receipt_id: UUID,
) -> UUID:
    """Idempotently bind one verified receipt to its sole executor."""
    return await spawn_sor_bound_work(
        contract=SOR_WEBHOOK_WORK,
        organization_id=organization_id,
        work_id=receipt_id,
        workflow_name=SOR_WEBHOOK_WORKFLOW,
        params_name="receipt_id",
        idempotency_prefix="sor-webhook",
        eligible_source_states=SOR_WEBHOOK_SOURCE_STATES,
    )


async def spawn_unbound_sor_webhook_receipts(*, limit: int = 100) -> int:
    """Recover verified receipts that committed before their spawn callback."""

    async def spawn(organization_id: UUID, receipt_id: UUID) -> UUID:
        return await spawn_sor_webhook_receipt(
            organization_id=organization_id,
            receipt_id=receipt_id,
        )

    spawned, failures = await spawn_unbound_sor_work(
        contract=SOR_WEBHOOK_WORK,
        spawn=spawn,
        eligible_source_states=SOR_WEBHOOK_SOURCE_STATES,
        limit=limit,
    )
    for receipt_id, error in failures:
        logger.error(
            "Could not spawn SOR webhook receipt id=%s error_type=%s",
            receipt_id,
            type(error).__name__,
        )
    return spawned


async def cancel_sor_webhook_receipt(
    *,
    organization_id: UUID,
    receipt_id: UUID,
    error_code: str = "CONNECTION_REVOKED",
    error_summary: str = "SOR webhook processing stopped after revocation.",
) -> bool:
    """Terminalize one source refetch before cancelling its exact durable task."""
    async with start_transaction() as session:
        row = await SorBoundWorkService(SOR_WEBHOOK_WORK, session).get(
            work_id=receipt_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_WEBHOOK_WORK.terminal:
            return False
        row.state = SorWebhookReceiptState.FAILED
        row.safe_error_code = error_code[:128]
        row.safe_error_summary = error_summary[:8192]
        row.finished_at = datetime.now(timezone.utc)
        task_id = row.absurd_task_id
        await session.flush()
    if task_id is not None:
        runtime = PlatformDurableRuntime()
        try:
            await runtime.cancel_task(task_id)
        finally:
            await runtime.close()
    return True


class SorWebhookWorkflow:
    """Refetch current source state; webhook payloads are never record authority."""

    def __init__(self, *, registry: SorRegistry | None = None) -> None:
        self.registry = registry

    async def execute(
        self,
        params: dict[str, Any],
        task_context: AsyncTaskContext,
    ) -> dict[str, Any]:
        organization_id, receipt_id = _parse_params(params)
        try:
            return await self._execute(
                organization_id=organization_id,
                receipt_id=receipt_id,
                task_context=task_context,
            )
        except CancelledTask:
            async with start_transaction() as session:
                work = SorBoundWorkService(SOR_WEBHOOK_WORK, session)
                row = await work.get(
                    work_id=receipt_id,
                    organization_id=organization_id,
                    for_update=True,
                )
                if row.state is SorWebhookReceiptState.PROCESSING:
                    await work.fail(
                        work_id=receipt_id,
                        organization_id=organization_id,
                        error_code="WEBHOOK_TASK_CANCELLED",
                        error_summary="SOR webhook processing was cancelled.",
                        permanent=False,
                    )
            raise

    async def _execute(
        self,
        *,
        organization_id: UUID,
        receipt_id: UUID,
        task_context: AsyncTaskContext,
    ) -> dict[str, Any]:
        try:
            receipt = await _begin_receipt(
                organization_id=organization_id,
                receipt_id=receipt_id,
            )
            if receipt["terminal"]:
                return receipt
            source_id = UUID(receipt["source_id"])
            signals = _decode_signals(receipt["signals"])
            broad_sync_needed = False
            for index, signal in enumerate(signals):
                if signal.vendor_object_key is None or signal.external_id is None:
                    broad_sync_needed = True
                    continue
                processed = await self._process_exact_signal(
                    organization_id=organization_id,
                    source_id=source_id,
                    receipt_id=receipt_id,
                    signal_index=index,
                    signal=signal,
                    task_context=task_context,
                )
                broad_sync_needed = broad_sync_needed or not processed
            sync_rows = await _complete_receipt(
                organization_id=organization_id,
                receipt_id=receipt_id,
                source_id=source_id,
                broad_sync_needed=broad_sync_needed,
            )
        except Exception as error:  # noqa: BLE001 - project failure into receipt
            return await _handle_failure(
                organization_id=organization_id,
                receipt_id=receipt_id,
                error=error,
            )

        for run_organization_id, run_id in sync_rows:
            try:
                await spawn_sor_sync_run(
                    organization_id=run_organization_id,
                    run_id=run_id,
                )
            except Exception as error:  # noqa: BLE001 - recovery scans committed rows
                logger.error(
                    "SOR sync run committed from webhook; spawn remains pending "
                    "run_id=%s error_type=%s",
                    run_id,
                    type(error).__name__,
                )
        async with start_transaction(ro=True) as session:
            row = await SorBoundWorkService(SOR_WEBHOOK_WORK, session).get(
                work_id=receipt_id,
                organization_id=organization_id,
            )
            return _receipt(row)

    async def _process_exact_signal(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        receipt_id: UUID,
        signal_index: int,
        signal: SorWebhookSignal,
        task_context: AsyncTaskContext,
    ) -> bool:
        vendor_object_key = signal.vendor_object_key
        external_id = signal.external_id
        if vendor_object_key is None or external_id is None:
            return False
        async with start_transaction(ro=True) as session:
            stream = await SorRepository(session).get_stream_by_object(
                organization_id=organization_id,
                source_id=source_id,
                vendor_object_key=vendor_object_key,
            )
            if stream is None:
                return False
            stream_id = stream.id

        async with acquire_source_adapter(
            organization_id=organization_id,
            source_id=source_id,
            registry=self.registry,
            invocation_budget_seconds=30.0,
        ) as adapter:
            try:
                encoded = await task_context.step(
                    f"sor-webhook:{receipt_id}:signal:{signal_index}:fetch:v1",
                    lambda: run_with_durable_heartbeat(
                        task_context,
                        lambda: _fetch_record(
                            adapter=adapter,
                            vendor_object_key=vendor_object_key,
                            external_id=external_id,
                        ),
                    ),
                )
            except SorExternalRecordNotFound as error:
                await _tombstone_signal(
                    organization_id=organization_id,
                    source_id=source_id,
                    stream_id=stream_id,
                    vendor_object_key=vendor_object_key,
                    external_id=external_id,
                    error=error,
                )
                return True
            record = decode_external_record(encoded)
            async with start_transaction() as session:
                repository = SorRepository(session)
                source = await repository.get_source(
                    organization_id=organization_id,
                    source_id=source_id,
                    for_update=True,
                )
                stream = await repository.get_stream(
                    organization_id=organization_id,
                    source_id=source_id,
                    stream_id=stream_id,
                    for_update=True,
                )
                if source is None or stream is None:
                    raise SorNotFoundError("SOR webhook source stream not found.")
                if source.state not in {
                    SorSourceState.BOOTSTRAPPING,
                    SorSourceState.ACTIVE,
                    SorSourceState.DEGRADED,
                }:
                    raise SorConfigurationError(
                        "SOR source cannot project a webhook refetch."
                    )
                await project_source_record(
                    session,
                    organization_id=organization_id,
                    source=source,
                    stream=stream,
                    adapter=adapter,
                    record=record,
                    sync_run_id=None,
                )
        return True


async def _begin_receipt(
    *,
    organization_id: UUID,
    receipt_id: UUID,
) -> dict[str, Any]:
    async with start_transaction() as session:
        row = await SorBoundWorkService(SOR_WEBHOOK_WORK, session).begin_attempt(
            work_id=receipt_id,
            organization_id=organization_id,
        )
        return _receipt(row)


async def _complete_receipt(
    *,
    organization_id: UUID,
    receipt_id: UUID,
    source_id: UUID,
    broad_sync_needed: bool,
) -> list[tuple[UUID, UUID]]:
    filed: list[tuple[UUID, UUID]] = []
    async with start_transaction() as session:
        repository = SorRepository(session)
        source = await repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None:
            raise SorNotFoundError("SOR webhook source not found.")
        if broad_sync_needed and source.state in {
            SorSourceState.ACTIVE,
            SorSourceState.DEGRADED,
        }:
            streams = await repository.list_streams(
                organization_id=organization_id,
                source_id=source_id,
            )
            kind = (
                SorSyncRunKind.RECONCILIATION
                if any(
                    stream.strategy is SorChangeStrategy.FULL_RECONCILE
                    for stream in streams
                )
                else SorSyncRunKind.INCREMENTAL
            )
            try:
                plan = await SorSyncRunService(session).create_generation(
                    organization_id=organization_id,
                    source_id=source_id,
                    stream_ids=tuple(stream.id for stream in streams),
                    kind=kind,
                )
            except SorConflictError:
                # Active source work already guarantees eventual reconciliation.
                pass
            else:
                filed.extend((organization_id, run_id) for run_id in plan.ready_run_ids)
        await SorBoundWorkService(SOR_WEBHOOK_WORK, session).succeed(
            work_id=receipt_id,
            organization_id=organization_id,
        )
    return filed


async def _fetch_record(
    *,
    adapter,
    vendor_object_key: str,
    external_id: str,
) -> dict[str, Any]:
    record = await adapter.fetch_record(
        vendor_object_key=vendor_object_key,
        external_id=external_id,
    )
    return encode_external_record(record)


async def _tombstone_signal(
    *,
    organization_id: UUID,
    source_id: UUID,
    stream_id: UUID,
    vendor_object_key: str,
    external_id: str,
    error: SorExternalRecordNotFound,
) -> None:
    async with start_transaction() as session:
        try:
            record = await SorProjectionService(session).tombstone(
                organization_id=organization_id,
                source_id=source_id,
                vendor_object_key=vendor_object_key,
                vendor_external_id=external_id,
                deleted_at=error.deleted_at,
                reason=error.reason,
            )
        except SorNotFoundError:
            return
        register_records_tombstoned(
            organization_id=organization_id,
            source_id=source_id,
            stream_id=stream_id,
            sync_run_id=None,
            record_ids=(record.id,),
        )


async def _handle_failure(
    *,
    organization_id: UUID,
    receipt_id: UUID,
    error: Exception,
) -> dict[str, Any]:
    code, summary, permanent = _classify_failure(error)
    async with start_transaction() as session:
        work = SorBoundWorkService(SOR_WEBHOOK_WORK, session)
        row = await work.get(
            work_id=receipt_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_WEBHOOK_WORK.terminal:
            return _receipt(row)
        state = await work.fail(
            work_id=receipt_id,
            organization_id=organization_id,
            error_code=code,
            error_summary=summary,
            permanent=permanent,
        )
    if state is SorWebhookReceiptState.PENDING:
        raise error
    logger.warning("SOR webhook processing failed id=%s code=%s", receipt_id, code)
    return _receipt(row)


def _classify_failure(error: Exception) -> tuple[str, str, bool]:
    if isinstance(error, ValidationError):
        error = SorProjectionError("SOR adapter returned an invalid typed contract.")
    if isinstance(error, SorAdapterUnavailableError):
        return error.error_code, str(error), error.requires_reauthorization
    if isinstance(
        error,
        (SorConfigurationError, SorConflictError, SorNotFoundError, SorProjectionError),
    ):
        return "WEBHOOK_CONTRACT_INVALID", str(error), True
    return "WEBHOOK_PROVIDER_FAILED", "SOR webhook refetch failed.", False


def _decode_signals(value: object) -> tuple[SorWebhookSignal, ...]:
    if not isinstance(value, list) or not value:
        raise SorConfigurationError("SOR webhook receipt has no normalized signals.")
    signals: list[SorWebhookSignal] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "delivery_id",
            "event_type",
            "vendor_object_key",
            "external_id",
            "occurred_at",
        }:
            raise SorConfigurationError("SOR webhook signal is malformed.")
        occurred_at = raw["occurred_at"]
        if occurred_at is not None:
            if not isinstance(occurred_at, str):
                raise SorConfigurationError("SOR webhook timestamp is malformed.")
            try:
                occurred_at = datetime.fromisoformat(occurred_at)
            except ValueError as error:
                raise SorConfigurationError(
                    "SOR webhook timestamp is malformed."
                ) from error
        signals.append(
            SorWebhookSignal(
                delivery_id=_optional_string(raw["delivery_id"]),
                event_type=_required_string(raw["event_type"]),
                vendor_object_key=_optional_string(raw["vendor_object_key"]),
                external_id=_optional_string(raw["external_id"]),
                occurred_at=occurred_at,
            )
        )
    return tuple(signals)


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SorConfigurationError("SOR webhook string value is malformed.")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _required_string(value)


def _parse_params(params: dict[str, Any]) -> tuple[UUID, UUID]:
    if set(params) != {"organization_id", "receipt_id"}:
        raise ValueError("SOR webhook task params must contain IDs only.")
    try:
        return UUID(str(params["organization_id"])), UUID(str(params["receipt_id"]))
    except (TypeError, ValueError) as error:
        raise ValueError("SOR webhook task params contain an invalid UUID.") from error


def _receipt(row: SorWebhookReceiptModel) -> dict[str, Any]:
    return {
        "organization_id": str(row.organization_id),
        "receipt_id": str(row.id),
        "source_id": str(row.source_id),
        "state": row.state.value,
        "signals": row.signals,
        "terminal": row.state in SOR_WEBHOOK_WORK.terminal,
    }


__all__ = [
    "SorWebhookWorkflow",
    "cancel_sor_webhook_receipt",
    "register_sor_webhook_workflow",
    "spawn_sor_webhook_receipt",
    "spawn_unbound_sor_webhook_receipts",
]
