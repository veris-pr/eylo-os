"""Conversation-to-session TTS routing.

WebSocket managers own connection/session transport mechanics. This module owns
the voice-pipeline step that turns conversation-level TTS payloads into per
session TTS manager queue items and request-state updates.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from eylo.pipelines.voice.live_buffer import (
    LiveVoiceBuffer,
    LiveVoiceDraft,
    LiveVoiceItemKind,
)
from eylo.pipelines.voice.request_state import (
    VoiceRequestSource,
    VoiceRequestState,
    VoiceRequestStatus,
)
from eylo.pipelines.voice.tts_payloads import (
    TTSRequest,
    TTSTextRequest,
    validate_tts_request,
)

logger = logging.getLogger(__name__)


class TTSQueue(Protocol):
    """Speech input port; runtime managers own queue capacity and playback."""

    async def add_to_request_queue(self, tts_item: TTSRequest) -> None: ...


class VoiceSessionState(Protocol):
    """Read-only session resources and request-state operations used by routing."""

    @property
    def tts_socket(self) -> TTSQueue | None: ...

    @property
    def live_voice_buffer(self) -> LiveVoiceBuffer | None: ...

    def start_voice_request(
        self,
        *,
        request_id: UUID,
        conversation_id: UUID,
        source: VoiceRequestSource,
        status: VoiceRequestStatus,
    ) -> VoiceRequestState: ...

    def mark_voice_request(
        self,
        request_id: UUID | str | None,
        status: VoiceRequestStatus,
        *,
        conversation_id: UUID | None = None,
        turn_id: str | None = None,
    ) -> VoiceRequestState | None: ...


class ConversationSessionRouter(Protocol):
    """Resolve only the voice sessions registered to an org/conversation pair."""

    async def get_sessions_for_conversation(
        self,
        organization_id: UUID,
        conversation_id: UUID,
    ) -> Collection[str]: ...

    def get_session_state(
        self,
        organization_id: UUID,
        session_id: str,
    ) -> VoiceSessionState | None: ...


async def enqueue_conversation_tts_payload(
    *,
    router: ConversationSessionRouter,
    conversation_id: UUID,
    organization_id: UUID,
    payload: TTSRequest,
) -> None:
    """Enqueue a conversation-level TTS payload into all active voice sessions."""
    tts_item = validate_tts_request(payload)
    session_ids = await router.get_sessions_for_conversation(
        organization_id,
        conversation_id,
    )

    if not session_ids:
        logger.debug("[TTS_PIPELINE] No session_ids for conversation, skipping TTS")
        return

    for session_id in session_ids:
        session_state = router.get_session_state(
            organization_id,
            session_id,
        )
        if not session_state:
            continue

        tts_socket = session_state.tts_socket
        if tts_socket is None:
            logger.debug(
                "[TTS_PIPELINE] session %s: tts_socket is None, skipping",
                session_id,
            )
            continue

        await _capture_policy_speech(
            session_state=session_state,
            conversation_id=conversation_id,
            item=tts_item,
        )
        session_state.mark_voice_request(
            tts_item.request_id,
            VoiceRequestStatus.TTS_QUEUED,
            conversation_id=conversation_id,
            turn_id=tts_item.turn_id,
        )

        logger.debug(
            "[TTS_PIPELINE] Enqueuing to TTS request_queue: type=%s",
            tts_item.type.value,
        )
        await tts_socket.add_to_request_queue(tts_item)


async def _capture_policy_speech(
    *,
    session_state: VoiceSessionState,
    conversation_id: UUID,
    item: TTSRequest,
) -> None:
    if not isinstance(item, TTSTextRequest) or item.policy_source is None:
        return
    if not item.text or session_state.live_voice_buffer is None:
        logger.error("Policy TTS payload cannot be captured in live voice state.")
        return
    assert item.request_id is not None  # Required by the policy request contract.
    session_state.start_voice_request(
        request_id=item.request_id,
        conversation_id=conversation_id,
        source=item.policy_source,
        status=VoiceRequestStatus.TTS_QUEUED,
    )
    await session_state.live_voice_buffer.append_turn(
        [
            LiveVoiceDraft(
                kind=LiveVoiceItemKind.SYSTEM_SPEECH,
                payload=item.text,
                request_id=item.request_id,
                policy_source=item.policy_source,
            )
        ]
    )
