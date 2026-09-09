"""Translate Flux turn facts directly into canonical speech observations."""

from pydantic import JsonValue

from eylo.sockets.stt.adapters.deepgram_flux_wire import (
    FluxMessageType,
    FluxTurnEvent,
    FluxTurnInfo,
)
from eylo.sockets.stt.schemas import (
    STTEvent,
    STTEventType,
    STTInterruptionHint,
    STTProvider,
    TimedWord,
)

_MILLISECONDS_PER_SECOND = 1000
_EVENT_TYPES = {
    FluxTurnEvent.START_OF_TURN: STTEventType.START_OF_TURN,
    FluxTurnEvent.UPDATE: STTEventType.TRANSCRIPT_PARTIAL,
    FluxTurnEvent.EAGER_END_OF_TURN: STTEventType.TRANSCRIPT_PREFLIGHT,
    FluxTurnEvent.END_OF_TURN: STTEventType.TRANSCRIPT_FINAL,
    FluxTurnEvent.TURN_RESUMED: STTEventType.TURN_RESUMED,
}
_ACTIVITY_EVENTS = frozenset({FluxTurnEvent.START_OF_TURN, FluxTurnEvent.TURN_RESUMED})


def flux_turn_event(native: FluxTurnInfo, *, model: str) -> STTEvent:
    """Preserve complete hypotheses; only confirmed EndOfTurn is final.

    A turn index is stream-local, not a platform request ID. Keep it beside the
    provider's stream ID and sequence in metadata. Platform policy owns barge-in.
    """
    metadata: dict[str, JsonValue] = {
        "turn_index": native.turn_index,
        "sequence_id": native.sequence_id,
        "end_of_turn_confidence": native.end_of_turn_confidence,
    }
    if native.trigger is not None:
        metadata["trigger"] = native.trigger.value
    if native.languages is not None:
        metadata["languages"] = list(native.languages)
    if native.languages_hinted is not None:
        metadata["languages_hinted"] = list(native.languages_hinted)
    return STTEvent(
        type=_EVENT_TYPES[native.event],
        provider=STTProvider.DEEPGRAM_FLUX,
        model=model,
        provider_request_id=native.request_id,
        transcript=native.transcript,
        audio_start_ms=round(native.audio_window_start * _MILLISECONDS_PER_SECOND),
        audio_end_ms=round(native.audio_window_end * _MILLISECONDS_PER_SECOND),
        words=tuple(
            TimedWord(
                word=word.word,
                confidence=word.confidence,
                start_time=word.start,
                end_time=word.end,
            )
            for word in native.words
        ),
        interruption_hint=STTInterruptionHint.REQUESTED
        if native.event in _ACTIVITY_EVENTS
        else STTInterruptionHint.NONE,
        vendor_metadata=metadata,
    )


def flux_stream_final_event(native: FluxTurnInfo, *, model: str) -> STTEvent | None:
    """At requested stream EOF, retain the unfinished hypothesis without a fake EOT."""
    if native.event is FluxTurnEvent.END_OF_TURN or not native.transcript:
        return None
    event = flux_turn_event(native, model=model)
    return event.model_copy(
        update={
            "type": STTEventType.TRANSCRIPT_FINAL,
            "interruption_hint": STTInterruptionHint.NONE,
            "vendor_metadata": {
                **event.vendor_metadata,
                "finalization_reason": FluxMessageType.CLOSE_STREAM.value,
            },
        }
    )
