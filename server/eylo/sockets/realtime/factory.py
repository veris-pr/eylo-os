"""Realtime adapter selection with explicitly resolved realtime credentials."""

from __future__ import annotations

from pydantic import ValidationError

from eylo.common.config import settings
from eylo.common.contracts.provider_config import Capability, NotConfiguredError
from eylo.common.contracts.realtime_runtime import (
    RealtimeAWSCredentials,
    RealtimeApiKeyCredentials,
    ResolvedRealtimeConfig,
)
from eylo.sockets.realtime.base import RealtimeAdapter
from eylo.sockets.realtime.config import RealtimeSessionConfig, RealtimeVendor


class RealtimeFactory:
    @staticmethod
    def validate(vendor: RealtimeVendor, resolved: ResolvedRealtimeConfig) -> None:
        if not settings.ENABLE_REALTIME_VOICE:
            raise ValueError("Realtime voice is disabled (ENABLE_REALTIME_VOICE=false)")
        if (
            not isinstance(vendor, RealtimeVendor)
            or vendor.value != resolved.provider_id
        ):
            raise _not_configured("compatible_realtime_provider")
        if vendor is RealtimeVendor.AMAZON_NOVA_SONIC:
            _aws_credentials(resolved)
        else:
            _api_key(resolved)

    @staticmethod
    def create(
        config: RealtimeSessionConfig,
        resolved: ResolvedRealtimeConfig,
    ) -> RealtimeAdapter:
        config = RealtimeSessionConfig.model_validate(config)
        RealtimeFactory.validate(config.vendor, resolved)

        if config.vendor is RealtimeVendor.AMAZON_NOVA_SONIC:
            from eylo.sockets.realtime.vendors.amazon_nova_sonic import (
                AmazonNovaSonicAdapter,
            )

            credentials = _aws_credentials(resolved)
            region = resolved.region
            if not isinstance(region, str) or not region:
                raise _not_configured("region")
            return AmazonNovaSonicAdapter(
                config,
                region=region,
                access_key_id=credentials.access_key_id,
                secret_access_key=credentials.secret_access_key,
                session_token=credentials.session_token,
            )
        if config.vendor is RealtimeVendor.GEMINI_LIVE:
            from eylo.sockets.realtime.vendors.gemini_live import GeminiLiveAdapter

            return GeminiLiveAdapter(config, api_key=_api_key(resolved))
        if config.vendor is RealtimeVendor.OPENAI_REALTIME:
            from eylo.sockets.realtime.vendors.openai_realtime import (
                OpenAIRealtimeAdapter,
            )

            return OpenAIRealtimeAdapter(config, api_key=_api_key(resolved))
        raise AssertionError("validated realtime vendor was not handled")


def _api_key(resolved: ResolvedRealtimeConfig) -> str:
    if not isinstance(resolved.credentials, RealtimeApiKeyCredentials):
        raise _not_configured("credentials")
    try:
        return RealtimeApiKeyCredentials.model_validate(resolved.credentials).api_key
    except ValidationError:
        raise _not_configured("credentials") from None


def _aws_credentials(
    resolved: ResolvedRealtimeConfig,
) -> RealtimeAWSCredentials:
    if not isinstance(resolved.credentials, RealtimeAWSCredentials):
        raise _not_configured("credentials")
    try:
        return RealtimeAWSCredentials.model_validate(resolved.credentials)
    except ValidationError:
        raise _not_configured("credentials") from None


def _not_configured(missing: str) -> NotConfiguredError:
    return NotConfiguredError(
        capability=Capability.REALTIME,
        missing=[missing],
        configure_via="/api/realtime-configs",
    )
