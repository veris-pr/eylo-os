"""Neutral voice values shared by conversation, transcript and voice runtimes."""

from enum import Enum, StrEnum

VOICE_MESSAGE_META_SESSION_ID = "voice_session_id"
VOICE_MESSAGE_META_SESSION_ROW_ID = "voice_session_row_id"
VOICE_MESSAGE_META_RUNTIME_MODE = "voice_runtime_mode"
VOICE_MESSAGE_META_SPEECH_OUTCOME = "speech_turn_outcome"
VOICE_MESSAGE_META_SOURCE_SEQUENCE = "voice_source_sequence"
VOICE_MESSAGE_META_REDACTION_VERSION = "voice_redaction_version"


class InterruptionType(str, Enum):
    TRANSCRIPT = "transcript"
    VAD = "vad"


class VoiceSpeechOutcome(str, Enum):
    """Eylo-owned terminal result for one assistant speech turn."""

    DRAINED = "drained"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VoiceRuntimeMode(str, Enum):
    """Platform runtime producing live and canonical voice history."""

    BROWSER_DECOMPOSED = "browser_decomposed"
    BROWSER_REALTIME = "browser_realtime"
    TELEPHONY = "telephony"


class RecordingDisclosureState(StrEnum):
    """Notification delivery and caller feedback; never permission to record.

    The existing consent-state wire values remain unchanged. GRANTED records
    queued disclosure or caller acknowledgement, not confirmed audio playback.
    """

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    GRANTED = "granted"
    DECLINED = "declined"


class BrowserVoiceTerminationReason(StrEnum):
    """Platform observations ending browser voice, not vendor-native states.

    Preserve these values in signaling and transcript history. Telephony owns
    its separate CallEndedReason vocabulary; matching values do not alias it.
    """

    ADDITIONAL_AUDIO_TRACK = "additional_audio_track"
    AGENT_ENDED_CALL = "agent_ended_call"
    CANDIDATE_DELIVERY_FAILED = "candidate_delivery_failed"
    CLIENT_HANGUP = "client_hangup"
    ICE_CLOSED = "ice_closed"
    ICE_DISCONNECTED = "ice_disconnected"
    ICE_FAILED = "ice_failed"
    MAX_DURATION = "max_duration"
    NEGOTIATION_TIMEOUT = "negotiation_timeout"
    OFFER_FAILED = "offer_failed"
    PEER_CLOSED = "peer_closed"
    PEER_DISCONNECTED = "peer_disconnected"
    PEER_FAILED = "peer_failed"
    PREPARE_FAILED = "prepare_failed"
    REALTIME_DISCONNECTED = "realtime_disconnected"
    REALTIME_HANDOFF_FAILED = "realtime_handoff_failed"
    REALTIME_RECONNECT_FAILED = "realtime_reconnect_failed"
    REALTIME_TRANSPORT_ENDED = "realtime_transport_ended"
    REALTIME_TRANSPORT_ERROR = "realtime_transport_error"
    REALTIME_VENDOR_ERROR = "realtime_vendor_error"
    SILENCE_TIMEOUT = "silence_timeout"
    STT_RUNTIME_FAILED = "stt_runtime_failed"
    TRACK_ENDED = "track_ended"
    TTS_RUNTIME_FAILED = "tts_runtime_failed"
    USER_END_CALL_PHRASE = "user_end_call_phrase"
    VOICE_CLEANUP_WITHOUT_REASON = "voice_cleanup_without_reason"
    VOICE_CONFIGURATION_FAILED = "voice_configuration_failed"
    VOICE_INITIALIZATION_FAILED = "voice_initialization_failed"
    WEBSOCKET_DISCONNECTED = "websocket_disconnected"


__all__ = [
    "BrowserVoiceTerminationReason",
    "InterruptionType",
    "RecordingDisclosureState",
    "VOICE_MESSAGE_META_RUNTIME_MODE",
    "VOICE_MESSAGE_META_REDACTION_VERSION",
    "VOICE_MESSAGE_META_SESSION_ID",
    "VOICE_MESSAGE_META_SESSION_ROW_ID",
    "VOICE_MESSAGE_META_SOURCE_SEQUENCE",
    "VOICE_MESSAGE_META_SPEECH_OUTCOME",
    "VoiceSpeechOutcome",
    "VoiceRuntimeMode",
]
