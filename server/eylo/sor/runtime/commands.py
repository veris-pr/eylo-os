"""Authorize, checkpoint, execute, and project durable SOR mutations."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

import uuid_utils
from absurd_sdk import AsyncTaskContext, CancelledTask
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    InstanceOf,
    JsonValue,
    ValidationError,
)
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from eylo.common.database import start_transaction
from eylo.common.revisions import RevisionAvailability
from eylo.durable_runtime import PlatformDurableRuntime, run_with_durable_heartbeat
from eylo.modules.agent_runs.domain import AgentRunLifecycle
from eylo.modules.agent_runs.models import AgentRunModel
from eylo.modules.agents.models import AgentRevisionModel, AgentRevisionToolModel
from eylo.modules.connections.domain import (
    ConnectionOwnerKind,
    ExternalConnectionStatus,
)
from eylo.modules.connections.models import ExternalConnectionModel
from eylo.modules.tools.services.tool_register import system_tool_id
from eylo.sor.runtime.action_events import file_sor_action_event
from eylo.sor.runtime.adapters import (
    SorAdapterUnavailableError,
    acquire_source_adapter,
)
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.runtime.command_payloads import validate_command_payload
from eylo.sor.runtime.projection import project_source_record
from eylo.sor.runtime.registry import SorRegistry
from eylo.sor.runtime.serialization import (
    SorStoredCommandResult,
    decode_external_record,
    encode_external_record,
)
from eylo.sor.runtime.work import (
    SorBoundWorkService,
    SorCommandCompletion,
    SorWorkBindingPending,
    SorWorkContract,
    spawn_sor_bound_work,
    spawn_unbound_sor_work,
)
from eylo.sor.shared.contracts import (
    SorAdapterCapabilityManifest,
    SorCommandPayload,
    SorCommandRequest,
    SorCommandResult,
    SorCommandRevisionConflict,
    SorCommandState,
    SorExternalRecord,
    SorFieldMappingDirection,
    SorFieldMappingState,
    SorLifecycleAdapter,
    SorProfile,
    SorRecoveryPolicy,
    SorSourceAccess,
    SorSourcePayload,
    SorSourceState,
    SorToolEffect,
    SorToolSpec,
    SorVendorOperationError,
)
from eylo.sor.shared.models import (
    SorAgentRevisionSourceGrantModel,
    SorCommandModel,
    SorRecordModel,
    SorSourceGrantModel,
    SorSourceModel,
)
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.secrets import (
    SorSecretEnvelopeError,
    decrypt_json_payload,
    encrypt_json_payload,
)
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
    SorProjectionError,
)

logger = logging.getLogger(__name__)

SOR_COMMAND_WORKFLOW = "eylo.sor.execute-command.v1"
SOR_COMMAND_WAIT_OWNER_KIND = "sor_command"
SOR_COMMAND_MAX_PAYLOAD_BYTES = 524_288
SOR_COMMAND_MAX_SAFE_RESULT_BYTES = 65_536
SOR_COMMAND_SOURCE_STATES = frozenset({SorSourceState.ACTIVE, SorSourceState.DEGRADED})

SOR_COMMAND_WORK = SorWorkContract[SorCommandModel](
    model=SorCommandModel,
    pending=SorCommandState.PENDING,
    running=SorCommandState.RUNNING,
    succeeded=SorCommandState.SUCCEEDED,
    failed=SorCommandState.FAILED,
    cancelled=SorCommandState.CANCELLED,
    terminal=frozenset(
        {
            SorCommandState.SUCCEEDED,
            SorCommandState.FAILED,
            SorCommandState.CONFLICT,
            SorCommandState.CANCELLED,
        }
    ),
)


class SorCommandFailure(StrEnum):
    """Stable runtime-owned refusal categories; vendor failures stay separate."""

    AGENT_REVISION_SOURCE_UNAVAILABLE = "AGENT_REVISION_SOURCE_UNAVAILABLE"
    AGENT_REVISION_TOOL_UNAVAILABLE = "AGENT_REVISION_TOOL_UNAVAILABLE"
    AGENT_REVISION_UNAVAILABLE = "AGENT_REVISION_UNAVAILABLE"
    AGENT_RUN_NOT_RUNNING = "AGENT_RUN_NOT_RUNNING"
    SOURCE_CONNECTION_UNAVAILABLE = "SOURCE_CONNECTION_UNAVAILABLE"
    SOURCE_GRANT_REVOKED = "SOURCE_GRANT_REVOKED"
    SOURCE_GRANT_UNAVAILABLE = "SOURCE_GRANT_UNAVAILABLE"
    SOURCE_NOT_ACTIVE = "SOURCE_NOT_ACTIVE"
    SOURCE_TOOL_SCOPE_MISSING = "SOURCE_TOOL_SCOPE_MISSING"
    SOURCE_TOOL_UNAVAILABLE = "SOURCE_TOOL_UNAVAILABLE"
    SOURCE_REVISION_CONFLICT = "SOURCE_REVISION_CONFLICT"
    COMMAND_PAYLOAD_INVALID = "COMMAND_PAYLOAD_INVALID"
    COMMAND_CONTRACT_INVALID = "COMMAND_CONTRACT_INVALID"
    COMMAND_PROVIDER_FAILED = "COMMAND_PROVIDER_FAILED"


class SorCommandAuthorizationError(Exception):
    """Live Agent, run, revision, or grant authority no longer permits a write."""

    def __init__(self, code: SorCommandFailure, message: str) -> None:
        super().__init__(message)
        self.code = code


class SorFiledCommand(BaseModel):
    """Stable command identity returned to the invoking Agent tool."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    command_id: UUID
    state: SorCommandState
    created: bool


class SorCommandReceipt(BaseModel):
    """Exact command identity and finite JSON result shared by worker and tool resume."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    organization_id: UUID
    command_id: UUID
    source_id: UUID
    agent_run_id: UUID
    tool_call_id: str
    profile_tool: str
    state: SorCommandState
    mutation_applied: bool
    safe_result: dict[str, JsonValue] | None = Field(repr=False)
    safe_error_category: str | None
    safe_error_summary: str | None = Field(repr=False)

    @property
    def terminal(self) -> bool:
        return self.state in SOR_COMMAND_WORK.terminal


class _CommandClaim(BaseModel):
    """Resolved command data; encrypted persistence owns raw payload readback."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    organization_id: UUID
    command_id: UUID
    source_id: UUID
    profile: SorProfile
    vendor_key: str
    profile_tool: str
    idempotency_key: str
    payload: SkipJsonSchema[InstanceOf[SorCommandPayload]] = Field(
        repr=False, exclude=True
    )
    target_vendor_object_key: str | None
    target_external_id: str | None
    expected_source_revision: str | None
    target_selected_payload: SorSourcePayload | None = Field(repr=False, exclude=True)
    result_vendor_object_key: str
    supports_conditional_writes: bool
    mutation_applied: bool
    mutation_result: SorCommandResult | None


