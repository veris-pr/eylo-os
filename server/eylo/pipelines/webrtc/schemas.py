"""Private WebRTC negotiation aggregate and signaling contracts."""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Literal
from uuid import UUID

from aiortc import RTCIceCandidate, RTCIceServer
from pydantic import BaseModel, ConfigDict, Field, InstanceOf, field_serializer
from pydantic.json_schema import SkipJsonSchema

from eylo.common.contracts.provider_config import Capability
from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.common.contracts.websocket import WEBRTC_SIGNALING_VERSION
from eylo.pipelines.webrtc.agent_peer import AgentPeerClient, SessionDescriptionType
from eylo.pipelines.webrtc.config import BrowserIceServer
from eylo.pipelines.webrtc.errors import WebRTCFailureCode, WebRTCSignalingCode
from eylo.pipelines.websocket.schemas import WSSessionState


class WebRTCSignalCommand(StrEnum):
    PREPARE = "prepare"
    OFFER = "offer"
    ANSWER = "answer"
    CANDIDATE = "candidate"
    ICE_CANDIDATE = "ice_candidate"
    HANGUP = "hangup"


class WebRTCSignalOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class WebRTCSignal(BaseModel):
    """Wire values are emitted only by the WebSocket interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    protocol_version: int = WEBRTC_SIGNALING_VERSION


class WebRTCPrepared(WebRTCSignal):
    command: Literal[WebRTCSignalCommand.PREPARE] = WebRTCSignalCommand.PREPARE
    outcome: Literal[WebRTCSignalOutcome.ACCEPTED] = WebRTCSignalOutcome.ACCEPTED
    negotiation_id: str
    negotiation_expires_at: float | None
    credential_expires_at: float | None
    ice_servers: tuple[BrowserIceServer, ...] = Field(
        serialization_alias="iceServers", repr=False
    )

    @field_serializer("ice_servers")
    def _ice_servers(
        self, value: tuple[BrowserIceServer, ...]
    ) -> list[dict[str, object]]:
        """Omit absent ICE auth without omitting the enclosing nullable expiry."""
        return [server.model_dump(mode="json", exclude_none=True) for server in value]


class WebRTCCandidateAccepted(WebRTCSignal):
    command: Literal[WebRTCSignalCommand.CANDIDATE] = WebRTCSignalCommand.CANDIDATE
    outcome: Literal[WebRTCSignalOutcome.ACCEPTED] = WebRTCSignalOutcome.ACCEPTED
    negotiation_id: str
    duplicate: bool


class WebRTCCleanupReason(StrEnum):
    HANGUP = "hangup"
    SHUTDOWN = "shutdown"


class WebRTCCleanupStep(StrEnum):
    NOTIFY = "notify"
    TTS_STREAMER = "tts_streamer"
    PEER = "peer"
    VOICE_RUNTIME = "voice_runtime"


class WebRTCHangupNotice(WebRTCSignal):
    command: Literal[WebRTCSignalCommand.HANGUP] = WebRTCSignalCommand.HANGUP
    outcome: Literal[WebRTCSignalOutcome.ACCEPTED] = WebRTCSignalOutcome.ACCEPTED
    negotiation_id: str
    reason: BrowserVoiceTerminationReason | WebRTCCleanupReason


class WebRTCHangupAccepted(WebRTCSignal):
    command: Literal[WebRTCSignalCommand.HANGUP] = WebRTCSignalCommand.HANGUP
    outcome: Literal[WebRTCSignalOutcome.ACCEPTED] = WebRTCSignalOutcome.ACCEPTED
    already_terminated: bool


class WebRTCRejected(WebRTCSignal):
    command: WebRTCSignalCommand
    outcome: Literal[WebRTCSignalOutcome.REJECTED] = WebRTCSignalOutcome.REJECTED
    code: WebRTCFailureCode


class WebRTCNotConfigured(WebRTCSignal):
    command: Literal[WebRTCSignalCommand.PREPARE] = WebRTCSignalCommand.PREPARE
    outcome: Literal[WebRTCSignalOutcome.REJECTED] = WebRTCSignalOutcome.REJECTED
    code: Literal[WebRTCSignalingCode.NOT_CONFIGURED] = (
        WebRTCSignalingCode.NOT_CONFIGURED
    )
    capability: Capability
    missing: tuple[str, ...]
    configure_via: str


class WebRTCAnswer(WebRTCSignal):
    """Immutable replayable answer, excluding live peer resources."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    protocol_version: int = WEBRTC_SIGNALING_VERSION
    command: Literal[WebRTCSignalCommand.ANSWER] = WebRTCSignalCommand.ANSWER
    outcome: Literal[WebRTCSignalOutcome.ACCEPTED] = WebRTCSignalOutcome.ACCEPTED
    negotiation_id: str
    sdp: str = Field(min_length=1)
    type: Literal[SessionDescriptionType.ANSWER] = SessionDescriptionType.ANSWER


type WebRTCResponse = (
    WebRTCPrepared
    | WebRTCAnswer
    | WebRTCCandidateAccepted
    | WebRTCHangupNotice
    | WebRTCHangupAccepted
    | WebRTCRejected
    | WebRTCNotConfigured
)


class WebRTCNegotiationState(StrEnum):
    """Monotonic lifecycle for one tenant-bound negotiation."""

    PREPARING = "preparing"
    PREPARED = "prepared"
    ACQUIRING = "acquiring"
    ACTIVE = "active"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


class WebRTCSessionKey(BaseModel):
    """Immutable WebRTC authority key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: UUID
    session_id: str


class WebRTCSession(BaseModel):
    """Manager-owned negotiation; live resources and ICE secrets never serialize."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    key: WebRTCSessionKey
    session_state: SkipJsonSchema[InstanceOf[WSSessionState]] = Field(exclude=True)
    negotiation_id: str
    state: WebRTCNegotiationState = WebRTCNegotiationState.PREPARING
    ice_servers: SkipJsonSchema[tuple[InstanceOf[RTCIceServer], ...]] = Field(
        default=(), exclude=True
    )
    negotiation_expires_at: float | None = None
    credential_expires_at: float | None = None
    peer_client: SkipJsonSchema[InstanceOf[AgentPeerClient] | None] = Field(
        default=None, exclude=True
    )
    tts_streamer_task: SkipJsonSchema[InstanceOf[asyncio.Task[None]] | None] = Field(
        default=None, exclude=True
    )
    deadline_task: SkipJsonSchema[InstanceOf[asyncio.Task[None]] | None] = Field(
        default=None, exclude=True
    )
    answer_payload: WebRTCAnswer | None = Field(default=None, exclude=True)
    offer_digest: str | None = None
    pending_candidates: SkipJsonSchema[list[InstanceOf[RTCIceCandidate] | None]] = (
        Field(default_factory=list, exclude=True)
    )
    candidate_digests: set[str] = Field(default_factory=set)
    lock: SkipJsonSchema[InstanceOf[asyncio.Lock]] = Field(
        default_factory=asyncio.Lock, exclude=True
    )
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    connected_at: float | None = None
    terminated_at: float | None = None

    @property
    def organization_id(self) -> UUID:
        return self.key.organization_id

    @property
    def session_id(self) -> str:
        return self.key.session_id

    def transition(self, state: WebRTCNegotiationState) -> None:
        self.state = state
        self.updated_at = time.time()
        if state is WebRTCNegotiationState.ACTIVE:
            self.connected_at = self.updated_at
        elif state is WebRTCNegotiationState.TERMINATED:
            self.terminated_at = self.updated_at
