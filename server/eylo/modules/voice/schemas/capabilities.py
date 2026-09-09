"""Console capability projections; adapter contracts stay in their sockets."""

from enum import Enum, StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
)

from eylo.modules.voice_configs.catalog import (
    RealtimeProviders,
    STTProviders,
    TTSProviders,
    VoiceKind,
)


class VoiceFeatureSupport(Enum):
    """Explicit support claim; preserve the console's boolean wire format."""

    UNSUPPORTED = False
    SUPPORTED = True

    def __bool__(self) -> bool:
        raise TypeError("Compare voice support with its explicit enum member.")


def _feature_support(value: object) -> VoiceFeatureSupport:
    if isinstance(value, VoiceFeatureSupport):
        return value
    if value is True:
        return VoiceFeatureSupport.SUPPORTED
    if value is False:
        return VoiceFeatureSupport.UNSUPPORTED
    raise ValueError("Voice support requires an explicit choice or boolean.")


class VoiceNativeEncoding(StrEnum):
    """Recognition encodings exposed by the console contract."""

    LINEAR16 = "linear16"
    PCM_S16LE = "pcm_s16le"
    MULAW = "mulaw"
    ALAW = "alaw"


class VoiceSessionUpdateMode(StrEnum):
    """Console vocabulary for how a realtime adapter applies updates."""

    IN_PLACE = "in_place"
    RECONNECT = "reconnect"
    UNSUPPORTED = "unsupported"


class VoicePlatformFeature(StrEnum):
    """Stable identifiers for the existing Eylo-owned policy projection."""

    INTERRUPTION_HANDLING = "interruption_handling"
    SILENCE_POLICY = "silence_policy"
    DURATION_LIMIT = "duration_limit"
    RECORDING_CAPTURE_AND_UPLOAD = "recording_capture_and_upload"
    RECORDING_NOTIFICATION = "recording_notification"
    TRANSCRIPT_PERSISTENCE = "transcript_persistence"
    POST_CALL_PII_PROCESSING = "post_call_pii_processing"
    SESSION_OBSERVABILITY = "session_observability"
    PRIMARY_AGENT_VOICE_PINNING = "primary_agent_voice_pinning"


type VoiceSupport = Annotated[VoiceFeatureSupport, BeforeValidator(_feature_support)]
type VoiceSampleRate = Annotated[StrictInt, Field(gt=0)]


class _CapabilityRead(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class STTNativeCapabilitiesRead(_CapabilityRead):
    """Recognition facts available for human inspection, not runtime policy."""

    streaming: VoiceSupport
    batch_recognize: VoiceSupport
    interim_results: VoiceSupport
    vad_events: VoiceSupport
    turn_detection: VoiceSupport
    word_timestamps: VoiceSupport
    speaker_labels: VoiceSupport
    language_detection: VoiceSupport
    custom_vocabulary: VoiceSupport
    punctuation: VoiceSupport
    profanity_filter: VoiceSupport
    aligned_transcript: VoiceSupport
    supported_encodings: tuple[VoiceNativeEncoding, ...]
    supported_sample_rates: tuple[VoiceSampleRate, ...]


class TTSNativeCapabilitiesRead(_CapabilityRead):
    """Synthesis facts intentionally exposed by the console API."""

    streaming: VoiceSupport
    batch_synthesize: VoiceSupport
    native_interruption: VoiceSupport
    aligned_transcript: VoiceSupport
    emotion_control: VoiceSupport
    speed_control: VoiceSupport
    voice_cloning: VoiceSupport
    context_continuity: VoiceSupport
    word_timestamps: VoiceSupport
    sample_rates: tuple[VoiceSampleRate, ...]
    languages_count: StrictInt = Field(ge=0)


class RealtimeNativeCapabilitiesRead(_CapabilityRead):
    """Realtime session facts without transport instances or SDK values."""

    full_duplex_audio: VoiceSupport
    input_transcription: VoiceSupport
    output_transcription: VoiceSupport
    native_turn_detection: VoiceSupport
    native_interruption: VoiceSupport
    tool_calling: VoiceSupport
    platform_message_speech: VoiceSupport
    session_update_mode: VoiceSessionUpdateMode
    voice_selection: VoiceSupport
    session_resumption: VoiceSupport
    context_compression: VoiceSupport
    input_sample_rates: tuple[VoiceSampleRate, ...]
    output_sample_rates: tuple[VoiceSampleRate, ...]


class _ProviderCapabilityRead(_CapabilityRead):
    provider_config_id: UUID
    ready: StrictBool


class STTProviderCapabilityRead(_ProviderCapabilityRead):
    """STT identity and recognition capabilities cannot be paired with TTS facts."""

    kind: Literal[VoiceKind.STT] = VoiceKind.STT
    provider: STTProviders
    native_capabilities: STTNativeCapabilitiesRead


class TTSProviderCapabilityRead(_ProviderCapabilityRead):
    """TTS identity and its synthesis projection."""

    kind: Literal[VoiceKind.TTS] = VoiceKind.TTS
    provider: TTSProviders
    native_capabilities: TTSNativeCapabilitiesRead


class RealtimeProviderCapabilityRead(_ProviderCapabilityRead):
    """Realtime identity and its session projection."""

    kind: Literal[VoiceKind.REALTIME] = VoiceKind.REALTIME
    provider: RealtimeProviders
    native_capabilities: RealtimeNativeCapabilitiesRead


type VoiceProviderCapabilityRead = Annotated[
    STTProviderCapabilityRead | TTSProviderCapabilityRead | RealtimeProviderCapabilityRead,
    Field(discriminator="kind"),
]