def register_sor_command_workflow(runtime: PlatformDurableRuntime) -> None:
    """Register one command executor for every profile-native mutation tool."""
    runtime.register_task(
        name=SOR_COMMAND_WORKFLOW,
        handler=SorCommandWorkflow().execute,
    )


async def file_sor_command(
    *,
    organization_id: UUID,
    source_id: UUID,
    profile_tool: str,
    agent_id: UUID,
    agent_revision: int,
    agent_run_id: UUID,
    tool_call_id: str,
    payload: SorCommandPayload,
    target_record_id: UUID | None = None,
    enforce_target_revision: bool = False,
    registry: SorRegistry | None = None,
) -> SorFiledCommand:
    """Persist one idempotent Agent mutation, then best-effort enqueue it."""
    resolved_registry = registry or get_sor_registry()
    async with start_transaction() as session:
        row, created = await _create_command(
            session=session,
            organization_id=organization_id,
            source_id=source_id,
            profile_tool=profile_tool,
            agent_id=agent_id,
            agent_revision=agent_revision,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            payload=payload,
            target_record_id=target_record_id,
            enforce_target_revision=enforce_target_revision,
            registry=resolved_registry,
        )
        filed = SorFiledCommand(
            command_id=row.id,
            state=row.state,
            created=created,
        )
    if created:
        try:
            await spawn_sor_command(
                organization_id=organization_id,
                command_id=filed.command_id,
            )
        except Exception as error:  # noqa: BLE001 - recovery owns committed rows
            logger.error(
                "SOR command committed; spawn recovery remains pending "
                "command_id=%s error_type=%s",
                filed.command_id,
                type(error).__name__,
            )
    return filed


async def spawn_sor_command(*, organization_id: UUID, command_id: UUID) -> UUID:
    """Idempotently bind one committed command to its sole executor."""
    return await spawn_sor_bound_work(
        contract=SOR_COMMAND_WORK,
        organization_id=organization_id,
        work_id=command_id,
        workflow_name=SOR_COMMAND_WORKFLOW,
        params_name="command_id",
        idempotency_prefix="sor-command",
        eligible_source_states=SOR_COMMAND_SOURCE_STATES,
    )


async def spawn_unbound_sor_commands(*, limit: int = 100) -> int:
    """Recover commands committed before their spawn callback completed."""

    async def spawn(organization_id: UUID, command_id: UUID) -> UUID:
        return await spawn_sor_command(
            organization_id=organization_id,
            command_id=command_id,
        )

    spawned, failures = await spawn_unbound_sor_work(
        contract=SOR_COMMAND_WORK,
        spawn=spawn,
        eligible_source_states=SOR_COMMAND_SOURCE_STATES,
        limit=limit,
    )
    for command_id, error in failures:
        logger.error(
            "Could not spawn SOR command id=%s error_type=%s",
            command_id,
            type(error).__name__,
        )
    return spawned


