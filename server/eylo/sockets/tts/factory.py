"""Adapter construction for the `tts` socket."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from eylo.common.contracts.provider_config import Capability, NotConfiguredError
from eylo.sockets.tts.adapters.amazon_polly_adapter import AmazonPollyTTSAdapter
from eylo.sockets.tts.adapters.cartesia_contract_adapter import (
    CartesiaContractAdapter,
)
from eylo.sockets.tts.adapters.deepgram_adapter import (
    DeepgramTTSAdapter,
    DeepgramTTSConfig,
)
from eylo.sockets.tts.adapters.elevenlabs_adapter import ElevenLabsTTSAdapter
from eylo.sockets.tts.adapters.groq_adapter import GroqTTSAdapter, GroqTTSConfig
from eylo.sockets.tts.adapters.hume_adapter import HumeTTSAdapter, HumeTTSConfig
from eylo.sockets.tts.adapters.murf_adapter import MurfTTSAdapter, MurfTTSConfig
from eylo.sockets.tts.adapters.openai_adapter import OpenAITTSAdapter, OpenAITTSConfig
from eylo.sockets.tts.adapters.rime_adapter import RimeTTSAdapter, RimeTTSConfig
from eylo.sockets.tts.adapters.sarvam_contract_adapter import SarvamContractAdapter
from eylo.sockets.tts.adapters.smallest_adapter import (
    SmallestTTSAdapter,
    SmallestTTSConfig,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider, normalize_tts_config

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS: dict[TTSProvider, frozenset[str]] = {
    TTSProvider.AMAZON_POLLY: frozenset(
        {
            "region",
            "model",
            "voice",
            "language",
            "access_key_id",
            "secret_access_key",
        }
    ),
    TTSProvider.CARTESIA: frozenset({"model", "voice", "api_key"}),
    TTSProvider.DEEPGRAM: frozenset({"model", "api_key"}),
    TTSProvider.ELEVENLABS: frozenset({"model", "voice", "api_key"}),
    TTSProvider.GROQ: frozenset({"model", "voice", "api_key"}),
    TTSProvider.HUME: frozenset({"model", "language", "api_key"}),
    TTSProvider.MURF: frozenset({"voice", "api_key"}),
    TTSProvider.OPENAI: frozenset({"model", "voice", "api_key"}),
    TTSProvider.RIME: frozenset({"model", "voice", "api_key"}),
    TTSProvider.SARVAM: frozenset({"model", "voice", "language", "api_key"}),
    TTSProvider.SMALLEST: frozenset({"model", "voice", "language", "api_key"}),
}


class TTSFactory:
    def __init__(
        self,
        tts_vendor: TTSProvider | str,
        tts_config: TTSConfig | dict[str, object] | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        if not isinstance(tts_vendor, str):
            raise ValueError("Unsupported TTS vendor.")
        try:
            self._tts_vendor = TTSProvider(tts_vendor.strip())
        except ValueError:
            raise ValueError("Unsupported TTS vendor.") from None
        self._typed_config = normalize_tts_config(
            tts_config, vendor=self._tts_vendor, api_key=api_key
        )
        self._tts_config = self._typed_config.to_adapter_config()
        _require_configuration(self._tts_vendor, self._tts_config)
        self._tts_service: TTSVendorAdapter | None = None

    def _contract_config(self) -> TTSConfig:
        """Translate the legacy flat carrier to adapter-owned option validation."""
        config = self._typed_config
        known = set(TTSConfig.model_fields)
        options = {}
        for key, value in self._tts_config.items():
            # `options` itself is not a vendor setting, and a field of the
            # contract belongs on the contract rather than duplicated beneath it.
            if key in known or key == "options" or value is None:
                continue
            options[key] = value
        return config.model_copy(update={"options": options})

    def create_tts(self) -> TTSVendorAdapter:
        if self._tts_vendor is TTSProvider.AMAZON_POLLY:
            return AmazonPollyTTSAdapter(self._contract_config())
        elif self._tts_vendor is TTSProvider.ELEVENLABS:
            return ElevenLabsTTSAdapter(self._contract_config())
        elif self._tts_vendor is TTSProvider.CARTESIA:
            return CartesiaContractAdapter(self._contract_config())
        elif self._tts_vendor is TTSProvider.SARVAM:
            return SarvamContractAdapter(self._contract_config())
        elif self._tts_vendor is TTSProvider.OPENAI:
            return OpenAITTSAdapter(
                config=OpenAITTSConfig.from_runtime(self._typed_config)
            )
        elif self._tts_vendor is TTSProvider.DEEPGRAM:
            return DeepgramTTSAdapter(
                config=DeepgramTTSConfig.from_runtime(self._typed_config)
            )
        elif self._tts_vendor is TTSProvider.GROQ:
            return GroqTTSAdapter(config=GroqTTSConfig.from_runtime(self._typed_config))
        elif self._tts_vendor is TTSProvider.RIME:
            return RimeTTSAdapter(config=RimeTTSConfig.from_runtime(self._typed_config))
        elif self._tts_vendor is TTSProvider.SMALLEST:
            return SmallestTTSAdapter(
                config=SmallestTTSConfig.from_runtime(self._typed_config)
            )
        elif self._tts_vendor is TTSProvider.HUME:
            return HumeTTSAdapter(config=HumeTTSConfig.from_runtime(self._typed_config))
        elif self._tts_vendor is TTSProvider.MURF:
            return MurfTTSAdapter(config=MurfTTSConfig.from_runtime(self._typed_config))
        else:
            raise ValueError(f"Unsupported TTS vendor: {self._tts_vendor}")

    def initialize_agent(self) -> TTSVendorAdapter:
        """Initialize the TTS service."""
        if not self._tts_service:
            self._tts_service = self.create_tts()
        return self._tts_service

    @property
    def service(self) -> TTSVendorAdapter:
        """Get the current TTS service, initializing if needed."""
        if self._tts_service:
            return self._tts_service
        return self.initialize_agent()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[TTSVendorAdapter, None]:
        """Yield the adapter, never its native handle; close it when use ends."""
        retry = self._typed_config.retry
        for attempt in range(retry.max_retries + 1):
            try:
                await self.service.connect()
                break
            except TTSConnectionFailed as error:
                if attempt >= retry.max_retries:
                    raise TTSConnectionFailed("TTS connection failed.") from error
                logger.warning(
                    "TTS connection failed vendor=%s retry=%s/%s error_type=%s",
                    self._tts_vendor.value,
                    attempt + 1,
                    retry.max_retries,
                    type(error).__name__,
                )
                await asyncio.sleep(retry.retry_interval_seconds)
        else:
            raise TTSConnectionFailed("TTS connection failed.")
        try:
            yield self.service
        finally:
            await self.service.disconnect()


def _require_configuration(vendor: TTSProvider, config: dict[str, object]) -> None:
    required = _REQUIRED_FIELDS.get(vendor)
    if required is None:
        return
    missing = {name for name in required if not _is_configured_text(config.get(name))}
    if vendor is TTSProvider.HUME and not any(
        _is_configured_text(config.get(name)) for name in ("voice", "voice_description")
    ):
        missing.add("voice")
    if missing:
        raise NotConfiguredError(
            capability=Capability.TTS,
            missing=sorted(missing),
            configure_via="/api/tts-configs",
        )


def _is_configured_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
