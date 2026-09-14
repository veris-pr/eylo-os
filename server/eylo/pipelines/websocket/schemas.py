"""Data contracts for the `websocket` pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, TypeAlias
from uuid import UUID

import arrow
from pydantic import BaseModel, ConfigDict, Field, InstanceOf
from pydantic.json_schema import SkipJsonSchema

from eylo.common.contracts.voice import (
    BrowserVoiceTerminationReason,
    RecordingDisclosureState,
)
from eylo.common.contracts.websocket import (
    WsCommonFilters as WsCommonFilters,
)
from eylo.common.contracts.websocket import (
    WsContactQueryEvent as WsContactQueryEvent,
)
from eylo.common.contracts.websocket import (
    WsContactQueryFilters as WsContactQueryFilters,
)
from eylo.common.contracts.websocket import (
    WsConversationQueryEvent as WsConversationQueryEvent,
)
from eylo.common.contracts.websocket import WsEvent
from eylo.common.contracts.websocket import (
    WsEventAction as WsEventAction,
)
from eylo.common.contracts.websocket import WsIdentifyEvent as WsIdentifyEvent
from eylo.common.contracts.websocket import (
    WsParticipantQueryEvent as WsParticipantQueryEvent,
)
from eylo.common.contracts.websocket import (
    WsParticipantQueryFilters as WsParticipantQueryFilters,
)
from eylo.common.contracts.websocket import (
    WsRequestEvent as WsRequestEvent,
)
from eylo.common.contracts.websocket import (
    WsResponse as WsResponse,
)
from eylo.modules.conversations.schemas import (
    websocket as conversation_websocket_schemas,
)
from eylo.modules.voice.schemas.api import AmbientNoiseConfig, FillerConfig
from eylo.modules.voice_transcripts.constants import VoiceRuntimeMode
from eylo.pipelines.voice.activity_gate import (
    TransportPlaybackGate,
    VoiceActivityGate,
)
from eylo.pipelines.voice.interaction_state import VoiceInteractionState
from eylo.pipelines.voice.live_buffer import LiveVoiceBuffer
from eylo.pipelines.voice.recording import AudioRecorder
from eylo.pipelines.voice.request_state import (
    VoiceRequestSource,
    VoiceRequestState,
    VoiceRequestStatus,
    resolve_voice_request_status,
)
from eylo.pipelines.voice.runtime_ports import VoiceTurnRunner
from eylo.pipelines.voice.stt import STTRealtime
from eylo.pipelines.voice.transcript_inputs import VoiceTranscriptInput
from eylo.pipelines.voice.tts import TTSRealtime
from eylo.pipelines.voice.tts_payloads import TTSRequest

if TYPE_CHECKING:
    from eylo.pipelines.voice.realtime import RealtimeManager

logger = logging.getLogger(__name__)


_DEFAULT_SAMPLE_RATE = 16000

OrganizationUUID: TypeAlias = UUID
SessionUUID: TypeAlias = str
ContactUUID: TypeAlias = UUID
ConversationUUID: TypeAlias = UUID

WsMessageEvent = conversation_websocket_schemas.WsMessageEvent
WsMessageFeedbackEvent = conversation_websocket_schemas.WsMessageFeedbackEvent
WsMessageQueryEvent = conversation_websocket_schemas.WsMessageQueryEvent
WsMessagesQueryFilters = conversation_websocket_schemas.WsMessagesQueryFilters


class WSSessionType(str, Enum):
    """Type of WebSocket session."""

    BROWSER = "browser"
    TWILIO = "twilio"
    PLIVO = "plivo"
    VONAGE = "vonage"
    EXOTEL = "exotel"


class WsConnectionState(str, Enum):
    """Connection state for tracking connection lifecycle."""

    NEW = "new"  # Initial state
    CONNECTING = "connecting"  # In process of connecting
    CONNECTED = "connected"  # Successfully connected
    RECONNECTING = "reconnecting"  # Attempting to reconnect
    DISCONNECTING = "disconnecting"  # In process of disconnecting
    DISCONNECTED = "disconnected"  # Fully disconnected
    FAILED = "failed"  # Connection failed


class WsPingEvent(WsEvent):
    """Ping event for WebSocket heartbeat."""

    pass


class STTEncodingInfo(BaseModel):
    encoding: str = "LINEAR16"
    sample_rate: int = _DEFAULT_SAMPLE_RATE
    channel: int = 1
    language: str = "en-US"


class WebSocketClientInfo(BaseModel):
    """Request metadata retained locally, not provider configuration or authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    ip: str | None = None
    user_agent: str | None = None
    referer: str | None = None
    origin: str | None = None


