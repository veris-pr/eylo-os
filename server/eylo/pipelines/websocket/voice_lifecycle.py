"""Presentation contracts for provider readiness, separate from call interaction state."""

from pydantic import BaseModel, ConfigDict

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.voice import BrowserVoiceTerminationReason, VoiceRuntimeMode
from eylo.events.schema.py_events.voice import (
    IceGatheringState,
    PeerConnectionState,
    WebRTCState,
)


class VoiceLifecyclePayload(BaseModel):
    """Project only declared fields; optional observations stay absent on the wire."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True, allow_inf_nan=False,
    )

    message: str
    timestamp: float

    def to_wire(self) -> JsonObject:
        return type(self).model_validate(self).model_dump(mode="json", exclude_none=True)


class WebRTCLifecyclePayload(VoiceLifecyclePayload):
    state: WebRTCState
    provider_state: PeerConnectionState | IceGatheringState | None = None
    error: str | None = None
    reason: BrowserVoiceTerminationReason | None = None
    track_kind: str | None = None
    track_id: str | None = None


class VoiceVendorLifecyclePayload(VoiceLifecyclePayload):
    # Already selected/validated by the capability owner. Do not merge STT, TTS
    # and realtime catalogs into a second provider registry in presentation.
    vendor: str
    error_type: str | None = None
    runtime_mode: VoiceRuntimeMode | None = None
