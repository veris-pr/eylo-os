"""Structural contracts for in-memory interface session state."""

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID

from eylo.common.contracts.voice import (
    BrowserVoiceTerminationReason,
    RecordingDisclosureState,
)


class SessionChannel(str, Enum):
    """Interface identity shared by live sessions and persisted interaction facts."""

    HTTP = "http"
    WEBSOCKET = "websocket"
    TELEPHONY = "telephony"
    WEBRTC = "webrtc"


class RecordingDisclosureStatePort(Protocol):
    """Notification state shared by browser and carrier sessions, not recording control."""

    recording_consent_state: RecordingDisclosureState


@runtime_checkable
class WebSocketSessionStatePort(RecordingDisclosureStatePort, Protocol):
    """Fields session composition consumes from a WebSocket runtime."""

    organization_id: UUID
    session_id: str
    user_session_id: UUID | None
    contact_id: UUID | None
    agent_id: UUID | None
    voice_session_id: UUID | None
    is_voice_mode: bool
    voice_termination_reason: BrowserVoiceTerminationReason | None
    voice_termination_lock: asyncio.Lock
    voice_termination_task: asyncio.Task[bool] | None
    voice_termination_complete: bool
    voice_terminal_callback: Callable[[BrowserVoiceTerminationReason], Awaitable[None]] | None


@runtime_checkable
class WebRTCSessionStatePort(Protocol):
    """Fields session composition retains from a WebRTC runtime."""

    organization_id: UUID
    session_id: str
    session_state: WebSocketSessionStatePort


@runtime_checkable
class TelephonySessionStatePort(Protocol):
    """Read-only fields session composition consumes from a live call."""

    agent_id: UUID | None
    user_session_id: UUID | None
    voice_session_id: UUID | None
