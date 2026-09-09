"""Compose provider-native and Eylo-owned Voice Config capabilities."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.voice.schemas.api import (
    VoiceConfig,
    VoiceConfigCompatibilityRead,
    VoicePlatformFeatureRead,
    VoiceProviderCapabilityRead,
)
from eylo.modules.voice.schemas.capabilities import (
    RealtimeNativeCapabilitiesRead,
    RealtimeProviderCapabilityRead,
    STTNativeCapabilitiesRead,
    STTProviderCapabilityRead,
    TTSNativeCapabilitiesRead,
    TTSProviderCapabilityRead,
    VoiceFeatureSupport,
    VoiceNativeEncoding,
    VoicePlatformFeature,
    VoiceSessionUpdateMode,
)
from eylo.modules.voice.services.voice_configs import VoiceConfigService
from eylo.modules.voice_configs.catalog import (
    RealtimeProviders,
    STTProviders,
    TTSProviders,
    VoiceKind,
)
from eylo.modules.voice_configs.domain import (
    ResolvedRealtime,
    ResolvedSTT,
    ResolvedTTS,
    VoiceProviderConfig,
)
from eylo.modules.voice_configs.wiring import (
    build_voice_config_service as build_provider_voice_config_service,
)
from eylo.pipelines.voice.provider_runtime import (
    build_realtime_session_config,
    build_stt_runtime_config,
    build_tts_runtime_config,
)
from eylo.sockets.realtime.base import RealtimeCapabilities
from eylo.sockets.realtime.factory import RealtimeFactory
from eylo.sockets.stt.factory import STTFactory
from eylo.sockets.stt.schemas import STTCapabilities
from eylo.sockets.tts.factory import TTSFactory
from eylo.sockets.tts.schemas import TTSCapabilities

_INSPECTION_SESSION_ID = "voice-config-capability-inspection"

_GUIDANCE = (
    "Eylo platform features remain available when a selected provider does not "
    "offer the same behavior natively. Native capabilities describe only the "
    "selected adapter path; provider-specific settings stay in that provider's "
    "configuration."
)


class VoiceCapabilityService:
    """Build a read model without making a vendor network request."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._voice_configs = VoiceConfigService(db)
        self._provider_configs = build_provider_voice_config_service(db)

    async def get(
        self,
        *,
        organization_id: UUID,
        voice_config_id: UUID,
    ) -> VoiceConfigCompatibilityRead:
        voice_config = await self._voice_configs.get(
            organization_id=organization_id,
            voice_config_id=voice_config_id,
        )
        providers: list[VoiceProviderCapabilityRead] = []
        selected = (
            (VoiceKind.STT, voice_config.config.stt_provider_config_id),
            (VoiceKind.TTS, voice_config.config.tts_provider_config_id),
            (VoiceKind.REALTIME, voice_config.config.realtime_provider_config_id),
        )
        for kind, config_id in selected:
            if config_id is None:
                continue
            providers.append(
                await self._provider_capabilities(
                    organization_id=organization_id,
                    kind=kind,
                    config_id=config_id,
                )
            )

        return VoiceConfigCompatibilityRead(
            voice_config_id=voice_config.id,
            voice_config_revision=voice_config.revision,
            platform_features=_platform_features(voice_config.config),
            selected_providers=providers,
            guidance=_GUIDANCE,
        )

    async def _provider_capabilities(
        self,
        *,
        organization_id: UUID,
        kind: VoiceKind,
        config_id: UUID,
    ) -> VoiceProviderCapabilityRead:
        stored = await self._provider_configs.get(
            organization_id=organization_id,
            config_id=config_id,
            kind=kind,
        )
        validated = VoiceProviderConfig.from_storage(
            provider=stored.provider,
            kind=kind,
            config=stored.config,
            secrets=stored.secrets,
        )

        if kind is VoiceKind.STT:
            stt = ResolvedSTT.from_voice_config(
                provider_config_id=stored.id,
                provider_config_revision=stored.revision,
                organization_id=organization_id,
                config=validated,
            )
            stt_adapter = STTFactory(
                organization_id=organization_id,
                session_id=_INSPECTION_SESSION_ID,
                stt_vendor=stored.provider,
                stt_config=build_stt_runtime_config(None, stt),
            ).service
            return STTProviderCapabilityRead(
                provider_config_id=stored.id,
                provider=STTProviders(stored.provider),
                ready=stored.ready,
                native_capabilities=_stt_capabilities(stt_adapter.capabilities),
            )
        elif kind is VoiceKind.TTS:
            tts = ResolvedTTS.from_voice_config(
                provider_config_id=stored.id,
                provider_config_revision=stored.revision,
                organization_id=organization_id,
                config=validated,
            )
            tts_adapter = TTSFactory(
                tts_vendor=stored.provider,
                tts_config=build_tts_runtime_config(tts),
            ).service
            return TTSProviderCapabilityRead(
                provider_config_id=stored.id,
                provider=TTSProviders(stored.provider),
                ready=stored.ready,
                native_capabilities=_tts_capabilities(tts_adapter.capabilities),
            )
        else:
            realtime = ResolvedRealtime.from_voice_config(
                organization_id=organization_id,
                provider_config_id=stored.id,
                provider_config_revision=stored.revision,
                config=validated,
                configured=True,
                verified=False,
                ready=False,
                granted=True,
            )
            return RealtimeProviderCapabilityRead(
                provider_config_id=stored.id,
                provider=RealtimeProviders(stored.provider),
                ready=stored.ready,
                native_capabilities=self._realtime_capabilities(realtime),
            )

    @staticmethod
    def _realtime_capabilities(
        resolved: ResolvedRealtime,
    ) -> RealtimeNativeCapabilitiesRead:
        session_config = build_realtime_session_config(
            resolved,
            organization_id=resolved.organization_id,
            conversation_id=UUID(int=0),
            agent_id=UUID(int=0),
            session_id=_INSPECTION_SESSION_ID,
        )
        adapter = RealtimeFactory.create(session_config, resolved)
        return _realtime_capabilities(adapter.capabilities)


