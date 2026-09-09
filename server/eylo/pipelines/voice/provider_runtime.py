"""Resolve pinned voice providers and compose their typed runtime inputs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.speech_runtime import SpeechTransportFormat
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.voice.schemas.api import VoiceConfig
from eylo.modules.voice_configs.catalog import STTProviders, TTSProviders
from eylo.modules.voice_configs.domain import (
    InvalidVoiceConfig,
    ResolvedRealtime,
    ResolvedSTT,
    ResolvedTTS,
)
from eylo.modules.voice_configs.wiring import build_voice_config_resolver
from eylo.sockets.realtime.config import RealtimeSessionConfig, RealtimeVendor


def build_realtime_session_config(
    resolved: ResolvedRealtime,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    session_id: str,
    voice_session_row_id: UUID | None = None,
) -> RealtimeSessionConfig:
    """Compose one org's validated provider material with current session facts."""
    resolved = ResolvedRealtime.model_validate(resolved)
    if resolved.organization_id != organization_id:
        raise InvalidVoiceConfig(
            "Realtime session organization does not match provider."
        )
    inference = resolved.config
    return RealtimeSessionConfig(
        organization_id=organization_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        session_id=session_id,
        voice_session_row_id=voice_session_row_id,
        vendor=RealtimeVendor(resolved.provider.value),
        model=inference.model,
        voice=inference.voice,
        temperature=inference.temperature,
        top_p=inference.top_p,
        max_tokens=inference.max_tokens,
        input_transcription_model=inference.input_transcription_model,
        vad_threshold=inference.vad_threshold,
        vad_silence_ms=inference.vad_silence_ms,
        endpointing_sensitivity=inference.endpointing_sensitivity,
        is_context_compression_enabled=inference.is_context_compression_enabled,
        context_compression_trigger_tokens=inference.context_compression_trigger_tokens,
    )


async def resolve_decomposed_voice_runtime(
    organization_id: UUID,
    voice_config: VoiceConfig,
    *,
    db: AsyncSession | None = None,
) -> tuple[ResolvedSTT, ResolvedTTS]:
    """Resolve pinned provider material; never substitute a current revision."""
    if (
        voice_config.stt_provider_config_id is None
        or voice_config.stt_provider_config_revision is None
    ):
        raise _not_configured(Capability.STT, "/api/stt-configs")
    if (
        voice_config.tts_provider_config_id is None
        or voice_config.tts_provider_config_revision is None
    ):
        raise _not_configured(Capability.TTS, "/api/tts-configs")

    resolver = build_voice_config_resolver(db)
    stt = await resolver.resolve_stt_pinned(
        organization_id,
        provider_config_id=voice_config.stt_provider_config_id,
        revision=voice_config.stt_provider_config_revision,
    )
    tts = await resolver.resolve_tts_pinned(
        organization_id,
        provider_config_id=voice_config.tts_provider_config_id,
        revision=voice_config.tts_provider_config_revision,
    )
    return stt, tts


async def resolve_realtime_voice_runtime(
    organization_id: UUID,
    voice_config: VoiceConfig,
    *,
    db: AsyncSession | None = None,
) -> ResolvedRealtime:
    """Resolve the exact realtime provider revision pinned at Agent publish."""
    if (
        voice_config.realtime_provider_config_id is None
        or voice_config.realtime_provider_config_revision is None
    ):
        raise _not_configured(Capability.REALTIME, "/api/realtime-configs")
    return await build_voice_config_resolver(db).resolve_realtime_pinned(
        organization_id,
        provider_config_id=voice_config.realtime_provider_config_id,
        revision=voice_config.realtime_provider_config_revision,
    )


class DecomposedVoiceRuntimeIdentity(BaseModel):
    """Provider identity actually used by one decomposed voice session."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    stt_vendor: STTProviders
    stt_model: str | None
    tts_vendor: TTSProviders
    tts_model: str | None
    tts_voice: str | None

    @classmethod
    def from_resolved(
        cls,
        stt: ResolvedSTT,
        tts: ResolvedTTS,
    ) -> DecomposedVoiceRuntimeIdentity:
        stt = ResolvedSTT.model_validate(stt)
        tts = ResolvedTTS.model_validate(tts)
        if stt.organization_id != tts.organization_id:
            raise InvalidVoiceConfig(
                "Speech providers belong to different organizations."
            )
        return cls(
            stt_vendor=stt.provider,
            stt_model=stt.config.model or stt.config.language_model_name,
            tts_vendor=tts.provider,
            tts_model=tts.config.model,
            tts_voice=tts.config.voice,
        )


def build_stt_runtime_config(
    voice_config: VoiceConfig | None,
    stt: ResolvedSTT,
    *,
    transport: SpeechTransportFormat | None = None,
) -> dict[str, object]:
    """Serialize checked material at the current STT factory mapping boundary.

    Verification has no conversation speech policy. Transport contributes only
    validated media facts; it cannot override the pinned model or credentials.
    """
    stt = ResolvedSTT.model_validate(stt)
    config: dict[str, object] = {}
    start_plan = voice_config.start_speaking_plan if voice_config is not None else None
    if start_plan is not None:
        config["wait_ms"] = start_plan.wait_ms
    stop_plan = voice_config.stop_speaking_plan if voice_config is not None else None
    if stop_plan is not None:
        config["interruption_type"] = stop_plan.interruption_type.value

    config.update(stt.config.model_dump(mode="json", exclude_unset=True))
    config.update(stt.credentials.for_adapter())
    if transport is not None:
        media = SpeechTransportFormat.model_validate(transport)
        config.update(sample_rate=media.sample_rate, encoding=media.encoding.value)
    config["vendor"] = stt.provider.value
    return config


def build_tts_runtime_config(
    tts: ResolvedTTS,
    *,
    transport: SpeechTransportFormat | None = None,
) -> dict[str, object]:
    """Serialize checked synthesis material at the current factory boundary."""
    tts = ResolvedTTS.model_validate(tts)
    config: dict[str, object] = tts.config.model_dump(mode="json", exclude_unset=True)
    config.update(tts.credentials.for_adapter())
    if transport is not None:
        media = SpeechTransportFormat.model_validate(transport)
        config.update(sample_rate=media.sample_rate, encoding=media.encoding.value)
    config["vendor"] = tts.provider.value
    return config


def _not_configured(
    capability: Capability,
    configure_via: str,
) -> NotConfiguredError:
    return NotConfiguredError(
        capability=capability,
        missing=["provider_config", "provider_config_revision"],
        configure_via=configure_via,
    )
