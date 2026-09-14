"""Absurd-step bridge for one organization-owned external effect."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, Self, TypeVar, runtime_checkable
from uuid import UUID

from absurd_sdk import CancelledTask
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from eylo.common.database import start_transaction
from eylo.common.outbound import (
    OUTBOUND_FINAL_STATES,
    OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH,
    OUTBOUND_STATUS_CODE_MAX,
    OUTBOUND_STATUS_CODE_MIN,
    OutboundAttemptCancelled,
    OutboundAttemptSpec,
    OutboundAttemptState,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
    require_failure_code,
)
from eylo.pipelines.outbound.models import OutboundAttemptModel
from eylo.pipelines.outbound.service import OutboundAttemptService

T = TypeVar("T")
OutboundSender = Callable[
    [OutboundSendAuthorization],
    Awaitable[OutboundSendOutcome],
]
_SEND_OUTCOME_TYPES = (
    OutboundSendSucceeded,
    OutboundSendRetryable,
    OutboundSendTerminal,
    OutboundSendUnknown,
)
_UNKNOWN_AFTER_INTERRUPTION = "send_interrupted_unconfirmed"
_UNKNOWN_AFTER_EXCEPTION = "send_exception_unconfirmed"
_UNKNOWN_AFTER_REPLAY = "prior_send_unconfirmed"
_RECEIPT_MAX_SEND_COUNT = 100


@runtime_checkable
class CommandStepContext(Protocol):
    """Execute one product-owned command; this alone grants no event-wait ability."""

    async def step(
        self,
        *,
        key: str,
        version: int,
        operation: Callable[[], Awaitable[T]],
    ) -> T: ...


@runtime_checkable
class DurableStepContext(CommandStepContext, Protocol):
    """Absurd-backed command steps plus resumable event waits."""

    async def await_event(
        self,
        *,
        event_name: str,
        key: str,
        version: int,
    ) -> object: ...


class OutboundExecutionReceipt(BaseModel):
    """Bounded durable projection safe to checkpoint and show to product code."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    attempt_id: UUID
    state: OutboundAttemptState
    send_count: int = Field(ge=0, le=_RECEIPT_MAX_SEND_COUNT)
    cancel_requested: bool
    provider_reference: str | None
    status_code: int | None = Field(
        ge=OUTBOUND_STATUS_CODE_MIN, le=OUTBOUND_STATUS_CODE_MAX
    )
    failure_code: str | None

    @field_validator("attempt_id", mode="before")
    @classmethod
    def decode_attempt_id(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @field_validator("state", mode="before")
    @classmethod
    def decode_state(cls, value: object) -> object:
        return OutboundAttemptState(value) if isinstance(value, str) else value

    @field_validator("provider_reference")
    @classmethod
    def validate_provider_reference(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip()
            if (
                not normalized
                or normalized != value
                or len(normalized) > OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH
            ):
                raise ValueError("Outbound receipt provider reference is invalid.")
        return value

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str | None) -> str | None:
        if value is not None:
            require_failure_code(value)
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if not self._has_valid_lifecycle():
            raise ValueError("Outbound receipt lifecycle is invalid.")
        return self

    def _has_valid_lifecycle(self) -> bool:
        if self.state is OutboundAttemptState.PREPARED:
            return self.send_count == 0 and self.failure_code is None
        if self.state is OutboundAttemptState.IN_FLIGHT:
            return self.send_count > 0 and self.failure_code is None
        if self.state is OutboundAttemptState.SUCCEEDED:
            return self.send_count > 0 and self.failure_code is None
        if self.state is OutboundAttemptState.RETRYABLE:
            return self.send_count > 0 and self.failure_code is not None
        if self.state is OutboundAttemptState.TERMINAL:
            return self.failure_code is not None
        if self.state is OutboundAttemptState.UNKNOWN:
            return self.send_count > 0 and self.failure_code is not None
        return self.state is OutboundAttemptState.CANCELLED and self.cancel_requested

    @classmethod
    def from_model(cls, row: OutboundAttemptModel) -> OutboundExecutionReceipt:
        return cls(
            attempt_id=UUID(str(row.id)),
            state=row.state,
            send_count=row.send_count,
            cancel_requested=row.cancel_requested_at is not None,
            provider_reference=row.provider_reference,
            status_code=row.status_code,
            failure_code=row.failure_code,
        )

    def as_checkpoint(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")

    @classmethod
    def from_checkpoint(cls, value: object) -> OutboundExecutionReceipt:
        if not isinstance(value, dict):
            raise ValueError("Outbound checkpoint must be an object.")
        return cls.model_validate(value)


class OutboundRetryRequested(Exception):
    """Ask Absurd to retry after the provider explicitly allowed another send."""

    def __init__(self, receipt: OutboundExecutionReceipt) -> None:
        if receipt.state is not OutboundAttemptState.RETRYABLE:
            raise ValueError("Outbound retry requires a retryable receipt.")
        self.receipt = receipt
        super().__init__(
            f"Outbound provider requested retry: {receipt.failure_code or 'retryable'}."
        )


async def execute_outbound_attempt(
    *,
    spec: OutboundAttemptSpec,
    context: CommandStepContext,
    sender: OutboundSender,
) -> OutboundExecutionReceipt:
    """Prepare first, then let one Absurd step own send/checkpoint/retry."""
    await _prepare(spec)
    checkpoint = await context.step(
        key=f"outbound:{spec.identity.attempt_id}",
        version=1,
        operation=lambda: _execute_uncheckpointed(spec, sender),
    )
    receipt = OutboundExecutionReceipt.from_checkpoint(checkpoint)
    if receipt.attempt_id != spec.identity.attempt_id:
        raise ValueError("Outbound checkpoint belongs to a different attempt.")
    if receipt.state is OutboundAttemptState.RETRYABLE:
        raise OutboundRetryRequested(receipt)
    return receipt


async def record_outbound_preflight_failure(
    *,
    spec: OutboundAttemptSpec,
    failure_code: str,
) -> OutboundExecutionReceipt:
    """Persist a zero-send terminal failure after product intent is committed."""
    async with start_transaction() as session:
        service = OutboundAttemptService(session)
        row = await service.prepare(spec)
        row = await service.record_preflight_terminal(
            organization_id=spec.identity.organization_id,
            attempt_id=spec.identity.attempt_id,
            failure_code=failure_code,
        )
        return OutboundExecutionReceipt.from_model(row)


async def request_outbound_cancellation(
    *,
    organization_id: UUID,
    attempt_id: UUID,
) -> OutboundExecutionReceipt:
    """Fence future sends; the product owner separately cancels its Absurd task."""
    async with start_transaction() as session:
        row = await OutboundAttemptService(session).request_cancel(
            organization_id=organization_id,
            attempt_id=attempt_id,
        )
        return OutboundExecutionReceipt.from_model(row)


async def _prepare(spec: OutboundAttemptSpec) -> None:
    async with start_transaction() as session:
        await OutboundAttemptService(session).prepare(spec)


async def _execute_uncheckpointed(
    spec: OutboundAttemptSpec,
    sender: OutboundSender,
) -> dict[str, JsonValue]:
    receipt, authorization = await _authorize_or_recover(spec)
    if authorization is None:
        return receipt.as_checkpoint()

    try:
        outcome = await sender(authorization)
        if not isinstance(outcome, _SEND_OUTCOME_TYPES):
            raise TypeError("Outbound sender returned an unsupported outcome.")
        receipt = await _record_send_outcome(spec, outcome)
    except (CancelledTask, asyncio.CancelledError):
        await _recover_unknown_if_in_flight(
            spec,
            failure_code=_UNKNOWN_AFTER_INTERRUPTION,
        )
        raise
    except Exception:
        receipt = await _recover_unknown_if_in_flight(
            spec,
            failure_code=_UNKNOWN_AFTER_EXCEPTION,
        )

    if receipt.state is OutboundAttemptState.RETRYABLE:
        raise OutboundRetryRequested(receipt)
    return receipt.as_checkpoint()


async def _authorize_or_recover(
    spec: OutboundAttemptSpec,
) -> tuple[OutboundExecutionReceipt, OutboundSendAuthorization | None]:
    organization_id = spec.identity.organization_id
    attempt_id = spec.identity.attempt_id
    async with start_transaction() as session:
        service = OutboundAttemptService(session)
        row = await service.get(
            organization_id=organization_id,
            attempt_id=attempt_id,
            for_update=True,
        )
        if row.state is OutboundAttemptState.IN_FLIGHT:
            row = await service.recover_in_flight_as_unknown(
                organization_id=organization_id,
                attempt_id=attempt_id,
                failure_code=_UNKNOWN_AFTER_REPLAY,
            )
            return OutboundExecutionReceipt.from_model(row), None
        if (
            row.state in OUTBOUND_FINAL_STATES
            or row.state is OutboundAttemptState.UNKNOWN
        ):
            return OutboundExecutionReceipt.from_model(row), None
        try:
            row = await service.begin_send(
                organization_id=organization_id,
                attempt_id=attempt_id,
            )
        except OutboundAttemptCancelled:
            row = await service.get(
                organization_id=organization_id,
                attempt_id=attempt_id,
            )
            return OutboundExecutionReceipt.from_model(row), None
        return OutboundExecutionReceipt.from_model(row), OutboundSendAuthorization(
            attempt_id=attempt_id,
            provider_idempotency_key=row.provider_idempotency_key,
        )


async def _record_send_outcome(
    spec: OutboundAttemptSpec,
    outcome: OutboundSendOutcome,
) -> OutboundExecutionReceipt:
    async with start_transaction() as session:
        row = await OutboundAttemptService(session).record_outcome(
            organization_id=spec.identity.organization_id,
            attempt_id=spec.identity.attempt_id,
            state=outcome.state,
            provider_reference=outcome.provider_reference,
            status_code=outcome.status_code,
            failure_code=(
                None
                if isinstance(outcome, OutboundSendSucceeded)
                else outcome.failure_code
            ),
        )
        return OutboundExecutionReceipt.from_model(row)


async def _recover_unknown_if_in_flight(
    spec: OutboundAttemptSpec,
    *,
    failure_code: str,
) -> OutboundExecutionReceipt:
    async with start_transaction() as session:
        service = OutboundAttemptService(session)
        row = await service.get(
            organization_id=spec.identity.organization_id,
            attempt_id=spec.identity.attempt_id,
            for_update=True,
        )
        if row.state is OutboundAttemptState.IN_FLIGHT:
            row = await service.recover_in_flight_as_unknown(
                organization_id=spec.identity.organization_id,
                attempt_id=spec.identity.attempt_id,
                failure_code=failure_code,
            )
        return OutboundExecutionReceipt.from_model(row)


__all__ = [
    "CommandStepContext",
    "DurableStepContext",
    "OutboundExecutionReceipt",
    "OutboundRetryRequested",
    "OutboundSender",
    "execute_outbound_attempt",
    "record_outbound_preflight_failure",
    "request_outbound_cancellation",
]
