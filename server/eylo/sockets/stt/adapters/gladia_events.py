"""Translate Gladia Live v2 recognition into canonical STT events."""

from __future__ import annotations

from eylo.sockets.stt.schemas import STTEvent, STTEventType, STTProvider, TimedWord
from eylo.sockets.voice.vendors.gladia.wire import GladiaTranscript

_MILLISECONDS_PER_SECOND = 1000


def gladia_stt_event(event: GladiaTranscript) -> STTEvent:
    """Retain native identities and relative timing; do not infer speaker or model."""
    data = event.data
    utterance = data.utterance
    return STTEvent(
        type=STTEventType.TRANSCRIPT_FINAL
        if data.is_final
        else STTEventType.TRANSCRIPT_PARTIAL,
        provider=STTProvider.GLADIA,
        transcript=utterance.text,
        confidence=utterance.confidence,
        language=utterance.language,
        provider_request_id=str(event.session_id),
        audio_start_ms=int(utterance.start * _MILLISECONDS_PER_SECOND),
        audio_end_ms=int(utterance.end * _MILLISECONDS_PER_SECOND),
        words=tuple(
            TimedWord(
                word=word.word,
                start_time=word.start,
                end_time=word.end,
                confidence=word.confidence,
            )
            for word in utterance.words
        ),
        vendor_metadata={
            "utterance_id": data.id,
            "channel": utterance.channel,
            "created_at": event.created_at.isoformat(),
        },
    )
