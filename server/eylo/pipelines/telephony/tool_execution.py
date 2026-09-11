"""Durable execution path for the platform place_call agent tool."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Mapping, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.outbound import OutboundAttemptConflict, OutboundAttemptState
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.pipelines.outbound.durable_execution import CommandStepContext

from .call_control import VoiceService

if TYPE_CHECKING:
    from eylo.pipelines.agent_execution_context import PlatformExecutionContext

PLACE_CALL_TOOL_NAME = "place_call"
_E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


class _PlaceCallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_number: str
    initial_message: str = Field(min_length=1, max_length=10_000)

    @field_validator("to_number")
    @classmethod
    def validate_to_number(cls, value: str) -> str:
        value = value.strip()
        if not _E164_PATTERN.fullmatch(value):
            raise ValueError("to_number must be E.164.")
        return value


class PlaceCallToolFailureCode(StrEnum):
    INPUT_INVALID = "telephony_input_invalid"
    AGENT_AUTHORITY_UNAVAILABLE = "telephony_agent_authority_unavailable"
    CONFIG_UNAVAILABLE = "telephony_config_unavailable"
    DELIVERY_CONFLICT = "telephony_delivery_conflict"
    DELIVERY_UNKNOWN = "telephony_delivery_unknown"
    DELIVERY_REJECTED = "telephony_delivery_rejected"
    DURABLE_EXECUTION_REQUIRED = "durable_execution_required"


class PlaceCallToolResultKind(StrEnum):
    ACCEPTED = "accepted"
    ERROR = "telephony_error"


class _PlaceCallValue(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class PlaceCallAccepted(_PlaceCallValue):
    """An accepted initiation is not evidence that the recipient answered."""

    status: Literal[PlaceCallToolResultKind.ACCEPTED] = PlaceCallToolResultKind.ACCEPTED
    call_id: UUID


class PlaceCallFailure(_PlaceCallValue):
    kind: Literal[PlaceCallToolResultKind.ERROR] = PlaceCallToolResultKind.ERROR
    error: PlaceCallToolFailureCode


class PlaceCallInvocationMetadata(_PlaceCallValue):
    """Marker for an invocation refused before an outbound attempt exists."""

    telephony_delivery: Literal[True] = True


class PlaceCallDeliveryMetadata(PlaceCallInvocationMetadata):
    """Exact committed delivery identity; a provider call ID may be unknown."""

    telephony_delivery_status: OutboundAttemptState
    call_id: UUID
    provider_call_id: str | None
    outbound_attempt_id: UUID
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)


class PlaceCallToolExecutionOutcome(_PlaceCallValue):
    content: PlaceCallAccepted | PlaceCallFailure
    metadata: PlaceCallDeliveryMetadata | PlaceCallInvocationMetadata | None = None

    @property
    def is_error(self) -> bool:
        return isinstance(self.content, PlaceCallFailure)

    @model_validator(mode="after")
    def require_matching_delivery(self) -> Self:
        """A success cannot contradict the committed attempt or its call identity."""
        if isinstance(self.content, PlaceCallAccepted):
            if (
                not isinstance(self.metadata, PlaceCallDeliveryMetadata)
                or self.metadata.telephony_delivery_status
                is not OutboundAttemptState.SUCCEEDED
                or self.metadata.call_id != self.content.call_id
            ):
                raise ValueError("Accepted call requires matching successful delivery.")
        elif isinstance(self.metadata, PlaceCallDeliveryMetadata):
            state = self.metadata.telephony_delivery_status
            expected = (
                PlaceCallToolFailureCode.DELIVERY_UNKNOWN
                if state is OutboundAttemptState.UNKNOWN
                else PlaceCallToolFailureCode.DELIVERY_REJECTED
            )
            if (
                state is OutboundAttemptState.SUCCEEDED
                or self.content.error is not expected
            ):
                raise ValueError("Call refusal differs from its delivery outcome.")
        return self


async def execute_agent_place_call_tool(
    *,
    tool_input: Mapping[str, JsonValue],
    conversation_context: PlatformExecutionContext,
    tool_use_message_id: UUID,
    durable_context: CommandStepContext,
) -> PlaceCallToolExecutionOutcome:
    """Place one call under the committed TOOL_USE message identity."""
    try:
        requested = _PlaceCallInput.model_validate(dict(tool_input))
    except ValidationError:
        return _error(PlaceCallToolFailureCode.INPUT_INVALID)

    primary_agent = conversation_context.get_primary_agent()
    if (
        primary_agent is None
        or primary_agent.agent_id is None
        or primary_agent.agent_revision is None
    ):
        return _error(PlaceCallToolFailureCode.AGENT_AUTHORITY_UNAVAILABLE)

    try:
        result = await VoiceService().initiate_outbound_call(
            call_id=tool_use_message_id,
            to_number=requested.to_number,
            agent_id=primary_agent.agent_id,
            agent_revision=primary_agent.agent_revision,
            organization_id=conversation_context.conversation.organization_id,
            initial_message=requested.initial_message,
            context={
                "conversation_id": str(conversation_context.conversation.id),
                "tool_use_message_id": str(tool_use_message_id),
            },
            durable_context=durable_context,
        )
    except NotConfiguredError:
        return _error(PlaceCallToolFailureCode.CONFIG_UNAVAILABLE)
    except OutboundAttemptConflict:
        return _error(PlaceCallToolFailureCode.DELIVERY_CONFLICT)

    metadata = PlaceCallDeliveryMetadata(
        telephony_delivery_status=result.status,
        call_id=result.call_id,
        provider_call_id=result.call_sid,
        outbound_attempt_id=result.outbound_attempt_id,
        provider_config_id=result.provider_config_id,
        provider_config_revision=result.provider_config_revision,
    )
    if result.status is OutboundAttemptState.SUCCEEDED:
        return PlaceCallToolExecutionOutcome(
            content=PlaceCallAccepted(call_id=result.call_id),
            metadata=metadata,
        )
    code = (
        PlaceCallToolFailureCode.DELIVERY_UNKNOWN
        if result.status is OutboundAttemptState.UNKNOWN
        else PlaceCallToolFailureCode.DELIVERY_REJECTED
    )
    return _error(code, metadata=metadata)


def _error(
    code: PlaceCallToolFailureCode,
    *,
    metadata: PlaceCallDeliveryMetadata | None = None,
) -> PlaceCallToolExecutionOutcome:
    return PlaceCallToolExecutionOutcome(
        content=PlaceCallFailure(error=code),
        metadata=metadata,
    )


__all__ = [
    "PLACE_CALL_TOOL_NAME",
    "PlaceCallToolExecutionOutcome",
    "execute_agent_place_call_tool",
]
