"""Pipeline-backed telephony capabilities a schedule can invoke.

The scheduler supplies the stable run ID. The call pipeline uses it as the
DB-first call identity, so an at-least-once worker replay observes the same
outbound ledger entry and never creates a second paid call.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, StrictStr

from eylo.common.contracts.json_values import JsonObject
from eylo.common.outbound import OutboundAttemptState
from eylo.modules.scheduler.actions import (
    ActionContext,
    AgentSchedulingAccess,
    schedulable,
)

logger = logging.getLogger(__name__)
TELEPHONY_PLACE_CALL_ACTION = "telephony.place_call"


class ScheduledCallPayload(BaseModel):
    """Typed call inputs; the original JSON retains additional call provenance."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    to_number: StrictStr | None = None
    initial_message: StrictStr | None = None


@schedulable(
    TELEPHONY_PLACE_CALL_ACTION,
    # Operator-and-campaign only. An agent that could schedule outbound calls
    # could be talked into scheduling them, and this one spends money and rings
    # a real person — `schedule_call` remains the agent's route, and it goes
    # through the same handler with the same checks.
    agent_access=AgentSchedulingAccess.OPERATOR_ONLY,
)
async def place_call(payload: JsonObject, *, context: ActionContext) -> JsonObject:
    """Initiate one outbound call.

    The run row owns execution recovery; the outbound ledger owns the charged
    effect boundary.
    """
    from eylo.pipelines.telephony.call_control import VoiceService

    value = ScheduledCallPayload.model_validate(payload)
    to_number = (value.to_number or "").strip()
    agent_id = context.agent_id
    agent_revision = context.agent_revision

    if not to_number:
        # Terminal by nature — a payload missing this will miss it every time.
        raise ValueError("telephony.place_call requires a to_number.")
    if agent_id is None or agent_revision is None:
        raise ValueError(
            "telephony.place_call requires the run's exact agent reference."
        )

    result = await VoiceService().initiate_outbound_call(
        call_id=context.run_id,
        to_number=to_number,
        agent_id=agent_id,
        agent_revision=agent_revision,
        organization_id=context.organization_id,
        initial_message=value.initial_message,
        context={
            **payload,
            "schedule_id": str(context.schedule_id),
            "schedule_revision": context.schedule_revision,
            "schedule_run_id": str(context.run_id),
        },
    )
    if result.status not in {
        OutboundAttemptState.SUCCEEDED,
        OutboundAttemptState.UNKNOWN,
    }:
        raise ValueError(
            f"Telephony provider rejected the call: {result.failure_code}."
        )

    if context.misfired_count:
        logger.info(
            "Placed a scheduled call to %s late; %d earlier occurrence(s) were "
            "coalesced into this one.",
            to_number,
            context.misfired_count,
        )

    return {
        "to_number": to_number,
        "call_id": str(result.call_id),
        "provider_call_id": result.call_sid,
        "status": result.status.value,
        "late_by_occurrences": context.misfired_count,
    }