def _stt_capabilities(native: STTCapabilities) -> STTNativeCapabilitiesRead:
    """Project only public recognition fields across the socket/module boundary."""
    return STTNativeCapabilitiesRead(
        streaming=VoiceFeatureSupport(native.streaming.value),
        batch_recognize=VoiceFeatureSupport(native.batch_recognize.value),
        interim_results=VoiceFeatureSupport(native.interim_results.value),
        vad_events=VoiceFeatureSupport(native.vad_events.value),
        turn_detection=VoiceFeatureSupport(native.turn_detection.value),
        word_timestamps=VoiceFeatureSupport(native.word_timestamps.value),
        speaker_labels=VoiceFeatureSupport(native.speaker_labels.value),
        language_detection=VoiceFeatureSupport(native.language_detection.value),
        custom_vocabulary=VoiceFeatureSupport(native.custom_vocabulary.value),
        punctuation=VoiceFeatureSupport(native.punctuation.value),
        profanity_filter=VoiceFeatureSupport(native.profanity_filter.value),
        aligned_transcript=VoiceFeatureSupport(native.aligned_transcript.value),
        supported_encodings=tuple(
            VoiceNativeEncoding(item.value) for item in native.supported_encodings
        ),
        supported_sample_rates=native.supported_sample_rates,
    )


def _tts_capabilities(native: TTSCapabilities) -> TTSNativeCapabilitiesRead:
    """Synthesis capabilities are observations, not platform policy switches."""
    return TTSNativeCapabilitiesRead(
        streaming=VoiceFeatureSupport(native.streaming),
        batch_synthesize=VoiceFeatureSupport(native.batch_synthesize),
        native_interruption=VoiceFeatureSupport(native.native_interruption),
        aligned_transcript=VoiceFeatureSupport(native.aligned_transcript),
        emotion_control=VoiceFeatureSupport(native.emotion_control),
        speed_control=VoiceFeatureSupport(native.speed_control),
        voice_cloning=VoiceFeatureSupport(native.voice_cloning),
        context_continuity=VoiceFeatureSupport(native.context_continuity),
        word_timestamps=VoiceFeatureSupport(native.word_timestamps),
        sample_rates=native.sample_rates,
        languages_count=native.languages_count,
    )