class VoiceSessionTask(StrEnum):
    """Session-owned children cancelled during voice teardown."""

    STT_INITIALIZE = "stt_initialize"
    TTS_INITIALIZE = "tts_initialize"
    USER_TRANSCRIPT_WRITER = "user_transcript_writer"
    MAX_DURATION_TIMEOUT = "max_duration_timeout"
    SILENCE_MONITOR = "silence_monitor"


class WSSessionState(BaseModel):
    """Mutable transport state with validated, identity-preserving live handles.

    Resource handles and request metadata never enter snapshots. Queue producers
    own payload validation; checking a queue instance does not inspect its contents.
    """

    model_config = ConfigDict(validate_assignment=True, hide_input_in_errors=True)

    organization_id: OrganizationUUID
    session_id: SessionUUID
    user_session_id: UUID | None = None
    contact_id: ContactUUID | None = None
    session_type: WSSessionType = WSSessionType.BROWSER
    stream_sid: str | None = None
    stt_socket: SkipJsonSchema[InstanceOf[STTRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    stt_response_queue: SkipJsonSchema[
        InstanceOf[asyncio.Queue[VoiceTranscriptInput]] | None
    ] = Field(default=None, exclude=True, repr=False)
    stt_request_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[bytes]] | None] = Field(
        default=None, exclude=True, repr=False
    )
    client_info: WebSocketClientInfo | None = Field(
        default=None, exclude=True, repr=False
    )
    stt_started: bool = False
    stt_encoding_info: STTEncodingInfo = Field(default_factory=STTEncodingInfo)
    stt_session_tasks: SkipJsonSchema[
        dict[VoiceSessionTask, InstanceOf[asyncio.Task[None]]]
    ] = Field(default_factory=dict, exclude=True, repr=False)
    tts_started: bool = False
    tts_socket: SkipJsonSchema[InstanceOf[TTSRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    tts_manager: SkipJsonSchema[InstanceOf[TTSRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    tts_response_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[bytes]] | None] = Field(
        default=None, exclude=True, repr=False
    )
    tts_request_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[TTSRequest]] | None] = (
        Field(default=None, exclude=True, repr=False)
    )
    tts_session_tasks: SkipJsonSchema[
        dict[VoiceSessionTask, InstanceOf[asyncio.Task[None]]]
    ] = Field(default_factory=dict, exclude=True, repr=False)
    voice_policy_tasks: SkipJsonSchema[
        dict[VoiceSessionTask, InstanceOf[asyncio.Task[None]]]
    ] = Field(default_factory=dict, exclude=True, repr=False)
    speech_activity_event: SkipJsonSchema[InstanceOf[asyncio.Event]] = Field(
        default_factory=asyncio.Event, exclude=True, repr=False
    )
    tts_interrupt_event: SkipJsonSchema[InstanceOf[asyncio.Event]] = Field(
        default_factory=asyncio.Event, exclude=True, repr=False
    )
    is_voice_mode: bool = False
    is_agent_thinking: bool = (
        False  # Set True while LLM is processing, enables ambient audio
    )
    voice_activity_gate: SkipJsonSchema[InstanceOf[VoiceActivityGate]] = Field(
        default_factory=VoiceActivityGate, exclude=True, repr=False
    )
    transport_playback_gate: SkipJsonSchema[InstanceOf[TransportPlaybackGate]] = Field(
        default_factory=TransportPlaybackGate, exclude=True, repr=False
    )
    voice_output_drained_callback: SkipJsonSchema[Callable[[], None] | None] = Field(
        default=None, exclude=True, repr=False
    )
    # Resolved once from the agent's ObservabilityPlan when audio is
    # configured, so teardown need not re-read it. Defaults match the schema.
    metrics_enabled: bool = True
    vendor_latency_tracking_enabled: bool = True
    ambient_noise_config: AmbientNoiseConfig | None = None
    filler_config: FillerConfig | None = None
    agent_id: UUID | None = None
    agent_revision: int | None = None
    # Populated from the published agent revision before WebRTC setup. D-014
    # owns that binding; absence must remain an actionable NotConfigured error.
    webrtc_provider_config_id: UUID | None = None
    webrtc_provider_config_revision: int | None = None
    last_activity_at: float = Field(default_factory=lambda: arrow.utcnow().timestamp())

    # Realtime mode (Gemini Live / OpenAI Realtime)
    realtime_mode: bool = False
    realtime_manager: SkipJsonSchema[InstanceOf["RealtimeManager"] | None] = Field(
        default=None, exclude=True, repr=False
    )

    # Voice recording (non-blocking audio capture)
    #
    # Notification state is visible to the client but does not own recording.
    # Recording begins with the primary voice flow; post-call data controls
    # own later redaction/deletion.
    recording_consent_state: RecordingDisclosureState = (
        RecordingDisclosureState.NOT_REQUIRED
    )
    audio_recorder: SkipJsonSchema[InstanceOf[AudioRecorder] | None] = Field(
        default=None, exclude=True, repr=False
    )
    # Fresh identity for one call on a potentially long-lived WebSocket.
    # ``session_id`` identifies the transport connection and must not be reused
    # as the voice runtime identity when a caller starts another call.
    voice_call_id: str | None = None
    voice_interaction_sequence: int = 0
    voice_interaction_started_at: float | None = None
    voice_interaction_callback: SkipJsonSchema[
        Callable[[VoiceInteractionState], None] | None
    ] = Field(default=None, exclude=True, repr=False)
    voice_session_id: UUID | None = None
    voice_transcript_session_started: bool = False
    voice_transcript_runtime_mode: VoiceRuntimeMode | None = None
    live_voice_buffer: SkipJsonSchema[InstanceOf[LiveVoiceBuffer] | None] = Field(
        default=None, exclude=True, repr=False
    )
    live_voice_turn_runner: SkipJsonSchema[InstanceOf[VoiceTurnRunner] | None] = Field(
        default=None, exclude=True, repr=False
    )
    voice_requests: dict[UUID, VoiceRequestState] = Field(default_factory=dict)
    current_voice_request_id: UUID | None = None
    voice_termination_lock: SkipJsonSchema[InstanceOf[asyncio.Lock]] = Field(
        default_factory=asyncio.Lock, exclude=True, repr=False
    )
    voice_termination_task: SkipJsonSchema[InstanceOf[asyncio.Task[bool]] | None] = (
        Field(default=None, exclude=True, repr=False)
    )
    voice_termination_complete: bool = False
    voice_termination_reason: BrowserVoiceTerminationReason | None = None
    voice_terminal_callback: SkipJsonSchema[
        Callable[[BrowserVoiceTerminationReason], Awaitable[None]] | None
    ] = Field(default=None, exclude=True, repr=False)

    @property
    def has_audio_recorder(self) -> bool:
        """Report recorder presence, not whether it is capturing or uploading."""
        return self.audio_recorder is not None

    @property
    def current_voice_request(self) -> VoiceRequestState | None:
        if self.current_voice_request_id is None:
            return None
        return self.voice_requests.get(self.current_voice_request_id)

    def start_voice_request(
        self,
        *,
        request_id: UUID,
        conversation_id: UUID,
        source: VoiceRequestSource = VoiceRequestSource.USER,
        status: VoiceRequestStatus = VoiceRequestStatus.STT_DETECTED,
    ) -> VoiceRequestState:
        state = VoiceRequestState(
            request_id=request_id,
            conversation_id=conversation_id,
            source=source,
            status=status,
        )
        self.voice_requests[request_id] = state
        if source is VoiceRequestSource.USER:
            self.current_voice_request_id = request_id
        return state

    def mark_voice_request(
        self,
        request_id: UUID | str | None,
        status: VoiceRequestStatus,
        *,
        conversation_id: UUID | None = None,
        source: VoiceRequestSource = VoiceRequestSource.USER,
        user_message_id: UUID | None = None,
        assistant_message_id: UUID | None = None,
        turn_id: str | None = None,
    ) -> VoiceRequestState | None:
        if request_id is None:
            return None
        normalized_request_id = (
            request_id if isinstance(request_id, UUID) else UUID(str(request_id))
        )
        state = self.voice_requests.get(normalized_request_id)
        if state is None:
            if conversation_id is None:
                return None
            state = self.start_voice_request(
                request_id=normalized_request_id,
                conversation_id=conversation_id,
                source=source,
                status=status,
            )
            state.mark(
                status,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                turn_id=turn_id,
            )
        else:
            state.mark(
                resolve_voice_request_status(state.status, status),
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                turn_id=turn_id,
            )
        if state.source == VoiceRequestSource.USER:
            self.current_voice_request_id = normalized_request_id
        return state


# Resolve forward reference to RealtimeManager (imported under TYPE_CHECKING).
# Per https://docs.pydantic.dev/latest/concepts/forward_annotations/
# We must pass the type via _types_namespace because model_rebuild() resolves
# annotations from the module's global scope, not from function locals.
def _rebuild_ws_session_state() -> None:
    from eylo.pipelines.voice.realtime import RealtimeManager

    WSSessionState.model_rebuild(_types_namespace={"RealtimeManager": RealtimeManager})


_rebuild_ws_session_state()
