"""Translate validated telephony domain config into the socket contract."""

from __future__ import annotations

from eylo.modules.telephony.provider_config_domain import (
    ExotelMaterial,
    PlivoMaterial,
    TelephonyProviderConfig,
    TwilioMaterial,
    VonageMaterial,
)
from eylo.sockets.telephony.base import TelephonyConfig
from eylo.sockets.telephony.config import (
    ExotelSettings,
    PlivoSettings,
    TelephonyVendorSettings,
    TwilioSettings,
    VonageSettings,
)


def build_telephony_runtime_config(
    config: TelephonyProviderConfig,
) -> TelephonyConfig:
    """Keep module/vendor enums distinct and parse the resolved socket payload."""
    material = config.material
    settings: TelephonyVendorSettings
    if isinstance(material, TwilioMaterial):
        settings = TwilioSettings(
            webhook_base_url=material.settings.webhook_base_url,
            account_sid=material.credentials.account_sid,
            auth_token=material.credentials.auth_token,
        )
    elif isinstance(material, PlivoMaterial):
        settings = PlivoSettings(
            webhook_base_url=material.settings.webhook_base_url,
            auth_id=material.credentials.auth_id,
            auth_token=material.credentials.auth_token,
        )
    elif isinstance(material, VonageMaterial):
        settings = VonageSettings(
            webhook_base_url=material.settings.webhook_base_url,
            application_id=material.settings.application_id,
            api_key=material.credentials.api_key,
            api_secret=material.credentials.api_secret,
            private_key=material.credentials.private_key,
            signature_secret=material.credentials.signature_secret,
        )
    elif isinstance(material, ExotelMaterial):
        settings = ExotelSettings(
            webhook_base_url=material.settings.webhook_base_url,
            application_id=material.settings.application_id,
            api_host=material.settings.api_host,
            api_key=material.credentials.api_key,
            api_token=material.credentials.api_token,
            account_sid=material.credentials.account_sid,
        )
    else:
        raise ValueError("Unsupported telephony provider.")
    return TelephonyConfig(settings=settings)
