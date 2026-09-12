"""Voice Service Event Schemas

Events emitted by voice services (WebRTC, STT, TTS) to broadcast state changes
to WebSocket clients. These events follow the same pattern as agent lifecycle events.

Architecture:
- Services emit these events when state changes occur
- Listeners (voice_lifecycle.py) catch events and broadcast via WebSocket
- This decouples service logic from WebSocket broadcasting
"""

from enum import Enum, StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.voice import BrowserVoiceTerminationReason


class WebRTCState(str, Enum):
    """WebRTC peer connection states."""

    PEER_CREATED = "peer_created"
    PEER_CONNECTING = "peer_connecting"
    PEER_CONNECTED = "peer_connected"
    PEER_DISCONNECTED = "peer_disconnected"
    PEER_FAILED = "peer_failed"
    ICE_GATHERING = "ice_gathering"
    ICE_COMPLETE = "ice_complete"
    TRACK_ADDED = "track_added"
    TRACK_REMOVED = "track_removed"


class STTState(str, Enum):
    """STT (Speech-to-Text) service states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class TTSState(str, Enum):
    """TTS (Text-to-Speech) service states."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class VoiceEventValue(BaseModel):
    """Immutable observations; provider resources and raw failures cannot enter."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True, allow_inf_nan=False,
    )


class PeerConnectionState(StrEnum):
    """Observed native peer states, distinct from Eylo lifecycle event names."""

    NEW = "new"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    CLOSED = "closed"


class IceGatheringState(StrEnum):
    NEW = "new"
    GATHERING = "gathering"
    COMPLETE = "complete"


class WebRTCPeerEventData(VoiceEventValue):
    """Only the peer observations projected by the browser transport."""

    state: PeerConnectionState | IceGatheringState | None = None
    error: str | None = None
    reason: BrowserVoiceTerminationReason | None = None
    track_kind: str | None = None
    track_id: str | None = None


class VoiceServiceEventData(VoiceEventValue):
    """Diagnostic exception class name, never a provider's raw error content."""

    error_type: str | None = None


class VoiceStateEvent(VoiceEventValue):
    """Shared routing identity; each concrete event owns its state and data."""

    message: str = Field(..., description="Human-readable status message")
    session_id: str = Field(..., description="Session ID for WebSocket routing")
    organization_id: UUID = Field(
        ..., description="Organization ID for WebSocket routing"
    )


class WebRTCStateEvent(VoiceStateEvent):
    """Event emitted when WebRTC peer connection state changes.

    States:
    - peer_created: Peer connection created
    - peer_connecting: ICE negotiation in progress
    - peer_connected: Peer connection established
    - peer_disconnected: Peer connection lost
    - peer_failed: Peer connection failed
    - ice_gathering: ICE candidate gathering started
    - ice_complete: ICE candidate gathering complete
    - track_added: Media track added to connection
    - track_removed: Media track removed from connection
    """

    state: WebRTCState
    data: WebRTCPeerEventData = Field(default_factory=WebRTCPeerEventData)

    @field_serializer("data")
    def serialize_data(self, value: WebRTCPeerEventData) -> JsonObject:
        return value.model_dump(mode="json", exclude_none=True)


class STTStateEvent(VoiceStateEvent):
    """Event emitted when STT (Speech-to-Text) service state changes.

    States:
    - connecting: Connecting to STT service
    - connected: STT service connection established
    - ready: STT service ready to process audio
    - disconnected: STT service disconnected
    - error: STT service error occurred
    """

    state: STTState
    vendor: str = Field(..., description="Configured STT vendor identifier")
    data: VoiceServiceEventData = Field(default_factory=VoiceServiceEventData)

    @field_serializer("data")
    def serialize_data(self, value: VoiceServiceEventData) -> JsonObject:
        return value.model_dump(mode="json", exclude_none=True)


class TTSStateEvent(VoiceStateEvent):
    """Event emitted when TTS (Text-to-Speech) service state changes.

    States:
    - connecting: Connecting to TTS service
    - connected: TTS service connection established
    - ready: TTS service ready to synthesize speech
    - disconnected: TTS service disconnected
    - error: TTS service error occurred
    """

    state: TTSState
    vendor: str = Field(..., description="Configured TTS vendor identifier")
    data: VoiceServiceEventData = Field(default_factory=VoiceServiceEventData)

    @field_serializer("data")
    def serialize_data(self, value: VoiceServiceEventData) -> JsonObject:
        return value.model_dump(mode="json", exclude_none=True)
