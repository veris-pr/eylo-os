"""Translate validated telephony domain config into the socket contract."""

from __future__ import annotations

from eylo.modules.telephony.provider_config_domain import TelephonyProviderConfig
from eylo.sockets.telephony.base import TelephonyConfig
from eylo.sockets.telephony.config import (
    ExotelSettings,
    PlivoSettings,
    TelephonyProvider,
    TelephonyVendorSettings,
    TwilioSettings,
    VonageSettings,
)


def build_telephony_runtime_config(
    config: TelephonyProviderConfig,
) -> TelephonyConfig:
    """Keep module/vendor enums distinct and parse the resolved socket payload."""
    provider = TelephonyProvider(config.provider)
    values = {**config.config, **config.secrets}
    settings: TelephonyVendorSettings
    if provider is TelephonyProvider.TWILIO:
        settings = TwilioSettings.model_validate(values)
    elif provider is TelephonyProvider.PLIVO:
        settings = PlivoSettings.model_validate(values)
    elif provider is TelephonyProvider.VONAGE:
        settings = VonageSettings.model_validate(values)
    elif provider is TelephonyProvider.EXOTEL:
        settings = ExotelSettings.model_validate(values)
    else:
        raise ValueError("Unsupported telephony provider.")
    return TelephonyConfig(settings=settings)
