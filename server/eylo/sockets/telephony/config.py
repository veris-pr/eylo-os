"""Execution-only carrier settings; credentials never belong in public output."""

from enum import Enum
from typing import ClassVar, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TelephonyProvider(str, Enum):
    """Carrier identities owned by the telephony socket boundary."""

    TWILIO = "twilio"
    PLIVO = "plivo"
    EXOTEL = "exotel"
    VONAGE = "vonage"


class TelephonySettings(BaseModel):
    """Immutable resolved settings, not an organization or persistence model."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_min_length=1,
        str_strip_whitespace=True,
        hide_input_in_errors=True,
    )

    webhook_base_url: str


class TwilioSettings(TelephonySettings):
    """Twilio account authentication for calls and numbers."""

    provider: ClassVar[TelephonyProvider] = TelephonyProvider.TWILIO
    account_sid: str = Field(repr=False)
    auth_token: str = Field(repr=False)


class PlivoSettings(TelephonySettings):
    """Plivo account authentication for calls and numbers."""

    provider: ClassVar[TelephonyProvider] = TelephonyProvider.PLIVO
    auth_id: str = Field(repr=False)
    auth_token: str = Field(repr=False)


class VonageSettings(TelephonySettings):
    """Vonage account and application authentication remain distinct."""

    provider: ClassVar[TelephonyProvider] = TelephonyProvider.VONAGE
    application_id: str
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    private_key: str = Field(repr=False)
    signature_secret: str = Field(repr=False)


class ExotelSettings(TelephonySettings):
    """Exotel account, application, and regional API authority."""

    provider: ClassVar[TelephonyProvider] = TelephonyProvider.EXOTEL
    application_id: str
    api_host: str
    api_key: str = Field(repr=False)
    api_token: str = Field(repr=False)
    account_sid: str = Field(repr=False)


TelephonyVendorSettings: TypeAlias = (
    TwilioSettings | PlivoSettings | VonageSettings | ExotelSettings
)
SettingsT = TypeVar("SettingsT", bound=TelephonySettings)