def _realtime_capabilities(
    native: RealtimeCapabilities,
) -> RealtimeNativeCapabilitiesRead:
    """Keep session update modes and audio facts explicit in the API projection."""
    return RealtimeNativeCapabilitiesRead(
        full_duplex_audio=VoiceFeatureSupport(native.full_duplex_audio.value),
        input_transcription=VoiceFeatureSupport(native.input_transcription.value),
        output_transcription=VoiceFeatureSupport(native.output_transcription.value),
        native_turn_detection=VoiceFeatureSupport(native.native_turn_detection.value),
        native_interruption=VoiceFeatureSupport(native.native_interruption.value),
        tool_calling=VoiceFeatureSupport(native.tool_calling.value),
        platform_message_speech=VoiceFeatureSupport(native.platform_message_speech.value),
        session_update_mode=VoiceSessionUpdateMode(native.session_update_mode.value),
        voice_selection=VoiceFeatureSupport(native.voice_selection.value),
        session_resumption=VoiceFeatureSupport(native.session_resumption.value),
        context_compression=VoiceFeatureSupport(native.context_compression.value),
        input_sample_rates=native.input_sample_rates,
        output_sample_rates=native.output_sample_rates,
    )


def _platform_features(config: VoiceConfig) -> list[VoicePlatformFeatureRead]:
    silence_enabled = (
        config.silence.reminder_max_count > 0
        or config.silence.end_call_after_silence_ms > 0
    )
    return [
        _feature(
            VoicePlatformFeature.INTERRUPTION_HANDLING,
            "Interruption handling",
            True,
            "Eylo coordinates user speech, Agent playback, and interrupted turns.",
        ),
        _feature(
            VoicePlatformFeature.SILENCE_POLICY,
            "Silence policy",
            silence_enabled,
            "Eylo owns reminders and silence-based call termination.",
        ),
        _feature(
            VoicePlatformFeature.DURATION_LIMIT,
            "Duration limit",
            config.conversation_control.max_duration_seconds > 0,
            "Eylo ends the session when its configured duration is reached.",
        ),
        _feature(
            VoicePlatformFeature.RECORDING_CAPTURE_AND_UPLOAD,
            "Recording capture and upload",
            config.artifacts.audio_storage_enabled,
            "Eylo records the primary flow and uploads through the selected storage config.",
        ),
        _feature(
            VoicePlatformFeature.RECORDING_NOTIFICATION,
            "Recording notification",
            config.compliance.recording_consent_required,
            "Eylo attempts the notification without making it a call gate.",
        ),
        _feature(
            VoicePlatformFeature.TRANSCRIPT_PERSISTENCE,
            "Transcript persistence",
            config.artifacts.transcript_storage_enabled,
            "Eylo persists the canonical post-call transcript.",
        ),
        _feature(
            VoicePlatformFeature.POST_CALL_PII_PROCESSING,
            "Post-call PII processing",
            config.compliance.redact_pii_in_transcripts,
            "Eylo builds redacted canonical storage after the live flow.",
        ),
        _feature(
            VoicePlatformFeature.SESSION_OBSERVABILITY,
            "Session observability",
            (
                config.observability.metrics_enabled
                or config.observability.vendor_latency_tracking_enabled
            ),
            "Eylo owns session metrics and provider latency tracking.",
        ),
        _feature(
            VoicePlatformFeature.PRIMARY_AGENT_VOICE_PINNING,
            "Primary Agent Voice Config pinning",
            True,
            "Eylo keeps the primary Agent's published Voice Config for all handoffs.",
        ),
    ]


def _feature(
    key: VoicePlatformFeature,
    label: str,
    enabled: bool,
    description: str,
) -> VoicePlatformFeatureRead:
    return VoicePlatformFeatureRead(
        key=key,
        label=label,
        enabled=enabled,
        description=description,
    )
