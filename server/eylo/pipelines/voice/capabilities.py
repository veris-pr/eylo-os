"""Compose provider-native and Eylo-owned Voice Config capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.modules.voice.schemas.api import (
    VoiceConfig,
    VoiceConfigCompatibilityRead,
    VoicePlatformFeatureRead,
    VoiceProviderCapabilityRead,
)
from eylo.modules.voice.services.voice_configs import VoiceConfigService
from eylo.modules.voice_configs.catalog import VoiceKind
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
from eylo.sockets.realtime.factory import RealtimeFactory
from eylo.sockets.stt.factory import STTFactory
from eylo.sockets.tts.factory import TTSFactory

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
            adapter = STTFactory(
                organization_id=organization_id,
                session_id="voice-config-capability-inspection",
                stt_vendor=stored.provider,
                stt_config=build_stt_runtime_config(None, stt),
            ).service
            capabilities = adapter.capabilities.model_dump(mode="json")
        elif kind is VoiceKind.TTS:
            tts = ResolvedTTS.from_voice_config(
                provider_config_id=stored.id,
                provider_config_revision=stored.revision,
                organization_id=organization_id,
                config=validated,
            )
            adapter = TTSFactory(
                tts_vendor=stored.provider,
                tts_config=build_tts_runtime_config(tts),
            ).service
            capabilities = adapter.capabilities.model_dump(mode="json")
        else:
            capabilities = self._realtime_capabilities(
                organization_id=organization_id,
                provider_config_id=stored.id,
                provider_config_revision=stored.revision,
                provider=stored.provider,
                config=stored.config,
                secrets=stored.secrets,
            )

        return VoiceProviderCapabilityRead(
            kind=kind.value,
            provider_config_id=stored.id,
            provider=stored.provider,
            ready=stored.ready,
            native_capabilities=capabilities,
        )

    @staticmethod
    def _realtime_capabilities(
        *,
        organization_id: UUID,
        provider_config_id: UUID,
        provider_config_revision: int,
        provider: str,
        config: Mapping[str, object],
        secrets: Mapping[str, str],
    ) -> dict[str, object]:
        validated = VoiceProviderConfig.from_storage(
            provider=provider, kind=VoiceKind.REALTIME, config=config, secrets=secrets
        )
        resolved = ResolvedRealtime.from_voice_config(
            provider_config_id=provider_config_id,
            provider_config_revision=provider_config_revision,
            organization_id=organization_id,
            config=validated,
            configured=True,
            verified=False,
            ready=False,
            granted=True,
        )
        session_config = build_realtime_session_config(
            resolved,
            organization_id=organization_id,
            conversation_id=UUID(int=0),
            agent_id=UUID(int=0),
            session_id="voice-config-capability-inspection",
        )
        adapter = RealtimeFactory.create(session_config, resolved)
        return adapter.capabilities.model_dump(mode="json")


def _platform_features(config: VoiceConfig) -> list[VoicePlatformFeatureRead]:
    silence_enabled = (
        config.silence.reminder_max_count > 0
        or config.silence.end_call_after_silence_ms > 0
    )
    return [
        _feature(
            "interruption_handling",
            "Interruption handling",
            True,
            "Eylo coordinates user speech, Agent playback, and interrupted turns.",
        ),
        _feature(
            "silence_policy",
            "Silence policy",
            silence_enabled,
            "Eylo owns reminders and silence-based call termination.",
        ),
        _feature(
            "duration_limit",
            "Duration limit",
            config.conversation_control.max_duration_seconds > 0,
            "Eylo ends the session when its configured duration is reached.",
        ),
        _feature(
            "recording_capture_and_upload",
            "Recording capture and upload",
            config.artifacts.audio_storage_enabled,
            "Eylo records the primary flow and uploads through the selected storage config.",
        ),
        _feature(
            "recording_notification",
            "Recording notification",
            config.compliance.recording_consent_required,
            "Eylo attempts the notification without making it a call gate.",
        ),
        _feature(
            "transcript_persistence",
            "Transcript persistence",
            config.artifacts.transcript_storage_enabled,
            "Eylo persists the canonical post-call transcript.",
        ),
        _feature(
            "post_call_pii_processing",
            "Post-call PII processing",
            config.compliance.redact_pii_in_transcripts,
            "Eylo builds redacted canonical storage after the live flow.",
        ),
        _feature(
            "session_observability",
            "Session observability",
            (
                config.observability.metrics_enabled
                or config.observability.vendor_latency_tracking_enabled
            ),
            "Eylo owns session metrics and provider latency tracking.",
        ),
        _feature(
            "primary_agent_voice_pinning",
            "Primary Agent Voice Config pinning",
            True,
            "Eylo keeps the primary Agent's published Voice Config for all handoffs.",
        ),
    ]


def _feature(
    key: str,
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
