"""In-memory call sessions for telephony pipeline orchestration."""

import asyncio
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, InstanceOf, StrictBool
from pydantic.json_schema import SkipJsonSchema

from eylo.common.contracts.voice import RecordingDisclosureState
from eylo.events.schema.py_events.call import CallDirection
from eylo.modules.voice.schemas.api import VoiceConfig
from eylo.pipelines.voice.live_buffer import LiveVoiceBuffer
from eylo.pipelines.voice.recording import AudioRecorder
from eylo.pipelines.voice.stt import STTRealtime
from eylo.pipelines.voice.transcript_inputs import VoiceTranscriptInput
from eylo.pipelines.voice.tts import TTSRealtime
from eylo.pipelines.voice.tts_payloads import TTSRequest
from eylo.sockets.telephony.base import CallEndedReason
from eylo.sockets.telephony.config import TelephonyProvider
from eylo.sockets.telephony.manager import TelephonyRealtime


class CallSessionState(str, Enum):
    """Whether media work may still run on this process-local session."""

    ACTIVE = "active"
    ENDED = "ended"


class CallTerminationState(str, Enum):
    """Idempotency latch for carrier termination, owned under its lock."""

    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"


class CallFinalizationState(str, Enum):
    """Finalization remains pending after failure so cleanup can be retried."""

    PENDING = "pending"
    COMPLETE = "complete"


@runtime_checkable
class CallTurnRunner(Protocol):
    """Teardown's narrow port; the voice runner owns its execution internals."""

    async def drain(self) -> None: ...


class CallSessionMetadata(BaseModel):
    """Product references and control outcomes, not an arbitrary vendor payload."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    campaign_id: UUID | None = Field(default=None, frozen=True)
    campaign_contact_id: UUID | None = Field(default=None, frozen=True)
    campaign_attempt_id: UUID | None = Field(default=None, frozen=True)
    transfer_to: str | None = None
    termination_failure_code: str | None = None


class CallSession(BaseModel):
    """Validated live resources; immutable registry identity survives teardown.

    Handles are process-local and excluded from snapshots. Payload validation
    remains owned by queue producers; handle checks establish instance identity.
    """

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, hide_input_in_errors=True
    )

    call_sid: str = Field(frozen=True, min_length=1)
    organization_id: UUID = Field(frozen=True)
    provider: TelephonyProvider = Field(frozen=True)
    direction: CallDirection
    call_id: UUID | None = None
    stream_sid: str | None = None
    agent_id: UUID | None = Field(default=None, frozen=True)
    agent_revision: int | None = Field(default=None, frozen=True, gt=0, strict=True)
    from_number: str | None = Field(default=None, repr=False)
    to_number: str | None = Field(default=None, repr=False)
    conversation_id: UUID | None = None
    user_session_id: UUID | None = None
    stt: SkipJsonSchema[InstanceOf[STTRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    tts: SkipJsonSchema[InstanceOf[TTSRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    telephony_manager: SkipJsonSchema[InstanceOf[TelephonyRealtime] | None] = Field(
        default=None, exclude=True, repr=False
    )
    stt_request_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[bytes]] | None] = Field(
        default=None, exclude=True, repr=False
    )
    stt_response_queue: SkipJsonSchema[
        InstanceOf[asyncio.Queue[VoiceTranscriptInput]] | None
    ] = Field(default=None, exclude=True, repr=False)
    tts_request_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[TTSRequest]] | None] = (
        Field(default=None, exclude=True, repr=False)
    )
    tts_response_queue: SkipJsonSchema[InstanceOf[asyncio.Queue[bytes]] | None] = Field(
        default=None, exclude=True, repr=False
    )
    stt_tasks: SkipJsonSchema[dict[str, InstanceOf[asyncio.Task[None]]]] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    tts_tasks: SkipJsonSchema[dict[str, InstanceOf[asyncio.Task[None]]]] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    policy_tasks: SkipJsonSchema[dict[str, InstanceOf[asyncio.Task[None]]]] = Field(
        default_factory=dict, exclude=True, repr=False
    )
    tts_interrupt_event: SkipJsonSchema[InstanceOf[asyncio.Event]] = Field(
        default_factory=asyncio.Event, exclude=True, repr=False
    )
    state: CallSessionState = CallSessionState.ACTIVE
    first_media_received: StrictBool = False
    ended_reason: CallEndedReason | None = None
    auth_session_token: SkipJsonSchema[str | None] = Field(
        default=None, exclude=True, repr=False
    )
    provider_config_id: UUID | None = Field(default=None, frozen=True)
    provider_config_revision: int | None = Field(
        default=None, frozen=True, gt=0, strict=True
    )
    started_at: datetime | None = None
    connected_at: datetime | None = None
    extra_data: CallSessionMetadata = Field(default_factory=CallSessionMetadata)
    voice_config: VoiceConfig | None = None
    # Voice recording (non-blocking audio capture)
    # Notification state mirrors WSSessionState. It never gates the recorder;
    # it records whether the configured disclosure was delivered.
    recording_consent_state: RecordingDisclosureState = (
        RecordingDisclosureState.NOT_REQUIRED
    )
    audio_recorder: SkipJsonSchema[InstanceOf[AudioRecorder] | None] = Field(
        default=None, exclude=True, repr=False
    )
    # Durable voice_sessions row id, set once transcript projection starts.
    voice_session_id: UUID | None = None
    live_voice_buffer: SkipJsonSchema[InstanceOf[LiveVoiceBuffer] | None] = Field(
        default=None, exclude=True, repr=False
    )
    live_voice_turn_runner: SkipJsonSchema[InstanceOf[CallTurnRunner] | None] = Field(
        default=None, exclude=True, repr=False
    )
    opener_text: str | None = Field(default=None, repr=False)
    carrier_audio_chunks: int = Field(default=0, ge=0, strict=True)
    carrier_audio_bytes: int = Field(default=0, ge=0, strict=True)
    comfort_audio_chunks: int = Field(default=0, ge=0, strict=True)
    comfort_audio_bytes: int = Field(default=0, ge=0, strict=True)
    finalization_lock: SkipJsonSchema[InstanceOf[asyncio.Lock]] = Field(
        default_factory=asyncio.Lock, exclude=True, repr=False
    )
    termination_lock: SkipJsonSchema[InstanceOf[asyncio.Lock]] = Field(
        default_factory=asyncio.Lock, exclude=True, repr=False
    )
    termination_state: CallTerminationState = CallTerminationState.NOT_REQUESTED
    finalization_state: CallFinalizationState = CallFinalizationState.PENDING
    manager_closed_ws: StrictBool = False

    @property
    def is_active(self) -> bool:
        return self.state is CallSessionState.ACTIVE

    @property
    def termination_requested(self) -> bool:
        return self.termination_state is CallTerminationState.REQUESTED

    @property
    def finalized(self) -> bool:
        return self.finalization_state is CallFinalizationState.COMPLETE


class MediaSessionKey(BaseModel):
    """Immutable identity for one organization-owned carrier media session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: UUID
    provider: TelephonyProvider
    call_sid: str = Field(min_length=1)


