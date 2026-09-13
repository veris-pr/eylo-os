"""Typed call observations preserving the existing append-only JSON history."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter, field_serializer

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.telephony import CallStatus
from eylo.common.outbound import OutboundAttemptState
from eylo.modules.telephony.constants import CallOpenerDeliveryOutcome

_JSON_OBJECT = TypeAdapter(JsonObject)


class CallObservationSource(StrEnum):
    """The owner of an observation, independent of the carrier's native status."""

    RUNTIME = "runtime"
    PROVIDER_CALLBACK = "provider_callback"
    MEDIA_RUNTIME = "media_runtime"


class CallEnrichmentField(StrEnum):
    """Canonical fields whose late observations can enrich or conflict."""

    STATUS = "status"
    PROVIDER_STATUS = "provider_status"
    ENDED_REASON = "ended_reason"
    ENDED_AT = "ended_at"
    CONNECTED_AT = "connected_at"
    DURATION_SECONDS = "duration_seconds"
    CONVERSATION_ID = "conversation_id"


class CallEnrichmentAuthority(StrEnum):
    """Whether a late observation may replace an already populated value."""

    FILL_MISSING = "fill_missing"
    REPLACE_CURRENT = "replace_current"


class CallEnrichmentDisposition(StrEnum):
    """The result of comparing one late observation with canonical state."""

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    CONFLICT = "conflict"


class CallMediaClaim(StrEnum):
    """A history receipt records consumption, not a second claim authority."""

    CONSUMED = "consumed"


class _CallObservation(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    observed_at: AwareDatetime

    @field_serializer("observed_at")
    def serialize_observed_at(self, value: datetime) -> str:
        """Keep the stored ISO offset spelling used by existing history writers."""
        return value.isoformat()

    def as_payload(self) -> JsonObject:
        """Serialize at the JSONB boundary; never persist live model instances."""
        return _JSON_OBJECT.validate_python(self.model_dump(mode="json"))


class CallStatusObservation(_CallObservation):
    """An accepted status observation, including repeated nonterminal statuses."""

    status: CallStatus
    provider_status: str | None
    previous_status: CallStatus
    source: CallObservationSource


class CallEnrichmentObservation(_CallObservation):
    """Late observations cannot reopen a terminal call or overwrite its identity."""

    status: CallStatus
    incoming_status: CallStatus
    source: CallObservationSource
    enriched_fields: tuple[CallEnrichmentField, ...]
    conflicts: tuple[CallEnrichmentField, ...]


class CallOutboundObservation(_CallObservation):
    """The durable outbound attempt's result, distinct from call completion."""

    effect_state: OutboundAttemptState


class CallMediaObservation(_CallObservation):
    """The first outbound media handoff consumed its one-use claim."""

    media_claim: Literal[CallMediaClaim.CONSUMED] = CallMediaClaim.CONSUMED


class CallOpenerObservation(_CallObservation):
    """The final carrier-facing opener delivery outcome."""

    opener_delivery: CallOpenerDeliveryOutcome


type CallHistoryEntry = (
    CallStatusObservation
    | CallEnrichmentObservation
    | CallOutboundObservation
    | CallMediaObservation
    | CallOpenerObservation
)
