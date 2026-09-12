"""Tenant-bound WebRTC signaling and lifecycle ownership."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from uuid import UUID, uuid4

from aiortc import RTCIceCandidate

from eylo.common.config import settings
from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.common.contracts.websocket import WEBRTC_SIGNALING_VERSION
from eylo.pipelines.webrtc.agent_peer import (
    AgentPeerClient,
    SessionDescriptionType,
    WebRTCOffer,
)
from eylo.pipelines.webrtc.config import (
    browser_ice_servers,
    resolve_ice_configuration,
)
from eylo.pipelines.webrtc.errors import (
    IceCandidateCode,
    WebRTCSignalingCode,
    WebRTCSignalingError,
)
from eylo.pipelines.webrtc.ice_policy import (
    MAX_REMOTE_CANDIDATES,
    IceCandidateError,
    IceDeploymentMode,
    filter_offer_candidates,
    parse_remote_candidate,
)
from eylo.pipelines.webrtc.playback import (
    needs_tts_streamer,
    start_tts_streamer,
    stop_tts_streamer,
)
from eylo.pipelines.webrtc.requests import WebRTCCandidateRequest, WebRTCOfferRequest
from eylo.pipelines.webrtc.schemas import (
    WebRTCAnswer,
    WebRTCCandidateAccepted,
    WebRTCCleanupReason,
    WebRTCCleanupStep,
    WebRTCHangupNotice,
    WebRTCNegotiationState,
    WebRTCPrepared,
    WebRTCSession,
    WebRTCSessionKey,
)
from eylo.pipelines.websocket.schemas import WsEventAction, WsRequestEvent

logger = logging.getLogger(__name__)

WEBRTC_PROTOCOL_VERSION = WEBRTC_SIGNALING_VERSION
NEGOTIATION_DEADLINE_SECONDS = 30


class WebRTCSignalingManager:
    """Own one negotiation aggregate per organization and interface session."""

    def __init__(self) -> None:
        self._sessions: dict[WebRTCSessionKey, WebRTCSession] = {}
        self._registry_lock = asyncio.Lock()

    async def start(self) -> None:
        logger.info("WebRTC signaling manager started")

    async def stop(self) -> None:
        for key in list(self._sessions):
            await self.cleanup_session(
                key.organization_id,
                key.session_id,
                reason=WebRTCCleanupReason.SHUTDOWN,
            )
        logger.info("WebRTC signaling manager stopped")

    def get_session(
        self, organization_id: UUID, session_id: str
    ) -> WebRTCSession | None:
        """Return an exact tenant-bound session for composition and probes."""
        return self._sessions.get(
            WebRTCSessionKey(organization_id=organization_id, session_id=session_id)
        )

    async def prepare_session(
        self,
        organization_id: UUID,
        session_id: str,
    ) -> WebRTCPrepared:
        """Resolve org ICE config before the browser constructs its peer."""
        from eylo.pipelines.websocket.singleton import S_ws_manager

        key = WebRTCSessionKey(organization_id=organization_id, session_id=session_id)
        session_state = S_ws_manager.get_session_state(organization_id, session_id)
        if session_state is None:
            raise WebRTCSignalingError(WebRTCSignalingCode.SESSION_NOT_FOUND)

        async with self._registry_lock:
            session = self._sessions.get(key)
            if session is None:
                session = WebRTCSession(
                    key=key,
                    session_state=session_state,
                    negotiation_id=str(uuid4()),
                )
                self._sessions[key] = session

        failure: Exception | None = None
        async with session.lock:
            if session.state is WebRTCNegotiationState.PREPARING:
                try:
                    resolved_ice = await resolve_ice_configuration(session_state)
                    session.ice_servers = resolved_ice.ice_servers
                    session.credential_expires_at = resolved_ice.credential_expires_at
                    session.negotiation_expires_at = (
                        time.time() + NEGOTIATION_DEADLINE_SECONDS
                    )
                    session.transition(WebRTCNegotiationState.PREPARED)
                    session.deadline_task = asyncio.create_task(
                        self._expire_negotiation(key, session.negotiation_id)
                    )
                except Exception as error:
                    failure = error
            elif session.state in {
                WebRTCNegotiationState.TERMINATING,
                WebRTCNegotiationState.TERMINATED,
            }:
                raise WebRTCSignalingError(WebRTCSignalingCode.NEGOTIATION_TERMINATED)

            if failure is None:
                return WebRTCPrepared(
                    negotiation_id=session.negotiation_id,
                    negotiation_expires_at=session.negotiation_expires_at,
                    credential_expires_at=session.credential_expires_at,
                    ice_servers=tuple(browser_ice_servers(session.ice_servers)),
                )

        await self._terminal_cleanup(key, BrowserVoiceTerminationReason.PREPARE_FAILED)
        if failure is None:
            raise WebRTCSignalingError(WebRTCSignalingCode.PREPARE_FAILED)
        raise failure

    async def handle_offer(
        self,
        organization_id: UUID,
        session_id: str,
        payload: WsRequestEvent,
    ) -> None:
        """Acquire one offer, publish only after its answer is delivered."""
        from eylo.pipelines.websocket.singleton import S_ws_manager

        data = WebRTCOfferRequest.from_payload(payload.data or {})
        negotiation_id = data.negotiation_id
        sdp = data.sdp

        key = WebRTCSessionKey(organization_id=organization_id, session_id=session_id)
        session = self._sessions.get(key)
        if session is None:
            raise WebRTCSignalingError(WebRTCSignalingCode.PREPARE_REQUIRED)
        offer_digest = hashlib.sha256(sdp.encode()).hexdigest()

        failure: Exception | None = None
        cleanup_on_failure = False
        async with session.lock:
            try:
                if negotiation_id != session.negotiation_id:
                    raise WebRTCSignalingError(WebRTCSignalingCode.NEGOTIATION_MISMATCH)
                if session.state is WebRTCNegotiationState.ACTIVE:
                    if (
                        session.offer_digest != offer_digest
                        or session.answer_payload is None
                    ):
                        raise WebRTCSignalingError(WebRTCSignalingCode.OFFER_CONFLICT)
                    delivered = await S_ws_manager.send_response(
                        _signal_envelope(
                            WsEventAction.WEBRTC_ANSWER,
                            session.answer_payload,
                            request_id=payload.request_id,
                        ),
                        organization_id,
                        session_id,
                    )
                    if not delivered:
                        cleanup_on_failure = True
                        raise WebRTCSignalingError(
                            WebRTCSignalingCode.ANSWER_DELIVERY_FAILED
                        )
                    return
                if session.state is not WebRTCNegotiationState.PREPARED:
                    raise WebRTCSignalingError(
                        WebRTCSignalingCode.NEGOTIATION_UNAVAILABLE
                    )

                session.transition(WebRTCNegotiationState.ACQUIRING)
                cleanup_on_failure = True
                try:
                    sanitized_sdp = filter_offer_candidates(
                        sdp,
                        mode=_deployment_mode(),
                        max_candidates=MAX_REMOTE_CANDIDATES,
                    )
                except IceCandidateError as error:
                    raise WebRTCSignalingError(error.code) from None
                embedded_digests = {
                    hashlib.sha256(line.removeprefix("a=").encode()).hexdigest()
                    for line in sanitized_sdp.splitlines()
                    if line.startswith("a=candidate:")
                }
                if (
                    len(session.candidate_digests | embedded_digests)
                    > MAX_REMOTE_CANDIDATES
                ):
                    raise WebRTCSignalingError(IceCandidateCode.CANDIDATE_LIMIT_REACHED)
                session.candidate_digests.update(embedded_digests)
                peer_client = AgentPeerClient(
                    session.session_state,
                    negotiation_id=session.negotiation_id,
                    terminal_callback=lambda reason: self._terminal_cleanup(
                        key, reason
                    ),
                )
                session.peer_client = peer_client
                await peer_client.setup_peer_connection(
                    WebRTCOffer(sdp=sanitized_sdp),
                    ice_servers=session.ice_servers,
                )
                for candidate in session.pending_candidates:
                    await peer_client.pc.addIceCandidate(candidate)
                session.pending_candidates.clear()

                local_description = peer_client.pc.localDescription
                if (
                    local_description is None
                    or local_description.type != SessionDescriptionType.ANSWER
                ):
                    raise WebRTCSignalingError(WebRTCSignalingCode.ANSWER_UNAVAILABLE)
                answer_payload = WebRTCAnswer(
                    negotiation_id=session.negotiation_id,
                    sdp=local_description.sdp,
                )
                delivered = await S_ws_manager.send_response(
                    _signal_envelope(
                        WsEventAction.WEBRTC_ANSWER,
                        answer_payload,
                        request_id=payload.request_id,
                    ),
                    organization_id,
                    session_id,
                )
                if not delivered:
                    raise WebRTCSignalingError(
                        WebRTCSignalingCode.ANSWER_DELIVERY_FAILED
                    )

                session.answer_payload = answer_payload
                session.offer_digest = offer_digest
                session.transition(WebRTCNegotiationState.ACTIVE)
                _cancel_deadline(session)
                if needs_tts_streamer(session.session_state):
                    session.tts_streamer_task = start_tts_streamer(
                        organization_id=organization_id,
                        session_id=session_id,
                    )
                logger.info(
                    "WebRTC negotiation active organization_id=%s",
                    organization_id,
                )
            except Exception as error:
                failure = error

        if failure is not None:
            if cleanup_on_failure:
                await self._terminal_cleanup(
                    key, BrowserVoiceTerminationReason.OFFER_FAILED
                )
            raise failure

    async def handle_candidate(
        self,
        organization_id: UUID,
        session_id: str,
        payload: WsRequestEvent,
    ) -> WebRTCCandidateAccepted:
        """Admit, deduplicate, cap, and apply one remote ICE candidate."""
        data = WebRTCCandidateRequest.from_payload(payload.data or {})
        negotiation_id = data.negotiation_id
        key = WebRTCSessionKey(organization_id=organization_id, session_id=session_id)
        session = self._sessions.get(key)
        if session is None:
            raise WebRTCSignalingError(WebRTCSignalingCode.PREPARE_REQUIRED)

        candidate_data = data.candidate

        async with session.lock:
            if negotiation_id != session.negotiation_id:
                raise WebRTCSignalingError(WebRTCSignalingCode.NEGOTIATION_MISMATCH)
            if session.state not in {
                WebRTCNegotiationState.PREPARED,
                WebRTCNegotiationState.ACQUIRING,
                WebRTCNegotiationState.ACTIVE,
            }:
                raise WebRTCSignalingError(WebRTCSignalingCode.NEGOTIATION_UNAVAILABLE)

            if candidate_data is None:
                candidate: RTCIceCandidate | None = None
                digest = "end-of-candidates"
            else:
                candidate_line = candidate_data.candidate
                digest = hashlib.sha256(candidate_line.encode()).hexdigest()
                if digest in session.candidate_digests:
                    return _candidate_outcome(session, duplicate=True)
                try:
                    parsed = parse_remote_candidate(
                        candidate_line,
                        mode=_deployment_mode(),
                    )
                except IceCandidateError as error:
                    raise WebRTCSignalingError(error.code) from None
                candidate = RTCIceCandidate(
                    foundation=parsed.foundation,
                    component=parsed.component.value,
                    protocol=parsed.protocol.value,
                    priority=parsed.priority,
                    ip=parsed.address,
                    port=parsed.port,
                    type=parsed.candidate_type.value,
                    relatedAddress=parsed.related_address,
                    relatedPort=parsed.related_port,
                    sdpMid=candidate_data.sdp_mid,
                    sdpMLineIndex=candidate_data.sdp_mline_index,
                    tcpType=parsed.tcp_type.value
                    if parsed.tcp_type is not None
                    else None,
                )

            if digest in session.candidate_digests:
                return _candidate_outcome(session, duplicate=True)
            if len(session.candidate_digests) >= MAX_REMOTE_CANDIDATES:
                raise WebRTCSignalingError(IceCandidateCode.CANDIDATE_LIMIT_REACHED)
            session.candidate_digests.add(digest)

            if session.peer_client is None:
                session.pending_candidates.append(candidate)
            else:
                try:
                    await session.peer_client.pc.addIceCandidate(candidate)
                except Exception:
                    raise WebRTCSignalingError(
                        WebRTCSignalingCode.CANDIDATE_APPLY_FAILED
                    ) from None
            return _candidate_outcome(session, duplicate=False)

    async def cleanup_session(
        self,
        organization_id: UUID,
        session_id: str,
        *,
        reason: BrowserVoiceTerminationReason
        | WebRTCCleanupReason = WebRTCCleanupReason.HANGUP,
        notify_client: bool = False,
    ) -> bool:
        """Run terminal cleanup once; every teardown step is failure-contained."""
        from eylo.pipelines.websocket.singleton import S_ws_manager

        key = WebRTCSessionKey(organization_id=organization_id, session_id=session_id)
        session = self._sessions.get(key)
        if session is None:
            return False

        owns_cleanup = False
        try:
            async with session.lock:
                if session.state in {
                    WebRTCNegotiationState.TERMINATING,
                    WebRTCNegotiationState.TERMINATED,
                }:
                    return False
                owns_cleanup = True
                session.transition(WebRTCNegotiationState.TERMINATING)
                _cancel_deadline(session)

                if notify_client:
                    try:
                        await S_ws_manager.send_response(
                            _signal_envelope(
                                WsEventAction.WEBRTC_HANGUP,
                                WebRTCHangupNotice(
                                    negotiation_id=session.negotiation_id,
                                    reason=reason,
                                ),
                            ),
                            organization_id,
                            session_id,
                        )
                    except Exception as error:
                        _log_cleanup_failure(
                            organization_id, WebRTCCleanupStep.NOTIFY, error
                        )

                try:
                    await stop_tts_streamer(
                        session.tts_streamer_task,
                        session_id=session_id,
                    )
                except Exception as error:
                    _log_cleanup_failure(
                        organization_id, WebRTCCleanupStep.TTS_STREAMER, error
                    )
                finally:
                    session.tts_streamer_task = None

                if session.peer_client is not None:
                    try:
                        await session.peer_client.cleanup()
                    except Exception as error:
                        _log_cleanup_failure(
                            organization_id, WebRTCCleanupStep.PEER, error
                        )
                    finally:
                        session.peer_client = None

                session.pending_candidates.clear()
                session.candidate_digests.clear()
                session.transition(WebRTCNegotiationState.TERMINATED)
        finally:
            if owns_cleanup:
                await self._detach(key, session)

        logger.info(
            "WebRTC session cleaned organization_id=%s reason=%s",
            organization_id,
            reason.value,
        )
        return True

    async def _terminal_cleanup(
        self, key: WebRTCSessionKey, reason: BrowserVoiceTerminationReason
    ) -> None:
        session = self._sessions.get(key)
        terminal_callback = (
            session.session_state.voice_terminal_callback if session else None
        )
        cleaned = await self.cleanup_session(
            key.organization_id,
            key.session_id,
            reason=reason,
            notify_client=True,
        )
        if cleaned and terminal_callback is not None:
            try:
                await terminal_callback(reason)
            except Exception as error:
                _log_cleanup_failure(
                    key.organization_id, WebRTCCleanupStep.VOICE_RUNTIME, error
                )

    async def _expire_negotiation(
        self,
        key: WebRTCSessionKey,
        negotiation_id: str,
    ) -> None:
        try:
            await asyncio.sleep(NEGOTIATION_DEADLINE_SECONDS)
            session = self._sessions.get(key)
            if session is None or session.negotiation_id != negotiation_id:
                return
            await self._terminal_cleanup(
                key, BrowserVoiceTerminationReason.NEGOTIATION_TIMEOUT
            )
        except asyncio.CancelledError:
            raise

    async def _detach(self, key: WebRTCSessionKey, session: WebRTCSession) -> None:
        async with self._registry_lock:
            if self._sessions.get(key) is session:
                self._sessions.pop(key, None)


def _deployment_mode() -> IceDeploymentMode:
    return (
        IceDeploymentMode.LOCAL
        if settings.ENV.value == "local"
        else IceDeploymentMode.PUBLIC
    )


def _signal_envelope(
    kind: WsEventAction,
    data: WebRTCAnswer | WebRTCHangupNotice,
    *,
    request_id: str | None = None,
) -> JsonObject:
    return {
        "kind": kind,
        "request_id": request_id,
        "data": data.model_dump(mode="json", by_alias=True),
    }


def _candidate_outcome(
    session: WebRTCSession,
    *,
    duplicate: bool,
) -> WebRTCCandidateAccepted:
    return WebRTCCandidateAccepted(
        negotiation_id=session.negotiation_id,
        duplicate=duplicate,
    )


def _cancel_deadline(session: WebRTCSession) -> None:
    task = session.deadline_task
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    session.deadline_task = None


def _log_cleanup_failure(
    organization_id: UUID,
    step: WebRTCCleanupStep,
    error: Exception,
) -> None:
    logger.warning(
        "WebRTC cleanup step failed organization_id=%s step=%s category=%s",
        organization_id,
        step,
        type(error).__name__,
    )
