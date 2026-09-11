"""Route the Agent's end-call request to the exact live voice transport."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.common.contracts.telephony import CallEndedReason
from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.modules.session_context.schemas import SessionChannel, SessionContext
from eylo.modules.voice_transcripts.constants import VoiceRuntimeMode
from eylo.pipelines.voice.live_buffer import LiveVoiceBufferIdentity
from eylo.pipelines.voice.request_state import VoiceRequestSource

if TYPE_CHECKING:
    from eylo.pipelines.agent_execution_context import PlatformExecutionContext
    from eylo.pipelines.telephony.sessions import CallSession
    from eylo.pipelines.websocket.schemas import WSSessionState

logger = logging.getLogger(__name__)

END_CALL_TOOL_NAME = "end_call"
SessionT = TypeVar("SessionT")


class VoiceTerminationStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class VoiceTerminationFailureCode(StrEnum):
    SESSION_NOT_AVAILABLE = "voice_session_not_available"
    TERMINATION_NOT_ACCEPTED = "voice_termination_not_accepted"


class _VoiceTerminationValue(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class VoiceTerminationAccepted(_VoiceTerminationValue):
    status: Literal[VoiceTerminationStatus.SUCCESS] = VoiceTerminationStatus.SUCCESS
    message: Literal["Voice session termination requested."] = (
        "Voice session termination requested."
    )


class VoiceTerminationFailure(_VoiceTerminationValue):
    status: Literal[VoiceTerminationStatus.ERROR] = VoiceTerminationStatus.ERROR
    error: VoiceTerminationFailureCode
    message: Literal["The active voice session could not be ended."] = (
        "The active voice session could not be ended."
    )


class VoiceTerminationMetadata(_VoiceTerminationValue):
    """Omit runtime mode on refusals, preserving the existing transcript shape."""

    voice_termination: Literal[True] = True
    runtime_mode: VoiceRuntimeMode | None = None


class AgentVoiceTerminationOutcome(_VoiceTerminationValue):
    """Safe tool result for one exact live voice termination request."""

    content: VoiceTerminationAccepted | VoiceTerminationFailure = Field(
        discriminator="status"
    )
    metadata: VoiceTerminationMetadata

    @property
    def is_error(self) -> bool:
        return isinstance(self.content, VoiceTerminationFailure)

    @model_validator(mode="after")
    def require_matching_runtime(self) -> Self:
        """Only accepted requests identify a transport in the result metadata."""
        if self.is_error == (self.metadata.runtime_mode is not None):
            raise ValueError("Voice termination metadata differs from its result.")
        return self


async def is_live_voice_session_active(identity: LiveVoiceBufferIdentity) -> bool:
    """Return whether the exact in-memory voice authority is still active."""
    if identity.runtime_mode is VoiceRuntimeMode.TELEPHONY:
        return _resolve_telephony_session(identity) is not None
    return await _resolve_browser_session(identity) is not None


async def execute_agent_end_call_tool(
    *,
    conversation_context: PlatformExecutionContext,
    identity: LiveVoiceBufferIdentity,
) -> AgentVoiceTerminationOutcome:
    """Request teardown through the owner of the exact active voice transport."""
    conversation = conversation_context.conversation
    if (
        identity.organization_id != conversation.organization_id
        or identity.conversation_id != conversation.id
    ):
        logger.error("Live voice end-call authority did not match the conversation.")
        return _error_outcome(VoiceTerminationFailureCode.SESSION_NOT_AVAILABLE)

    if identity.runtime_mode is VoiceRuntimeMode.TELEPHONY:
        return await _end_telephony_session(identity)
    return await _end_browser_session(identity)


async def _end_telephony_session(
    identity: LiveVoiceBufferIdentity,
) -> AgentVoiceTerminationOutcome:
    from eylo.pipelines.telephony.voice import terminate_telephony_voice

    session = _resolve_telephony_session(identity)
    if session is None or session.telephony_manager is None:
        return _error_outcome(VoiceTerminationFailureCode.SESSION_NOT_AVAILABLE)

    accepted = await terminate_telephony_voice(
        sess=session,
        telephony_manager=session.telephony_manager,
        ended_reason=CallEndedReason.AGENT_ENDED_CALL,
        source=VoiceRequestSource.END_CALL,
    )
    return _termination_outcome(accepted, identity.runtime_mode)


async def _end_browser_session(
    identity: LiveVoiceBufferIdentity,
) -> AgentVoiceTerminationOutcome:
    from eylo.pipelines.voice.browser import request_browser_voice_termination

    session = await _resolve_browser_session(identity)
    if session is None:
        return _error_outcome(VoiceTerminationFailureCode.SESSION_NOT_AVAILABLE)

    context = SessionContext(
        channel=SessionChannel.WEBSOCKET,
        organization_id=identity.organization_id,
        session_id=session.session_id,
        contact_id=session.contact_id,
        voice_session_id=identity.voice_session_id,
        authorized_conversation_id=identity.conversation_id,
        ws=session,
    )
    accepted = await request_browser_voice_termination(
        context,
        reason=BrowserVoiceTerminationReason.AGENT_ENDED_CALL,
        notify_client=True,
        source=VoiceRequestSource.END_CALL,
    )
    return _termination_outcome(accepted, identity.runtime_mode)


def _resolve_telephony_session(
    identity: LiveVoiceBufferIdentity,
) -> CallSession | None:
    from eylo.pipelines.telephony.sessions import S_CALLS

    matches = [
        session
        for session in S_CALLS.active_sessions()
        if session.is_active
        and not session.termination_requested
        and session.organization_id == identity.organization_id
        and session.conversation_id == identity.conversation_id
        and session.call_sid == identity.session_id
        and session.voice_session_id == identity.voice_session_id
        and session.live_voice_buffer is not None
        and session.live_voice_buffer.identity == identity
    ]
    return _one_exact_session(matches, identity.runtime_mode)


async def _resolve_browser_session(
    identity: LiveVoiceBufferIdentity,
) -> WSSessionState | None:
    from eylo.pipelines.websocket.singleton import S_ws_manager

    session_ids = await S_ws_manager.get_sessions_for_conversation(
        identity.organization_id,
        identity.conversation_id,
    )
    matches: list[WSSessionState] = []
    for session_id in session_ids:
        session = S_ws_manager.get_session_state(
            identity.organization_id,
            str(session_id),
        )
        if (
            session is not None
            and session.is_voice_mode
            and not session.voice_termination_complete
            and session.voice_call_id == identity.session_id
            and session.voice_session_id == identity.voice_session_id
            and session.live_voice_buffer is not None
            and session.live_voice_buffer.identity == identity
        ):
            matches.append(session)
    return _one_exact_session(matches, identity.runtime_mode)


def _one_exact_session(
    matches: Sequence[SessionT],
    runtime_mode: VoiceRuntimeMode,
) -> SessionT | None:
    if len(matches) > 1:
        logger.error(
            "Live voice end-call authority was ambiguous runtime_mode=%s.",
            runtime_mode.value,
        )
        return None
    return matches[0] if matches else None


def _termination_outcome(
    accepted: bool,
    runtime_mode: VoiceRuntimeMode,
) -> AgentVoiceTerminationOutcome:
    if not accepted:
        return _error_outcome(VoiceTerminationFailureCode.TERMINATION_NOT_ACCEPTED)
    return AgentVoiceTerminationOutcome(
        content=VoiceTerminationAccepted(),
        metadata=VoiceTerminationMetadata(runtime_mode=runtime_mode),
    )


def _error_outcome(code: VoiceTerminationFailureCode) -> AgentVoiceTerminationOutcome:
    return AgentVoiceTerminationOutcome(
        content=VoiceTerminationFailure(error=code),
        metadata=VoiceTerminationMetadata(),
    )


__all__ = [
    "END_CALL_TOOL_NAME",
    "AgentVoiceTerminationOutcome",
    "execute_agent_end_call_tool",
    "is_live_voice_session_active",
]
