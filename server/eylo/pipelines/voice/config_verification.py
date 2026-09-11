"""Bounded, revision-safe STT, TTS and realtime provider verification."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from eylo.common.database import start_transaction
from eylo.modules.voice_configs.catalog import (
    RealtimeProviders,
    VoiceKind,
)
from eylo.modules.voice_configs.domain import (
    ResolvedRealtime,
    ResolvedSTT,
    ResolvedTTS,
    VoiceProviderConfig,
)
from eylo.modules.voice_configs.verification import (
    VoiceProviderVerification,
    VoiceProviderVerifier,
    VoiceVerificationError,
    VoiceVerificationResult,
)
from eylo.modules.voice_configs.wiring import build_voice_config_service
from eylo.pipelines.voice.provider_runtime import (
    build_realtime_session_config,
    build_stt_runtime_config,
    build_tts_runtime_config,
)
from eylo.sockets.realtime.factory import RealtimeFactory
from eylo.sockets.stt.factory import STTFactory
from eylo.sockets.tts.factory import TTSFactory

_VERIFICATION_TIMEOUT_SECONDS = 20.0
logger = logging.getLogger(__name__)


class VoiceRuntimeVerifier:
    """Construct and connect the same socket adapter used by live voice."""

    async def verify(
        self,
        config: VoiceProviderConfig,
    ) -> VoiceProviderVerification:
        try:
            async with asyncio.timeout(_VERIFICATION_TIMEOUT_SECONDS):
                if config.kind is VoiceKind.STT:
                    await self._verify_stt(config)
                elif config.kind is VoiceKind.TTS:
                    await self._verify_tts(config)
                else:
                    await self._verify_realtime(config)
        except Exception as error:
            logger.warning(
                "Voice provider verification failed kind=%s provider=%s error_type=%s",
                config.kind.value,
                config.provider.value,
                type(error).__name__,
            )
            raise VoiceVerificationError(
                "Voice provider verification failed."
            ) from None
        return VoiceProviderVerification(
            provider=config.provider,
            kind=config.kind,
        )

    @staticmethod
    async def _verify_stt(config: VoiceProviderConfig) -> None:
        resolved = ResolvedSTT.from_voice_config(
            provider_config_id=UUID(int=0),
            provider_config_revision=1,
            organization_id=UUID(int=0),
            config=config,
        )
        factory = STTFactory(
            organization_id=UUID(int=0),
            session_id="provider-config-verification",
            stt_vendor=config.provider.value,
            stt_config=build_stt_runtime_config(None, resolved),
        )
        async with factory.connection():
            if not factory.is_connected:
                raise VoiceVerificationError("Voice provider verification failed.")

    @staticmethod
    async def _verify_tts(config: VoiceProviderConfig) -> None:
        resolved = ResolvedTTS.from_voice_config(
            provider_config_id=UUID(int=0),
            provider_config_revision=1,
            organization_id=UUID(int=0),
            config=config,
        )
        factory = TTSFactory(
            tts_vendor=config.provider.value,
            tts_config=build_tts_runtime_config(resolved),
        )
        async with factory.connection():
            if not factory.service.is_connected:
                raise VoiceVerificationError("Voice provider verification failed.")

    @staticmethod
    async def _verify_realtime(config: VoiceProviderConfig) -> None:
        if not isinstance(config.provider, RealtimeProviders):
            raise VoiceVerificationError("Voice provider verification failed.")
        resolved = ResolvedRealtime.from_voice_config(
            provider_config_id=UUID(int=0),
            provider_config_revision=1,
            organization_id=UUID(int=0),
            config=config,
            configured=True,
            verified=False,
            ready=False,
            granted=True,
        )
        session_config = build_realtime_session_config(
            resolved,
            organization_id=UUID(int=0),
            conversation_id=UUID(int=0),
            agent_id=UUID(int=0),
            session_id="provider-config-verification",
        )
        adapter = RealtimeFactory.create(session_config, resolved)
        try:
            await adapter.connect()
            await adapter.verify_ready()
        finally:
            await adapter.disconnect()


class VoiceConfigVerificationUseCase:
    """Keep the external check outside DB transactions, then CAS the revision."""

    def __init__(self, verifier: VoiceProviderVerifier) -> None:
        self._verifier = verifier

    async def verify(
        self,
        *,
        organization_id: UUID,
        config_id: UUID,
        kind: VoiceKind,
    ) -> VoiceVerificationResult:
        async with start_transaction():
            stored = await build_voice_config_service().get(
                organization_id=organization_id,
                config_id=config_id,
                kind=kind,
            )
            provider_config = VoiceProviderConfig.from_storage(
                provider=stored.provider,
                kind=kind,
                config=stored.config,
                secrets=stored.secrets,
            )
            expected_revision = stored.revision

        result = await self._verifier.verify(provider_config)

        async with start_transaction():
            verified = await build_voice_config_service().mark_verified(
                organization_id=organization_id,
                config_id=config_id,
                expected_revision=expected_revision,
            )
        assert verified.verified_at is not None
        return VoiceVerificationResult(
            provider=result.provider,
            kind=result.kind,
            revision=verified.revision,
            verified_at=verified.verified_at,
        )