async def cancel_sor_command(*, organization_id: UUID, command_id: UUID) -> bool:
    """Fence one command in the DB, then interrupt its exact durable task."""
    async with start_transaction() as session:
        work = SorBoundWorkService(SOR_COMMAND_WORK, session)
        row = await work.get(
            work_id=command_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_COMMAND_WORK.terminal:
            return False
        task_id = row.absurd_task_id
        if row.state is SorCommandState.PENDING and row.mutation_applied_at is None:
            cancelled, _ = await work.cancel(
                work_id=command_id,
                organization_id=organization_id,
            )
            row.safe_error_category = None
            row.safe_error_summary = None
            await session.flush()
        elif row.state in {SorCommandState.PENDING, SorCommandState.RUNNING}:
            _terminalize_interrupted_command(row)
            await session.flush()
            cancelled = True
        else:
            raise SorConflictError("SOR command cannot be cancelled from this state.")
    if cancelled:
        await _notify_command_cancellation(
            organization_id=organization_id,
            command_id=command_id,
            task_id=task_id,
        )
    return cancelled


def _terminalize_interrupted_command(row: SorCommandModel) -> None:
    """Persist the safest known outcome before relying on worker cooperation."""
    mutation_applied = row.mutation_applied_at is not None
    row.state = SorCommandState.FAILED
    row.safe_error_category = (
        "POST_WRITE_CANCELLED" if mutation_applied else "MUTATION_OUTCOME_UNKNOWN"
    )
    row.safe_error_summary = (
        "Vendor mutation completed, but result projection was cancelled."
        if mutation_applied
        else "Command cancellation interrupted an unconfirmed vendor mutation."
    )
    row.finished_at = datetime.now(timezone.utc)


async def _notify_command_cancellation(
    *,
    organization_id: UUID,
    command_id: UUID,
    task_id: UUID | None,
) -> None:
    """Best-effort wake the Agent and stop work after the DB fence commits."""
    runtime = PlatformDurableRuntime()
    try:
        try:
            await runtime.emit_event(
                event_name=sor_command_terminal_event(command_id),
                payload=_terminal_event_payload(
                    organization_id=organization_id,
                    command_id=command_id,
                ),
            )
        except Exception as error:  # noqa: BLE001 - DB terminal state is authoritative
            logger.error(
                "Could not emit SOR command terminal event after cancellation "
                "command_id=%s error_type=%s",
                command_id,
                type(error).__name__,
            )
        if task_id is not None:
            try:
                await runtime.cancel_task(task_id)
            except Exception as error:  # noqa: BLE001 - DB fence still blocks projection
                logger.error(
                    "Could not cancel SOR durable task after command cancellation "
                    "command_id=%s task_id=%s error_type=%s",
                    command_id,
                    task_id,
                    type(error).__name__,
                )
    finally:
        try:
            await runtime.close()
        except Exception as error:  # noqa: BLE001 - committed cancellation must remain
            logger.error(
                "Could not close SOR durable runtime after command cancellation "
                "command_id=%s error_type=%s",
                command_id,
                type(error).__name__,
            )


async def cancel_active_sor_commands(
    *,
    organization_id: UUID,
    source_id: UUID,
    agent_id: UUID | None = None,
) -> int:
    """Best-effort cancel active commands under one revoked source authority."""
    predicates = [
        SorCommandModel.organization_id == organization_id,
        SorCommandModel.source_id == source_id,
        SorCommandModel.state.in_((SorCommandState.PENDING, SorCommandState.RUNNING)),
        SorCommandModel.deleted.is_(False),
    ]
    if agent_id is not None:
        predicates.append(SorCommandModel.agent_id == agent_id)
    try:
        async with start_transaction(ro=True) as session:
            command_ids = tuple(
                (
                    await session.scalars(
                        select(SorCommandModel.id)
                        .where(*predicates)
                        .order_by(
                            SorCommandModel.created_at.asc(),
                            SorCommandModel.id.asc(),
                        )
                    )
                ).all()
            )
    except Exception as error:  # noqa: BLE001 - revocation already committed
        logger.error(
            "Could not resolve SOR commands after authority revocation "
            "source_id=%s error_type=%s",
            source_id,
            type(error).__name__,
        )
        return 0
    cancelled = 0
    for active_command_id in command_ids:
        try:
            if await cancel_sor_command(
                organization_id=organization_id,
                command_id=active_command_id,
            ):
                cancelled += 1
        except Exception as error:  # noqa: BLE001 - revocation already committed
            logger.error(
                "Could not cancel SOR command after authority revocation "
                "command_id=%s error_type=%s",
                active_command_id,
                type(error).__name__,
            )
    return cancelled


def sor_command_terminal_event(command_id: UUID) -> str:
    """Return the stable Absurd event name for one command receipt."""
    return f"sor-command:{command_id}:terminal"


class SorCommandWorkflow:
    """Execute one external mutation once, then project its authoritative result."""

    def __init__(self, *, registry: SorRegistry | None = None) -> None:
        self.registry = registry or get_sor_registry()

    async def execute(
        self,
        params: dict[str, Any],
        task_context: AsyncTaskContext,
    ) -> dict[str, Any]:
        organization_id, command_id = _parse_params(params)
        try:
            receipt = await self._execute(
                organization_id=organization_id,
                command_id=command_id,
                task_context=task_context,
            )
        except CancelledTask:
            receipt = await _record_cancellation(
                organization_id=organization_id,
                command_id=command_id,
            )
            if receipt.terminal:
                await task_context.emit_event(
                    sor_command_terminal_event(command_id),
                    _terminal_event_payload(
                        organization_id=organization_id,
                        command_id=command_id,
                    ),
                )
            raise
        if receipt.terminal:
            await task_context.emit_event(
                sor_command_terminal_event(command_id),
                _terminal_event_payload(
                    organization_id=organization_id,
                    command_id=command_id,
                ),
            )
        return receipt.model_dump(mode="json")

    async def _execute(
        self,
        *,
        organization_id: UUID,
        command_id: UUID,
        task_context: AsyncTaskContext,
    ) -> SorCommandReceipt:
        try:
            claim = await _begin_command(
                organization_id=organization_id,
                command_id=command_id,
                registry=self.registry,
            )
            if claim is None:
                return await _read_receipt(
                    organization_id=organization_id,
                    command_id=command_id,
                )

            if not claim.mutation_applied:
                async with acquire_source_adapter(
                    organization_id=organization_id,
                    source_id=claim.source_id,
                    registry=self.registry,
                    invocation_budget_seconds=60.0,
                ) as adapter:
                    claim = await _load_claim(
                        organization_id=organization_id,
                        command_id=command_id,
                        registry=self.registry,
                        require_live_authority=True,
                    )
                    await _require_target_version(
                        claim=claim,
                        adapter=adapter,
                        task_context=task_context,
                    )
                    encoded_result = await task_context.step(
                        f"sor-command:{command_id}:vendor-write:v1",
                        lambda: run_with_durable_heartbeat(
                            task_context,
                            lambda: _execute_vendor_command(
                                adapter=adapter,
                                claim=claim,
                            ),
                        ),
                    )
                    result = _decode_command_result(encoded_result)
                    _require_expected_result_stream(claim=claim, result=result)
                    await _checkpoint_mutation(
                        organization_id=organization_id,
                        command_id=command_id,
                        result=result,
                    )
            else:
                if claim.mutation_result is None:
                    raise SorProjectionError(
                        "Applied SOR command has no durable mutation result."
                    )
                result = claim.mutation_result
                _require_expected_result_stream(claim=claim, result=result)

            # A mutation checkpoint is not continuing authority. Re-resolve the
            # live grant, run, source, and connection before the vendor read and
            # canonical projection. This also forces a fresh credential edge.
            claim = await _load_claim(
                organization_id=organization_id,
                command_id=command_id,
                registry=self.registry,
                require_live_authority=True,
            )
            async with acquire_source_adapter(
                organization_id=organization_id,
                source_id=claim.source_id,
                registry=self.registry,
                invocation_budget_seconds=60.0,
            ) as adapter:
                encoded_record = await task_context.step(
                    f"sor-command:{command_id}:read-after-write:v1",
                    lambda: run_with_durable_heartbeat(
                        task_context,
                        lambda: _fetch_result_record(adapter=adapter, result=result),
                    ),
                )
                record = decode_external_record(encoded_record)
                if (
                    record.vendor_object_key != result.vendor_object_key
                    or record.external_id != result.external_id
                ):
                    raise SorProjectionError(
                        "SOR read-after-write returned a different source identity."
                    )
                return await _project_and_complete(
                    organization_id=organization_id,
                    command_id=command_id,
                    source_id=claim.source_id,
                    record=record,
                    result=result,
                    result_vendor_object_key=claim.result_vendor_object_key,
                    adapter=adapter,
                )
        except SorWorkBindingPending:
            raise
        except Exception as error:  # noqa: BLE001 - project failure into receipt
            return await _handle_failure(
                organization_id=organization_id,
                command_id=command_id,
                error=error,
            )


async def _create_command(
    *,
    session,
    organization_id: UUID,
    source_id: UUID,
    profile_tool: str,
    agent_id: UUID,
    agent_revision: int,
    agent_run_id: UUID,
    tool_call_id: str,
    payload: SorCommandPayload,
    target_record_id: UUID | None,
    enforce_target_revision: bool,
    registry: SorRegistry,
) -> tuple[SorCommandModel, bool]:
    normalized_tool_call_id = tool_call_id.strip()
    if not 1 <= len(normalized_tool_call_id) <= 320:
        raise SorConfigurationError("SOR tool call ID is invalid.")
    wire_payload = payload.to_wire()
    _canonical_json(wire_payload, maximum=SOR_COMMAND_MAX_PAYLOAD_BYTES)
    idempotency_key = f"sor-command:v1:{agent_run_id}:{normalized_tool_call_id}"
    stable_intent = {
        "organization_id": str(organization_id),
        "source_id": str(source_id),
        "profile_tool": profile_tool,
        "agent_id": str(agent_id),
        "agent_revision": agent_revision,
        "agent_run_id": str(agent_run_id),
        "tool_call_id": normalized_tool_call_id,
        "target_record_id": str(target_record_id) if target_record_id else None,
        "enforce_target_revision": enforce_target_revision,
        "payload": wire_payload,
    }
    request_hash = hashlib.sha256(
        _canonical_json(stable_intent, maximum=SOR_COMMAND_MAX_PAYLOAD_BYTES)
    ).hexdigest()
    existing = await SorRepository(session).get_command_by_idempotency(
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        for_update=True,
    )
    if existing is not None:
        _require_same_command(existing, request_hash=request_hash)
        return existing, False

    repository = SorRepository(session)
    source_hint = await repository.get_source(
        organization_id=organization_id,
        source_id=source_id,
    )
    if source_hint is None:
        raise SorNotFoundError("SOR source not found.")
    connection = await _require_live_connection(
        repository=repository,
        organization_id=organization_id,
        source=source_hint,
        for_update=True,
    )
    source = await repository.get_source(
        organization_id=organization_id,
        source_id=source_id,
        for_update=True,
    )
    if source is None or source.external_connection_id != connection.id:
        raise SorNotFoundError("SOR source not found.")
    if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
        raise SorConfigurationError("SOR source is not ready for Agent commands.")
    if source.active_mapping_revision_id is None:
        raise SorConfigurationError("SOR source has no published mapping.")
    tool = _mutation_tool(
        registry=registry,
        profile=source.profile,
        name=profile_tool,
    )
    command_payload = validate_command_payload(
        profile=source.profile,
        tool_name=profile_tool,
        value=payload,
    )
    wire_payload = command_payload.to_wire()
    manifest = registry.get_manifest(
        profile=source.profile,
        vendor_key=source.vendor_key,
    )
    if profile_tool not in manifest.writable_tools:
        raise SorConfigurationError(
            "SOR source adapter does not execute this mutation tool."
        )
    await _require_command_result_stream(
        repository=SorRepository(session),
        organization_id=organization_id,
        source=source,
        manifest=manifest,
        profile_tool=profile_tool,
    )
    await _require_tool_scopes(
        repository=repository,
        organization_id=organization_id,
        source=source,
        manifest=manifest,
        profile_tool=profile_tool,
        connection=connection,
    )
    if tool.effect is not SorToolEffect.MUTATION:
        raise SorConfigurationError("SOR read tools cannot create command receipts.")

    grant = await session.scalar(
        select(SorSourceGrantModel)
        .where(
            SorSourceGrantModel.organization_id == organization_id,
            SorSourceGrantModel.source_id == source_id,
            SorSourceGrantModel.agent_id == agent_id,
            SorSourceGrantModel.access == SorSourceAccess.READ_WRITE,
            SorSourceGrantModel.deleted.is_(False),
        )
        .with_for_update()
    )
    if grant is None:
        raise SorCommandAuthorizationError(
            SorCommandFailure.SOURCE_GRANT_UNAVAILABLE,
            "Agent has no live read-write grant for this source.",
        )
    await _require_agent_authority(
        session=session,
        organization_id=organization_id,
        source_id=source_id,
        agent_id=agent_id,
        agent_revision=agent_revision,
        agent_run_id=agent_run_id,
        profile_tool=profile_tool,
        grant=grant,
        command_id=None,
    )

    target = None
    if target_record_id is not None:
        target = await session.scalar(
            select(SorRecordModel)
            .where(
                SorRecordModel.id == target_record_id,
                SorRecordModel.organization_id == organization_id,
                SorRecordModel.source_id == source_id,
                SorRecordModel.profile == source.profile,
                SorRecordModel.tombstoned_at.is_(None),
                SorRecordModel.deleted.is_(False),
            )
            .with_for_update()
        )
        if target is None:
            raise SorNotFoundError("SOR target record not found.")
        if target.canonical_entity_kind != tool.primary_entity:
            raise SorConfigurationError(
                "SOR target record does not match the mutation tool's entity."
            )
    if enforce_target_revision and target is None:
        raise SorConfigurationError(
            "Revision-protected SOR commands require a target record."
        )
    expected_revision = _record_version(target) if enforce_target_revision else None
    target_external_id = target.vendor_external_id if target is not None else None
    command_id = UUID(str(uuid_utils.uuid7()))
    request_payload = encrypt_json_payload(
        {
            "payload": wire_payload,
            "target_vendor_object_key": (
                target.vendor_object_key if target is not None else None
            ),
            "target_external_id": target_external_id,
        },
        organization_id=organization_id,
        resource_id=command_id,
        purpose="command-request",
        maximum_bytes=SOR_COMMAND_MAX_PAYLOAD_BYTES,
    )
    inserted_id = await session.scalar(
        insert(SorCommandModel)
        .values(
            id=command_id,
            organization_id=organization_id,
            source_id=source_id,
            profile=source.profile,
            profile_tool=profile_tool,
            agent_id=agent_id,
            agent_revision=agent_revision,
            agent_run_id=agent_run_id,
            tool_call_id=normalized_tool_call_id,
            source_grant_id=grant.id,
            source_grant_revision=grant.revision,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_payload=request_payload,
            target_record_id=target_record_id,
            expected_source_revision=expected_revision,
            state=SorCommandState.PENDING,
            attempts=0,
            max_attempts=3,
            deleted=False,
        )
        .on_conflict_do_nothing()
        .returning(SorCommandModel.id)
    )
    if inserted_id is not None:
        row = await SorRepository(session).get_command(
            organization_id=organization_id,
            command_id=inserted_id,
        )
        if row is None:
            raise SorConflictError("SOR command insert was not readable.")
        return row, True
    existing = await SorRepository(session).get_command_by_idempotency(
        organization_id=organization_id,
        idempotency_key=idempotency_key,
        for_update=True,
    )
    if existing is None:
        raise SorConflictError("SOR command identity conflicted.")
    _require_same_command(existing, request_hash=request_hash)
    return existing, False


async def _require_agent_authority(
    *,
    session,
    organization_id: UUID,
    source_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    agent_run_id: UUID,
    profile_tool: str,
    grant: SorSourceGrantModel,
    command_id: UUID | None,
) -> None:
    revision = await session.scalar(
        select(AgentRevisionModel).where(
            AgentRevisionModel.organization_id == organization_id,
            AgentRevisionModel.agent_id == agent_id,
            AgentRevisionModel.revision == agent_revision,
            AgentRevisionModel.availability == RevisionAvailability.PUBLISHED.value,
            AgentRevisionModel.deleted.is_(False),
        )
    )
    if revision is None:
        raise SorCommandAuthorizationError(
            SorCommandFailure.AGENT_REVISION_UNAVAILABLE,
            "The pinned Agent revision cannot execute source commands.",
        )
    revision_tool = await session.scalar(
        select(AgentRevisionToolModel.id).where(
            AgentRevisionToolModel.organization_id == organization_id,
            AgentRevisionToolModel.agent_id == agent_id,
            AgentRevisionToolModel.agent_revision == agent_revision,
            AgentRevisionToolModel.tool_id
            == system_tool_id(profile_tool, organization_id),
            AgentRevisionToolModel.deleted.is_(False),
        )
    )
    if revision_tool is None:
        raise SorCommandAuthorizationError(
            SorCommandFailure.AGENT_REVISION_TOOL_UNAVAILABLE,
            "The pinned Agent revision has no matching source tool.",
        )
    revision_grant = await session.scalar(
        select(SorAgentRevisionSourceGrantModel).where(
            SorAgentRevisionSourceGrantModel.organization_id == organization_id,
            SorAgentRevisionSourceGrantModel.agent_id == agent_id,
            SorAgentRevisionSourceGrantModel.agent_revision == agent_revision,
            SorAgentRevisionSourceGrantModel.source_id == source_id,
            SorAgentRevisionSourceGrantModel.source_grant_id == grant.id,
            SorAgentRevisionSourceGrantModel.source_grant_revision == grant.revision,
            SorAgentRevisionSourceGrantModel.access == SorSourceAccess.READ_WRITE,
            SorAgentRevisionSourceGrantModel.deleted.is_(False),
        )
    )
    if revision_grant is None:
        raise SorCommandAuthorizationError(
            SorCommandFailure.AGENT_REVISION_SOURCE_UNAVAILABLE,
            "The pinned Agent revision has no matching source grant.",
        )
    lifecycle_predicate = AgentRunModel.lifecycle == AgentRunLifecycle.RUNNING
    if command_id is not None:
        lifecycle_predicate = or_(
            lifecycle_predicate,
            and_(
                AgentRunModel.lifecycle == AgentRunLifecycle.WAITING_FOR_TOOL,
                AgentRunModel.waiting_tool_owner_kind == SOR_COMMAND_WAIT_OWNER_KIND,
                AgentRunModel.waiting_tool_owner_id == command_id,
            ),
        )
    run = await session.scalar(
        select(AgentRunModel).where(
            AgentRunModel.organization_id == organization_id,
            AgentRunModel.id == agent_run_id,
            AgentRunModel.agent_id == agent_id,
            AgentRunModel.agent_revision == agent_revision,
            lifecycle_predicate,
            AgentRunModel.cancellation_requested_at.is_(None),
            AgentRunModel.deleted.is_(False),
        )
    )
    if run is None:
        raise SorCommandAuthorizationError(
            SorCommandFailure.AGENT_RUN_NOT_RUNNING,
            "The Agent run no longer permits a new source mutation.",
        )


async def _begin_command(
    *,
    organization_id: UUID,
    command_id: UUID,
    registry: SorRegistry,
) -> _CommandClaim | None:
    async with start_transaction() as session:
        row = await SorBoundWorkService(SOR_COMMAND_WORK, session).begin_attempt(
            work_id=command_id,
            organization_id=organization_id,
        )
        if row.state in SOR_COMMAND_WORK.terminal:
            return None
    return await _load_claim(
        organization_id=organization_id,
        command_id=command_id,
        registry=registry,
        require_live_authority=True,
    )


async def _load_claim(
    *,
    organization_id: UUID,
    command_id: UUID,
    registry: SorRegistry,
    require_live_authority: bool,
) -> _CommandClaim:
    async with start_transaction(ro=True) as session:
        repository = SorRepository(session)
        row = await repository.get_command(
            organization_id=organization_id,
            command_id=command_id,
        )
        if row is None:
            raise SorNotFoundError("SOR command not found.")
        source = await repository.get_source(
            organization_id=organization_id,
            source_id=row.source_id,
        )
        if source is None:
            raise SorNotFoundError("SOR command source not found.")
        _mutation_tool(
            registry=registry,
            profile=row.profile,
            name=row.profile_tool,
        )
        manifest = registry.get_manifest(
            profile=row.profile,
            vendor_key=source.vendor_key,
        )
        if row.profile_tool not in manifest.writable_tools:
            raise SorCommandAuthorizationError(
                SorCommandFailure.SOURCE_TOOL_UNAVAILABLE,
                "The source adapter no longer executes this mutation tool.",
            )
        result_vendor_object_key = await _require_command_result_stream(
            repository=repository,
            organization_id=organization_id,
            source=source,
            manifest=manifest,
            profile_tool=row.profile_tool,
        )
        await _require_tool_scopes(
            repository=repository,
            organization_id=organization_id,
            source=source,
            manifest=manifest,
            profile_tool=row.profile_tool,
        )
        if require_live_authority:
            if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
                raise SorCommandAuthorizationError(
                    SorCommandFailure.SOURCE_NOT_ACTIVE,
                    "The source no longer permits Agent commands.",
                )
            grant = await repository.get_source_grant(
                organization_id=organization_id,
                source_id=row.source_id,
                grant_id=row.source_grant_id,
            )
            if (
                grant is None
                or grant.agent_id != row.agent_id
                or grant.revision != row.source_grant_revision
                or grant.access is not SorSourceAccess.READ_WRITE
            ):
                raise SorCommandAuthorizationError(
                    SorCommandFailure.SOURCE_GRANT_REVOKED,
                    "The Agent source grant was revoked or changed.",
                )
            await _require_agent_authority(
                session=session,
                organization_id=organization_id,
                source_id=row.source_id,
                agent_id=row.agent_id,
                agent_revision=row.agent_revision,
                agent_run_id=row.agent_run_id,
                profile_tool=row.profile_tool,
                grant=grant,
                command_id=command_id,
            )
        request = decrypt_json_payload(
            row.request_payload,
            organization_id=organization_id,
            resource_id=command_id,
            purpose="command-request",
            maximum_bytes=SOR_COMMAND_MAX_PAYLOAD_BYTES,
        )
        payload_wire = request.get("payload")
        if not isinstance(payload_wire, dict) or not all(
            isinstance(key, str) for key in payload_wire
        ):
            raise SorSecretEnvelopeError("SOR command payload is malformed.")
        payload = validate_command_payload(
            profile=row.profile,
            tool_name=row.profile_tool,
            value=payload_wire,
        )
        object_key = request.get("target_vendor_object_key")
        external_id = request.get("target_external_id")
        if object_key is not None and not isinstance(object_key, str):
            raise SorSecretEnvelopeError("SOR command target object is malformed.")
        if external_id is not None and not isinstance(external_id, str):
            raise SorSecretEnvelopeError("SOR command target identity is malformed.")
        target_selected_payload = None
        if row.target_record_id is not None:
            target = await session.scalar(
                select(SorRecordModel).where(
                    SorRecordModel.id == row.target_record_id,
                    SorRecordModel.organization_id == organization_id,
                    SorRecordModel.source_id == row.source_id,
                    SorRecordModel.deleted.is_(False),
                )
            )
            if target is None:
                raise SorNotFoundError("SOR command target record not found.")
            if (
                object_key != target.vendor_object_key
                or external_id != target.vendor_external_id
            ):
                raise SorSecretEnvelopeError(
                    "SOR command target does not match its canonical record."
                )
            target_selected_payload = SorSourcePayload.from_mapping(
                target.selected_raw_payload
            )
        mutation_result = (
            _decode_stored_result(row.safe_result)
            if row.mutation_applied_at is not None
            else None
        )
        return _CommandClaim(
            organization_id=organization_id,
            command_id=command_id,
            source_id=row.source_id,
            profile=row.profile,
            vendor_key=source.vendor_key,
            profile_tool=row.profile_tool,
            idempotency_key=row.idempotency_key,
            payload=payload,
            target_vendor_object_key=object_key,
            target_external_id=external_id,
            expected_source_revision=row.expected_source_revision,
            target_selected_payload=target_selected_payload,
            result_vendor_object_key=result_vendor_object_key,
            supports_conditional_writes=manifest.supports_conditional_writes,
            mutation_applied=row.mutation_applied_at is not None,
            mutation_result=mutation_result,
        )


async def _require_target_version(
    *,
    claim: _CommandClaim,
    adapter: SorLifecycleAdapter,
    task_context: AsyncTaskContext,
) -> None:
    if claim.expected_source_revision is None:
        return
    if claim.target_vendor_object_key is None or claim.target_external_id is None:
        raise SorProjectionError("Versioned SOR command has no target identity.")
    current = await run_with_durable_heartbeat(
        task_context,
        lambda: adapter.fetch_record(
            vendor_object_key=claim.target_vendor_object_key,
            external_id=claim.target_external_id,
        ),
    )
    if not isinstance(current, SorExternalRecord):
        raise SorProjectionError("SOR adapter returned an invalid target record.")
    if (
        _external_record_version(
            current,
            selected_payload=claim.target_selected_payload,
            expected=claim.expected_source_revision,
        )
        != claim.expected_source_revision
    ):
        raise SorCommandRevisionConflict(
            "The source record changed after the Agent read it."
        )


async def _execute_vendor_command(
    *, adapter: SorLifecycleAdapter, claim: _CommandClaim
) -> dict[str, JsonValue]:
    expected_revision = claim.expected_source_revision
    if (
        not claim.supports_conditional_writes
        or expected_revision is not None
        and expected_revision.startswith("hash:")
    ):
        expected_revision = None
    result = await adapter.execute_command(
        SorCommandRequest(
            tool_name=claim.profile_tool,
            idempotency_key=claim.idempotency_key,
            payload=claim.payload,
            target_external_id=claim.target_external_id,
            expected_source_revision=expected_revision,
        )
    )
    return _encode_command_result(result)


async def _checkpoint_mutation(
    *,
    organization_id: UUID,
    command_id: UUID,
    result: SorCommandResult,
) -> None:
    safe_result = _stored_result(result)
    _canonical_json(safe_result, maximum=SOR_COMMAND_MAX_SAFE_RESULT_BYTES)
    async with start_transaction() as session:
        row = await SorBoundWorkService(SOR_COMMAND_WORK, session).get(
            work_id=command_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state is not SorCommandState.RUNNING:
            raise SorConflictError("SOR command cannot checkpoint a vendor mutation.")
        if row.mutation_applied_at is not None:
            if row.safe_result != safe_result:
                raise SorConflictError("SOR command mutation result changed on retry.")
            return
        row.safe_result = safe_result
        row.external_request_id = result.external_request_id
        row.source_revision_after = result.source_revision
        row.mutation_applied_at = datetime.now(timezone.utc)
        await session.flush()


async def _fetch_result_record(
    *,
    adapter: SorLifecycleAdapter,
    result: SorCommandResult,
) -> dict[str, JsonValue]:
    record = await adapter.fetch_record(
        vendor_object_key=result.vendor_object_key,
        external_id=result.external_id,
    )
    return encode_external_record(record)


async def _project_and_complete(
    *,
    organization_id: UUID,
    command_id: UUID,
    source_id: UUID,
    record: SorExternalRecord,
    result: SorCommandResult,
    result_vendor_object_key: str,
    adapter: SorLifecycleAdapter,
) -> SorCommandReceipt:
    async with start_transaction() as session:
        repository = SorRepository(session)
        work = SorBoundWorkService(SOR_COMMAND_WORK, session)
        command = await work.get(
            work_id=command_id,
            organization_id=organization_id,
            for_update=True,
        )
        if command.state is not SorCommandState.RUNNING:
            raise SorConflictError("SOR command is no longer running.")
        if command.source_id != source_id:
            raise SorConflictError("SOR command source identity changed.")
        source_hint = await repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
        )
        if source_hint is None:
            raise SorConfigurationError("SOR command source is unavailable.")
        connection = await _require_live_connection(
            repository=repository,
            organization_id=organization_id,
            source=source_hint,
            for_update=True,
        )
        source = await repository.get_source(
            organization_id=organization_id,
            source_id=source_id,
            for_update=True,
        )
        if source is None or source.external_connection_id != connection.id:
            raise SorCommandAuthorizationError(
                SorCommandFailure.SOURCE_CONNECTION_UNAVAILABLE,
                "The source connection changed during command projection.",
            )
        stream = await repository.get_stream_by_object(
            organization_id=organization_id,
            source_id=source_id,
            vendor_object_key=result_vendor_object_key,
            for_update=True,
        )
        if stream is None:
            raise SorConfigurationError(
                "SOR command result has no configured projection stream."
            )
        if source.state not in {SorSourceState.ACTIVE, SorSourceState.DEGRADED}:
            raise SorCommandAuthorizationError(
                SorCommandFailure.SOURCE_NOT_ACTIVE,
                "The source no longer permits Agent commands.",
            )
        grant = await repository.get_source_grant(
            organization_id=organization_id,
            source_id=source_id,
            grant_id=command.source_grant_id,
        )
        if (
            grant is None
            or grant.agent_id != command.agent_id
            or grant.revision != command.source_grant_revision
            or grant.access is not SorSourceAccess.READ_WRITE
        ):
            raise SorCommandAuthorizationError(
                SorCommandFailure.SOURCE_GRANT_REVOKED,
                "The Agent source grant was revoked or changed.",
            )
        await _require_agent_authority(
            session=session,
            organization_id=organization_id,
            source_id=source_id,
            agent_id=command.agent_id,
            agent_revision=command.agent_revision,
            agent_run_id=command.agent_run_id,
            profile_tool=command.profile_tool,
            grant=grant,
            command_id=command_id,
        )
        if record.vendor_object_key != result_vendor_object_key:
            raise SorProjectionError(
                "SOR command result does not match its declared projection stream."
            )
        outcome = await project_source_record(
            session,
            organization_id=organization_id,
            source=source,
            stream=stream,
            adapter=adapter,
            record=record,
            sync_run_id=None,
        )
        safe_result = {
            **_stored_result(result),
            "record_id": str(outcome.record_id),
            "projection": outcome.disposition.value,
            "source_revision": record.source_revision,
            "source_url": record.source_url or result.source_url,
        }
        _canonical_json(safe_result, maximum=SOR_COMMAND_MAX_SAFE_RESULT_BYTES)
        row = await work.succeed(
            work_id=command_id,
            organization_id=organization_id,
            values=SorCommandCompletion(
                safe_result=safe_result,
                source_revision_after=record.source_revision,
            ),
        )
        action_event_id = await file_sor_action_event(
            session,
            command=row,
            source=source,
            result_record_id=outcome.record_id,
            projection=outcome.disposition,
            source_revision=record.source_revision,
        )
        if action_event_id is not None:
            safe_result = {
                **safe_result,
                "durable_event_id": str(action_event_id),
            }
            _canonical_json(safe_result, maximum=SOR_COMMAND_MAX_SAFE_RESULT_BYTES)
            row.safe_result = safe_result
            await session.flush()
        return _receipt(row)


async def _record_cancellation(
    *,
    organization_id: UUID,
    command_id: UUID,
) -> SorCommandReceipt:
    async with start_transaction() as session:
        work = SorBoundWorkService(SOR_COMMAND_WORK, session)
        row = await work.get(
            work_id=command_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_COMMAND_WORK.terminal:
            return _receipt(row)
        error_code = (
            "POST_WRITE_CANCELLED"
            if row.mutation_applied_at is not None
            else "MUTATION_OUTCOME_UNKNOWN"
        )
        summary = (
            "Vendor mutation completed, but result projection was cancelled."
            if row.mutation_applied_at is not None
            else "Command cancellation interrupted an unconfirmed vendor mutation."
        )
        await work.fail(
            work_id=command_id,
            organization_id=organization_id,
            error_code=error_code,
            error_summary=summary,
            permanent=True,
        )
        return _receipt(row)


async def _handle_failure(
    *,
    organization_id: UUID,
    command_id: UUID,
    error: Exception,
) -> SorCommandReceipt:
    async with start_transaction() as session:
        work = SorBoundWorkService(SOR_COMMAND_WORK, session)
        row = await work.get(
            work_id=command_id,
            organization_id=organization_id,
            for_update=True,
        )
        if row.state in SOR_COMMAND_WORK.terminal:
            return _receipt(row)
        if isinstance(error, SorCommandRevisionConflict):
            if row.mutation_applied_at is not None:
                raise SorConflictError(
                    "A completed vendor mutation cannot become a revision conflict."
                ) from error
            row = await work.finish_as(
                work_id=command_id,
                organization_id=organization_id,
                state=SorCommandState.CONFLICT,
                error_code=SorCommandFailure.SOURCE_REVISION_CONFLICT,
                error_summary=str(error),
            )
            return _receipt(row)
        code, summary, permanent = _classify_failure(error)
        state = await work.fail(
            work_id=command_id,
            organization_id=organization_id,
            error_code=code,
            error_summary=summary,
            permanent=permanent,
        )
        receipt = _receipt(row)
    if state is SorCommandState.PENDING:
        raise error
    logger.warning("SOR command failed id=%s code=%s", command_id, code)
    return receipt


def _classify_failure(error: Exception) -> tuple[str, str, bool]:
    if isinstance(error, ValidationError):
        error = SorProjectionError("SOR adapter returned an invalid typed contract.")
    if isinstance(error, SorCommandAuthorizationError):
        return error.code, str(error), True
    if isinstance(error, SorAdapterUnavailableError):
        return error.error_code, str(error), error.requires_reauthorization
    if isinstance(error, SorVendorOperationError):
        return (
            error.code.value,
            str(error),
            error.recovery
            in {
                SorRecoveryPolicy.TERMINAL,
                SorRecoveryPolicy.REAUTH_REQUIRED,
                SorRecoveryPolicy.RECONCILE_REQUIRED,
            },
        )
    if isinstance(error, SorSecretEnvelopeError):
        return SorCommandFailure.COMMAND_PAYLOAD_INVALID, str(error), True
    if isinstance(error, (SorConfigurationError, SorConflictError, SorProjectionError)):
        return SorCommandFailure.COMMAND_CONTRACT_INVALID, str(error), True
    return (
        SorCommandFailure.COMMAND_PROVIDER_FAILED,
        "SOR provider command failed.",
        False,
    )


def _mutation_tool(
    *, registry: SorRegistry, profile: SorProfile, name: str
) -> SorToolSpec:
    spec = registry.get_profile(profile)
    tool = next((candidate for candidate in spec.tools if candidate.name == name), None)
    if tool is None:
        raise SorConfigurationError("Unknown SOR profile tool.")
    if tool.effect is not SorToolEffect.MUTATION:
        raise SorConfigurationError("SOR tool does not permit a mutation.")
    return tool


async def _require_tool_scopes(
    *,
    repository: SorRepository,
    organization_id: UUID,
    source: SorSourceModel,
    manifest: SorAdapterCapabilityManifest,
    profile_tool: str,
    connection: ExternalConnectionModel | None = None,
) -> None:
    active_connection = connection or await _require_live_connection(
        repository=repository,
        organization_id=organization_id,
        source=source,
    )
    required = set(manifest.tool_required_scopes.get(profile_tool, ()))
    granted = set(active_connection.granted_scopes or ())
    if not required.issubset(granted):
        raise SorCommandAuthorizationError(
            SorCommandFailure.SOURCE_TOOL_SCOPE_MISSING,
            "The source connection requires reauthorization for this action.",
        )


async def _require_live_connection(
    *,
    repository: SorRepository,
    organization_id: UUID,
    source: SorSourceModel,
    for_update: bool = False,
) -> ExternalConnectionModel:
    """Resolve the exact active organization connection for one source."""
    connection = await repository.get_connection(
        organization_id=organization_id,
        connection_id=source.external_connection_id,
        vendor_key=source.vendor_key,
        for_update=for_update,
    )
    if (
        connection is None
        or connection.owner_kind is not ConnectionOwnerKind.ORGANIZATION
        or connection.status is not ExternalConnectionStatus.ACTIVE
    ):
        raise SorCommandAuthorizationError(
            SorCommandFailure.SOURCE_CONNECTION_UNAVAILABLE,
            "The source connection was revoked or requires reauthorization.",
        )
    return connection


async def _require_command_result_stream(
    *,
    repository: SorRepository,
    organization_id: UUID,
    source: SorSourceModel,
    manifest: SorAdapterCapabilityManifest,
    profile_tool: str,
) -> str:
    """Refuse a vendor write unless its authoritative result can be projected."""
    result_stream = manifest.mutation_result_streams.get(profile_tool)
    if result_stream is None:
        raise SorConfigurationError(
            "SOR mutation tool has no declared result projection stream."
        )
    stream = await repository.get_stream_by_object(
        organization_id=organization_id,
        source_id=source.id,
        vendor_object_key=result_stream,
    )
    if stream is None:
        raise SorConfigurationError(
            "Select and synchronize the mutation result stream before using this tool."
        )
    if source.active_mapping_revision_id is None:
        raise SorConfigurationError("SOR source has no published mapping.")
    fields = await repository.list_field_mappings(
        organization_id=organization_id,
        source_id=source.id,
        mapping_revision_id=source.active_mapping_revision_id,
    )
    if not any(
        field.vendor_object_key == result_stream
        and field.direction is not SorFieldMappingDirection.IGNORE
        and field.state is SorFieldMappingState.ACTIVE
        for field in fields
    ):
        raise SorConfigurationError(
            "The mutation result stream has no active projection mapping."
        )
    return result_stream


def _require_expected_result_stream(
    *,
    claim: _CommandClaim,
    result: SorCommandResult,
) -> None:
    """Catch an adapter result-contract defect before durable checkpointing."""
    if result.vendor_object_key != claim.result_vendor_object_key:
        raise SorProjectionError(
            "SOR adapter returned an undeclared mutation result stream."
        )


def _record_version(record: SorRecordModel | None) -> str | None:
    if record is None:
        return None
    return record.source_revision or f"hash:{record.payload_hash}"


def _external_record_version(
    record: SorExternalRecord,
    *,
    selected_payload: SorSourcePayload | None,
    expected: str,
) -> str:
    if not expected.startswith("hash:"):
        if not record.source_revision:
            return "missing-source-revision"
        return record.source_revision
    if selected_payload is None:
        raise SorProjectionError("Hash-versioned SOR command lost its target fields.")
    current = {
        key: record.payload.value(key) if record.payload.has_field(key) else None
        for key in selected_payload.field_names()
    }
    payload = _canonical_json(current, maximum=SOR_COMMAND_MAX_PAYLOAD_BYTES)
    return f"hash:{hashlib.sha256(payload).hexdigest()}"


def _encode_command_result(result: SorCommandResult) -> dict[str, JsonValue]:
    if not isinstance(result, SorCommandResult):
        raise SorProjectionError("SOR adapter returned an invalid command result.")
    encoded = _stored_result(result)
    _canonical_json(encoded, maximum=SOR_COMMAND_MAX_SAFE_RESULT_BYTES)
    return encoded


def _decode_command_result(value: object) -> SorCommandResult:
    try:
        return SorStoredCommandResult.model_validate(value).to_result()
    except ValidationError as error:
        raise SorProjectionError("Durable SOR command result is malformed.") from error


def _stored_result(result: SorCommandResult) -> dict[str, JsonValue]:
    return SorStoredCommandResult.from_result(result).model_dump(mode="json")


def _decode_stored_result(value: object) -> SorCommandResult:
    return _decode_command_result(value)


def _require_same_command(row: SorCommandModel, *, request_hash: str) -> None:
    if row.request_hash != request_hash:
        raise SorConflictError(
            "SOR command idempotency key was reused for a different request."
        )


async def _read_receipt(
    *,
    organization_id: UUID,
    command_id: UUID,
) -> SorCommandReceipt:
    async with start_transaction(ro=True) as session:
        row = await SorBoundWorkService(SOR_COMMAND_WORK, session).get(
            work_id=command_id,
            organization_id=organization_id,
        )
        return _receipt(row)


async def read_sor_command_receipt(
    *,
    organization_id: UUID,
    command_id: UUID,
) -> SorCommandReceipt:
    """Load one organization-owned command receipt for durable tool resume."""
    return await _read_receipt(
        organization_id=organization_id,
        command_id=command_id,
    )


def _receipt(row: SorCommandModel) -> SorCommandReceipt:
    return SorCommandReceipt(
        organization_id=row.organization_id,
        command_id=row.id,
        source_id=row.source_id,
        agent_run_id=row.agent_run_id,
        tool_call_id=row.tool_call_id,
        profile_tool=row.profile_tool,
        state=row.state,
        mutation_applied=row.mutation_applied_at is not None,
        safe_result=row.safe_result,
        safe_error_category=row.safe_error_category,
        safe_error_summary=row.safe_error_summary,
    )


def _terminal_event_payload(
    *,
    organization_id: UUID,
    command_id: UUID,
) -> dict[str, str]:
    return {
        "organization_id": str(organization_id),
        "command_id": str(command_id),
    }


def _canonical_json(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SorConfigurationError(
            "SOR command values must be JSON-compatible."
        ) from error
    if len(encoded) > maximum:
        raise SorConfigurationError("SOR command value exceeds its size limit.")
    return encoded


def _parse_params(params: dict[str, Any]) -> tuple[UUID, UUID]:
    if set(params) != {"organization_id", "command_id"}:
        raise ValueError("SOR command task params must contain IDs only.")
    try:
        return UUID(str(params["organization_id"])), UUID(str(params["command_id"]))
    except (TypeError, ValueError) as error:
        raise ValueError("SOR command task params contain an invalid UUID.") from error


__all__ = [
    "SOR_COMMAND_MAX_PAYLOAD_BYTES",
    "SOR_COMMAND_WAIT_OWNER_KIND",
    "SOR_COMMAND_WORKFLOW",
    "SorCommandWorkflow",
    "SorCommandReceipt",
    "SorFiledCommand",
    "cancel_active_sor_commands",
    "cancel_sor_command",
    "file_sor_command",
    "read_sor_command_receipt",
    "register_sor_command_workflow",
    "sor_command_terminal_event",
    "spawn_sor_command",
    "spawn_unbound_sor_commands",
]