class DuplicateMediaSessionError(ValueError):
    """An active carrier session already owns the exact registry identity."""


class AmbiguousMediaSessionError(ValueError):
    """An unscoped carrier ID matches more than one organization's session."""


class CallSessionRegistry:
    """Process-local index; scoped identity and instance ownership govern removal."""

    def __init__(self) -> None:
        self._sessions: dict[MediaSessionKey, CallSession] = {}

    @staticmethod
    def key_for(session: CallSession) -> MediaSessionKey:
        return MediaSessionKey(
            organization_id=session.organization_id,
            provider=session.provider,
            call_sid=session.call_sid,
        )

    def publish(self, session: CallSession) -> None:
        """Publish one fully initialized session without overwriting another."""
        key = self.key_for(session)
        if key in self._sessions:
            raise DuplicateMediaSessionError(
                "Media session identity is already active."
            )
        self._sessions[key] = session

    def find_by_provider_call(
        self,
        provider: str,
        call_sid: str,
        *,
        organization_id: UUID | None = None,
    ) -> CallSession | None:
        matches = [
            session
            for key, session in self._sessions.items()
            if key.provider == provider
            and key.call_sid == call_sid
            and (organization_id is None or key.organization_id == organization_id)
        ]
        if len(matches) > 1:
            raise AmbiguousMediaSessionError(
                "Carrier call identity is ambiguous across organizations."
            )
        return matches[0] if matches else None

    def remove(self, session: CallSession) -> None:
        """A delayed/repeated teardown cannot remove a replacement session."""
        key = self.key_for(session)
        if self._sessions.get(key) is session:
            del self._sessions[key]

    def active_sessions(self) -> tuple[CallSession, ...]:
        return tuple(self._sessions.values())

    def resolve_session_id(
        self,
        provider: str,
        call_sid: str,
        organization_id: UUID,
    ) -> str | None:
        """Resolve the WS-routable session_id for a call_sid.

        Returns auth_session_token if the call is still active in memory,
        otherwise None (caller should fall back to DB lookup).
        """
        sess = self.find_by_provider_call(
            provider,
            call_sid,
            organization_id=organization_id,
        )
        if sess and sess.auth_session_token:
            return sess.auth_session_token
        return None


S_CALLS = CallSessionRegistry()
