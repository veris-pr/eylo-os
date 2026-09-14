"""Constants and enums for voice transcript persistence."""

from enum import Enum, StrEnum

from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_REDACTION_VERSION as VOICE_MESSAGE_META_REDACTION_VERSION,
)
from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_RUNTIME_MODE as VOICE_MESSAGE_META_RUNTIME_MODE,
)
from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_SESSION_ID as VOICE_MESSAGE_META_SESSION_ID,
)
from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_SESSION_ROW_ID as VOICE_MESSAGE_META_SESSION_ROW_ID,
)
from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_SOURCE_SEQUENCE as VOICE_MESSAGE_META_SOURCE_SEQUENCE,
)
from eylo.common.contracts.voice import (
    VOICE_MESSAGE_META_SPEECH_OUTCOME as VOICE_MESSAGE_META_SPEECH_OUTCOME,
)
from eylo.common.contracts.voice import (
    VoiceRuntimeMode as VoiceRuntimeMode,
)
from eylo.common.contracts.voice import (
    VoiceSpeechOutcome as VoiceSpeechOutcome,
)


class VoiceSessionStatus(str, Enum):
    """Lifecycle states for a durable voice transcript session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class VoiceRedactionState(StrEnum):
    """Stored segment processing state; this is not a session lifecycle."""

    NONE = "none"
    CLEAN = "clean"
    REDACTED = "redacted"


class VoiceCanonicalState(str, Enum):
    """Outcome of destructive post-call canonical history processing."""

    NOT_RUN = "not_run"
    CLEAN = "clean"
    REDACTED = "redacted"
    FAILED = "failed"
    NO_STORAGE = "no_storage"


class VoiceCanonicalFailureCode(StrEnum):
    """Content-free reasons a session's canonical history could not be stored."""

    STORAGE_DECISION_UNAVAILABLE = "storage_decision_unavailable"
    STORAGE_DECISION_CONFLICT = "storage_decision_conflict"
    SOURCE_ORDER_INVALID = "source_order_invalid"
    SOURCE_CAPTURE_INCOMPLETE = "source_capture_incomplete"
    SOURCE_CAPACITY_EXCEEDED = "source_capacity_exceeded"
    SOURCE_INVALID_PAYLOAD = "source_invalid_payload"
    REDACTED_PAYLOAD_INVALID = "redacted_payload_invalid"
    REDACTION_FAILED = "redaction_failed"
    PROJECTION_FAILED = "projection_failed"
    PARTICIPANT_AUTHORITY_UNAVAILABLE = "participant_authority_unavailable"
    PARTICIPANT_AUTHORITY_CONFLICT = "participant_authority_conflict"
    TOOL_CALL_INVALID = "tool_call_invalid"
    TOOL_RESULT_INVALID = "tool_result_invalid"
    MESSAGE_PROJECTION_UNAVAILABLE = "message_projection_unavailable"
    POLICY_SOURCE_UNAVAILABLE = "policy_source_unavailable"
    TEXT_PAYLOAD_INVALID = "text_payload_invalid"
    ASSISTANT_SPEECH_OUTCOME_UNAVAILABLE = "assistant_speech_outcome_unavailable"


VOICE_CANONICAL_REDACTION_VERSION = 1


class VoiceSegmentRole(str, Enum):
    """Speaker or actor represented by a timeline segment."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class VoiceSegmentType(str, Enum):
    """Kinds of timeline entries in a voice transcript."""

    SPEECH = "speech"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    EVENT = "event"
    SILENCE = "silence"


class VoiceSegmentSource(str, Enum):
    """Subsystem that produced a voice transcript segment."""

    STT = "stt"
    TTS = "tts"
    REALTIME = "realtime"
    TELEPHONY = "telephony"
    TOOL = "tool"
    SYSTEM = "system"
    MESSAGE = "message"


class VoiceAudioTrackKind(str, Enum):
    """Audio track associated with a segment."""

    USER = "user"
    ASSISTANT = "assistant"
    COMBINED = "combined"
