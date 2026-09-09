"""Bridge one browser WebRTC peer to an Agent voice session."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Final

import arrow
from aiortc import (
    MediaStreamTrack,
    RTCBundlePolicy,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from pydantic import BaseModel, ConfigDict, Field

from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.voice import WebRTCState, WebRTCStateEvent
from eylo.pipelines.session_timeline import try_file_runtime_fact
from eylo.pipelines.webrtc.media import IncomingAudioTrack, OutgoingAudioTrack
from eylo.pipelines.websocket.schemas import WSSessionState

logger = logging.getLogger(__name__)

AUDIO_TRACK_KIND: Final = "audio"
STT_REQUEST_QUEUE_CAPACITY: Final = 50
TTS_RESPONSE_QUEUE_CAPACITY: Final = 1000


class SessionDescriptionType(StrEnum):
    """Native SDP description kinds, not Eylo signaling commands."""

    OFFER = "offer"
    ANSWER = "answer"
    PRANSWER = "pranswer"
    ROLLBACK = "rollback"


class PeerConnectionState(StrEnum):
    """Native peer states, distinct from Eylo lifecycle event names."""

    NEW = "new"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    CLOSED = "closed"


class IceConnectionState(StrEnum):
    NEW = "new"
    CHECKING = "checking"
    CONNECTED = "connected"
    COMPLETED = "completed"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    CLOSED = "closed"


class IceGatheringState(StrEnum):
    NEW = "new"
    GATHERING = "gathering"
    COMPLETE = "complete"


class PeerEvent(StrEnum):
    CONNECTION_STATE_CHANGED = "connectionstatechange"
    ICE_GATHERING_STATE_CHANGED = "icegatheringstatechange"
    ICE_CONNECTION_STATE_CHANGED = "iceconnectionstatechange"
    SIGNALING_STATE_CHANGED = "signalingstatechange"
    TRACK = "track"


class WebRTCOffer(BaseModel):
    """Sanitized remote offer; authorization and candidate policy precede it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    sdp: str = Field(min_length=1)


