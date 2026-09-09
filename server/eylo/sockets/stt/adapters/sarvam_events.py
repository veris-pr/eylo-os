"""Translate Sarvam-native facts without inventing partials or transcript confidence."""

from eylo.sockets.stt.adapters.sarvam_wire import (
    SarvamSignalType,
    SarvamTranscript,
    SarvamVadEvent,
)
from eylo.sockets.stt.schemas import (
    STTEvent,
    STTEventType,
    STTInterruptionHint,
    STTProvider,
)


def sarvam_transcript_event(native: SarvamTranscript, *, model: str) -> STTEvent:
    """A language probability is not recognition confidence or an audio offset."""
    data = native.data
    return STTEvent(
        type=STTEventType.TRANSCRIPT_FINAL,
        provider=STTProvider.SARVAM,
        model=model,
        transcript=data.transcript,
        provider_request_id=data.request_id,
        language=data.language_code,
        vendor_metadata={
            "audio_duration": data.metrics.audio_duration,
            "processing_latency": data.metrics.processing_latency,
            "language_probability": data.language_probability,
        },
    )


def sarvam_speech_started_event(native: SarvamVadEvent, *, model: str) -> STTEvent:
    """The platform owns interruption policy; this event is only an activity hint."""
    if native.data.signal_type is not SarvamSignalType.START_SPEECH:
        raise ValueError("A speech-start event requires a native speech-start signal.")
    event = STTEvent(
        type=STTEventType.SPEECH_START,
        provider=STTProvider.SARVAM,
        model=model,
        interruption_hint=STTInterruptionHint.REQUESTED,
    )
    data = native.data
    timestamp = data.occured_at
    if timestamp is None and data.timestamp is not None:
        timestamp = data.timestamp.timestamp()
    if timestamp is not None:
        return event.model_copy(update={"timestamp": timestamp})
    return event