class WebRTCPeerEventData(BaseModel):
    """Bounded peer observations serialized into the existing event envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    state: PeerConnectionState | IceGatheringState | None = None
    error: str | None = None
    reason: BrowserVoiceTerminationReason | None = None
    track_kind: str | None = None
    track_id: str | None = None


_PEER_TERMINATION_REASONS: Final = {
    PeerConnectionState.DISCONNECTED: BrowserVoiceTerminationReason.PEER_DISCONNECTED,
    PeerConnectionState.FAILED: BrowserVoiceTerminationReason.PEER_FAILED,
    PeerConnectionState.CLOSED: BrowserVoiceTerminationReason.PEER_CLOSED,
}
_ICE_TERMINATION_REASONS: Final = {
    IceConnectionState.DISCONNECTED: BrowserVoiceTerminationReason.ICE_DISCONNECTED,
    IceConnectionState.FAILED: BrowserVoiceTerminationReason.ICE_FAILED,
    IceConnectionState.CLOSED: BrowserVoiceTerminationReason.ICE_CLOSED,
}


class AgentPeerClient:
    """Enhanced peer client with STT/TTS audio processing integration."""

    @property
    def pc(self) -> RTCPeerConnection:
        if self._pc:
            return self._pc
        raise ValueError("RTCPeerConnection is not set")

    @property
    def incoming_audio_track(self) -> IncomingAudioTrack:
        if self._incoming_audio_track:
            return self._incoming_audio_track
        raise ValueError("IncomingAudioTrack is not set")

    @property
    def outgoing_audio_track(self) -> OutgoingAudioTrack:
        if self._outgoing_audio_track:
            return self._outgoing_audio_track
        raise ValueError("OutgoingAudioTrack is not set")

    def __init__(
        self,
        session_state: WSSessionState,
        *,
        negotiation_id: str,
        terminal_callback: Callable[[BrowserVoiceTerminationReason], Awaitable[None]],
    ) -> None:
        self._session_state = session_state
        self._negotiation_id = negotiation_id
        self._terminal_callback = terminal_callback
        self._terminal_scheduled = False
        self._cleaning_up = False
        self._last_timeline_transport_state: PeerConnectionState | None = None
        self._pc: RTCPeerConnection | None = None
        self._outgoing_audio_track: OutgoingAudioTrack | None = None
        self._incoming_audio_track: IncomingAudioTrack | None = None
        self._consume_task: asyncio.Task[None] | None = None
        self._stt_forwarder_task: asyncio.Task[None] | None = None
        self._terminal_task: asyncio.Task[None] | None = None
        self._connection_established_time: arrow.Arrow | None = None
        self._last_activity_time = arrow.utcnow()
        self._rtc_configuration: RTCConfiguration | None = None

    def _emit_webrtc_state(
        self, state: WebRTCState, message: str, data: WebRTCPeerEventData | None = None
    ) -> None:
        """Project peer observations without exposing SDK resources."""
        try:
            emit_ephemeral(
                WebRTCStateEvent(
                    state=state,
                    message=message,
                    session_id=self._session_state.session_id,
                    organization_id=self._session_state.organization_id,
                    data=data.model_dump(mode="json", exclude_none=True)
                    if data
                    else {},
                )
            )
            logger.debug(f"Emitted WebRTC {state.value} event")
        except Exception as error:
            logger.warning(
                "WebRTC state event failed state=%s category=%s",
                state.value,
                type(error).__name__,
            )

    def _schedule_terminal(self, reason: BrowserVoiceTerminationReason) -> None:
        if self._terminal_scheduled or self._cleaning_up:
            return
        self._terminal_scheduled = True
        self._terminal_task = asyncio.create_task(self._run_terminal_callback(reason))
        self._terminal_task.add_done_callback(self._terminal_done)

    async def _run_terminal_callback(
        self, reason: BrowserVoiceTerminationReason
    ) -> None:
        """Adapt any declared awaitable to a coroutine owned by this peer."""
        await self._terminal_callback(reason)

    def _terminal_done(self, task: asyncio.Task[None]) -> None:
        self._terminal_task = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "WebRTC terminal cleanup failed error_type=%s", type(error).__name__
            )

    async def _record_transport_state(self, state: PeerConnectionState) -> None:
        if self._last_timeline_transport_state == state:
            return
        self._last_timeline_transport_state = state
        await try_file_runtime_fact(
            organization_id=self._session_state.organization_id,
            user_session_id=self._session_state.user_session_id,
            subject_type="transport.webrtc",
            subject_id=self._session_state.voice_session_id,
            event_type=f"transport.webrtc.{state}",
            payload={"negotiation_id": self._negotiation_id},
        )

    async def setup_peer_connection(
        self,
        offer: WebRTCOffer,
        *,
        ice_servers: tuple[RTCIceServer, ...],
    ) -> None:
        """Setup the peer connection with audio processing."""
        logger.info("Setting up WebRTC peer connection for STT/TTS")

        # Reset any existing STT forwarder task before creating new queues
        if self._stt_forwarder_task and not self._stt_forwarder_task.done():
            self._stt_forwarder_task.cancel()
            try:
                await self._stt_forwarder_task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error(
                    "WebRTC STT forwarder reset failed error_type=%s",
                    type(error).__name__,
                )
        self._stt_forwarder_task = None

        self._rtc_configuration = RTCConfiguration(
            iceServers=list(ice_servers), bundlePolicy=RTCBundlePolicy.MAX_BUNDLE
        )

        logger.info(
            f"[WEBRTC] Creating peer connection with {len(ice_servers)} ICE servers"
        )

        self._pc = RTCPeerConnection(configuration=self._rtc_configuration)
        self._last_activity_time = arrow.utcnow()

        # Runtime queues and forwarders are allocated only after config is ready
        # and a peer exists, so failed preparation leaves no background resources.
        if not self._session_state.realtime_mode:
            self._session_state.stt_request_queue = asyncio.Queue(
                maxsize=STT_REQUEST_QUEUE_CAPACITY
            )
        if self._session_state.tts_manager:
            if self._session_state.tts_response_queue is None:
                self._session_state.tts_response_queue = asyncio.Queue(
                    maxsize=TTS_RESPONSE_QUEUE_CAPACITY
                )
            logger.info("TTS is enabled - will add outgoing audio track")
        elif self._session_state.realtime_mode:
            logger.info("Realtime mode - vendor provides outgoing audio")
        else:
            logger.info("TTS is disabled - STT-only mode")
        if self._session_state.stt_request_queue:
            self._stt_forwarder_task = asyncio.create_task(self._forward_stt_audio())

        # Emit peer created event
        self._emit_webrtc_state(
            state=WebRTCState.PEER_CREATED,
            message="WebRTC peer connection created",
        )

        # Create and add outgoing audio track for TTS (decomposed or realtime mode)
        has_audio_output = (
            self._session_state.tts_manager or self._session_state.realtime_mode
        )
        if has_audio_output:
            self._outgoing_audio_track = OutgoingAudioTrack(self._session_state)
            self.pc.addTrack(self.outgoing_audio_track)
            logger.info("Added outgoing audio track to peer connection")
        else:
            logger.info("TTS disabled - skipping outgoing audio track")

        # Subscribe to connection state changes for monitoring
        pc = self.pc

        @pc.on(PeerEvent.CONNECTION_STATE_CHANGED)
        async def on_connectionstatechange() -> None:
            logger.info(f"AGENT_PEER: Connection state is {pc.connectionState}")
            self._last_activity_time = arrow.utcnow()

            # Emit connection state changes
            state = PeerConnectionState(pc.connectionState)
            if state is PeerConnectionState.CONNECTING:
                self._emit_webrtc_state(
                    state=WebRTCState.PEER_CONNECTING,
                    message="WebRTC peer connection is connecting",
                    data=WebRTCPeerEventData(state=state),
                )
                await self._record_transport_state(state)
            elif state is PeerConnectionState.CONNECTED:
                self._connection_established_time = arrow.utcnow()
                self._emit_webrtc_state(
                    state=WebRTCState.PEER_CONNECTED,
                    message="WebRTC peer connection established",
                    data=WebRTCPeerEventData(state=state),
                )
                await self._record_transport_state(state)
            elif state is PeerConnectionState.DISCONNECTED:
                self._emit_webrtc_state(
                    state=WebRTCState.PEER_DISCONNECTED,
                    message="WebRTC peer connection disconnected",
                    data=WebRTCPeerEventData(state=state),
                )
                await self._record_transport_state(state)
                self._schedule_terminal(_PEER_TERMINATION_REASONS[state])
            elif state in {PeerConnectionState.FAILED, PeerConnectionState.CLOSED}:
                self._emit_webrtc_state(
                    state=WebRTCState.PEER_FAILED,
                    message="WebRTC peer connection failed",
                    data=WebRTCPeerEventData(
                        state=state, error="Connection failed to establish"
                    ),
                )
                await self._record_transport_state(
                    PeerConnectionState.DISCONNECTED
                    if state is PeerConnectionState.CLOSED and self._cleaning_up
                    else PeerConnectionState.FAILED
                )
                self._schedule_terminal(_PEER_TERMINATION_REASONS[state])

        @pc.on(PeerEvent.ICE_GATHERING_STATE_CHANGED)
        async def on_icegatheringstatechange() -> None:
            logger.info(f"AGENT_PEER: ICE gathering state is {pc.iceGatheringState}")
            self._last_activity_time = arrow.utcnow()

            # Emit ICE gathering state changes
            state = IceGatheringState(pc.iceGatheringState)
            if state is IceGatheringState.GATHERING:
                self._emit_webrtc_state(
                    state=WebRTCState.ICE_GATHERING,
                    message="ICE candidates gathering in progress",
                    data=WebRTCPeerEventData(state=state),
                )
            elif state is IceGatheringState.COMPLETE:
                self._emit_webrtc_state(
                    state=WebRTCState.ICE_COMPLETE,
                    message="ICE candidate gathering completed",
                    data=WebRTCPeerEventData(state=state),
                )

        @pc.on(PeerEvent.ICE_CONNECTION_STATE_CHANGED)
        async def on_iceconnectionstatechange() -> None:
            logger.info(f"AGENT_PEER: ICE connection state is {pc.iceConnectionState}")
            self._last_activity_time = arrow.utcnow()

            state = IceConnectionState(pc.iceConnectionState)
            if state in _ICE_TERMINATION_REASONS and not self._cleaning_up:
                logger.warning(
                    "[ICE_DEBUG] ICE connection state transitioned to %s. "
                    "Relay likely unavailable or connectivity interrupted.",
                    state,
                )
                self._schedule_terminal(_ICE_TERMINATION_REASONS[state])

        @pc.on(PeerEvent.SIGNALING_STATE_CHANGED)
        async def on_signalingstatechange() -> None:
            logger.info(f"AGENT_PEER: Signaling state is {pc.signalingState}")
            self._last_activity_time = arrow.utcnow()

        # aiortc gathers local candidates in setLocalDescription; the signaling
        # manager sends that completed SDP answer, not browser-only ICE events.

        # Set up track handler for incoming audio
        @pc.on(PeerEvent.TRACK)
        def on_track(track: MediaStreamTrack) -> None:
            logger.info(f"Track received: kind={track.kind}, id={track.id}")
            self._last_activity_time = arrow.utcnow()

            if track.kind == AUDIO_TRACK_KIND:
                if self._incoming_audio_track is not None:
                    track.stop()
                    self._emit_webrtc_state(
                        state=WebRTCState.PEER_FAILED,
                        message="Additional audio tracks are unsupported in V1",
                        data=WebRTCPeerEventData(
                            reason=BrowserVoiceTerminationReason.ADDITIONAL_AUDIO_TRACK
                        ),
                    )
                    self._schedule_terminal(
                        BrowserVoiceTerminationReason.ADDITIONAL_AUDIO_TRACK
                    )
                    return
                # Emit track added event
                self._emit_webrtc_state(
                    state=WebRTCState.TRACK_ADDED,
                    message="Audio track added to peer connection",
                    data=WebRTCPeerEventData(track_kind=track.kind, track_id=track.id),
                )

                # Wrap incoming track with STT processor
                self._incoming_audio_track = IncomingAudioTrack(
                    track, self._session_state
                )

                # Start consuming the track for STT
                async def consume_track() -> None:
                    logger.info("Starting to consume incoming audio track for STT")
                    try:
                        while True:
                            await self.incoming_audio_track.recv()
                            self._last_activity_time = arrow.utcnow()
                    except asyncio.CancelledError:
                        logger.info("Track consumption cancelled")
                        raise
                    except Exception as e:
                        logger.info(
                            "Track consumption ended category=%s", type(e).__name__
                        )
                        self._schedule_terminal(
                            BrowserVoiceTerminationReason.TRACK_ENDED
                        )
                        return

                self._consume_task = asyncio.create_task(consume_track())

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=offer.sdp, type=SessionDescriptionType.OFFER)
        )

        # Create answer
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

    async def _forward_stt_audio(self) -> None:
        """Drain audio chunks from the session STT queue into the STT socket."""
        queue = self._session_state.stt_request_queue
        if not queue:
            return

        logger.info("AgentPeerClient: STT forwarder task started")
        try:
            while True:
                try:
                    audio_chunk = await queue.get()
                except asyncio.CancelledError:
                    raise

                try:
                    stt_socket = self._session_state.stt_socket
                    if stt_socket and self._session_state.stt_started:
                        await stt_socket.send_audio(audio_chunk)
                        # TODO (observability): update `self._session_state.last_activity_at` here so the forwarder keeps the session heartbeat fresh even when audio bypasses the IncomingAudioTrack queue timing.
                    else:
                        logger.debug(
                            "AgentPeerClient: STT socket unavailable, dropping audio chunk"
                        )
                except Exception as error:
                    logger.error(
                        "AgentPeerClient STT forwarding failed error_type=%s",
                        type(error).__name__,
                    )
                finally:
                    queue.task_done()
        except asyncio.CancelledError:
            logger.info("AgentPeerClient: STT forwarder task cancelled")
        finally:
            logger.info("AgentPeerClient: STT forwarder task finished")

    async def cleanup(self) -> None:
        """Drain owned media work; never await the terminal task invoking cleanup."""
        logger.info("AgentPeerClient.cleanup: starting resource teardown")
        self._cleaning_up = True

        consume_task = self._consume_task
        if consume_task and not consume_task.done():
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error(
                    "WebRTC consume task cleanup failed error_type=%s",
                    type(error).__name__,
                )
        self._consume_task = None

        forwarder_task = self._stt_forwarder_task
        if forwarder_task and not forwarder_task.done():
            forwarder_task.cancel()
            try:
                await forwarder_task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.error(
                    "WebRTC STT forwarder cleanup failed error_type=%s",
                    type(error).__name__,
                )
        self._stt_forwarder_task = None

        # Stop incoming audio track and clear buffers
        if self._incoming_audio_track:
            try:
                if self._incoming_audio_track.downsampler:
                    self._incoming_audio_track.downsampler.clear_buffers()
            except Exception as error:
                logger.warning(
                    "AgentPeerClient cleanup failed to clear incoming downsampler "
                    "buffers error_type=%s",
                    type(error).__name__,
                )

            try:
                self._incoming_audio_track.stop()
            except Exception as error:
                logger.warning(
                    "AgentPeerClient cleanup failed to stop incoming track "
                    "error_type=%s",
                    type(error).__name__,
                )
            finally:
                self._incoming_audio_track = None

        # Stop outgoing audio track and clear queued audio
        if self._outgoing_audio_track:
            try:
                await self._outgoing_audio_track.clear_buffers()
            except Exception as error:
                logger.warning(
                    "AgentPeerClient cleanup failed to clear outgoing buffers "
                    "error_type=%s",
                    type(error).__name__,
                )

            try:
                self._outgoing_audio_track.stop()
            except Exception as error:
                logger.warning(
                    "AgentPeerClient cleanup failed to stop outgoing track "
                    "error_type=%s",
                    type(error).__name__,
                )
            finally:
                self._outgoing_audio_track = None

        # Close peer connection if still open
        if self._pc:
            try:
                await self._pc.close()
            except Exception as error:
                logger.warning(
                    "AgentPeerClient cleanup failed to close RTCPeerConnection "
                    "error_type=%s",
                    type(error).__name__,
                )
            finally:
                self._pc = None

        # Reset session queues/events to avoid leaking state across sessions
        try:
            if self._session_state.stt_request_queue:
                queue = self._session_state.stt_request_queue
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                self._session_state.stt_request_queue = None

            if (
                self._session_state.tts_response_queue
                and not self._session_state.tts_manager
                and not self._session_state.realtime_mode
            ):
                queue = self._session_state.tts_response_queue
                while not queue.empty():
                    try:
                        queue.get_nowait()
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                self._session_state.tts_response_queue = None

            if self._session_state.tts_interrupt_event.is_set():
                self._session_state.tts_interrupt_event.clear()
        except Exception as error:
            logger.warning(
                "AgentPeerClient cleanup failed to reset session state error_type=%s",
                type(error).__name__,
            )

        logger.info("AgentPeerClient.cleanup: resource teardown complete")
