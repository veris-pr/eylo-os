"""Read-only carrier credential verification through explicit settings."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping

import httpx
from pydantic import BaseModel, ConfigDict, Field

from eylo.sockets.telephony.base import BaseTelephonyService, TelephonyConfig
from eylo.sockets.telephony.config import (
    ExotelSettings,
    PlivoSettings,
    TelephonyProvider,
    TelephonyVendorSettings,
    TwilioSettings,
    VonageSettings,
)
from eylo.sockets.telephony.factory import TelephonyFactory
from eylo.sockets.telephony.twilio.endpoint import twilio_account_url


class TelephonyCredentialProbeError(Exception):
    """Raised when carrier construction or read-only authentication fails."""


class TelephonyCredentialProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    provider: TelephonyProvider
    account_reference: str = Field(min_length=1, repr=False, exclude=True)


class TelephonyCredentialProbe:
    """Construct the live carrier service, then execute one read-only API call."""

    def __init__(
        self,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._client_factory = client_factory

    async def verify(
        self,
        *,
        config: TelephonyConfig,
        timeout_seconds: float,
    ) -> TelephonyCredentialProbeResult:
        service = TelephonyFactory(config).service
        _require_constructed_provider(service, config.provider)
        request = _request(config.settings)
        try:
            async with self._client_factory(
                timeout=timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.send(request)
            response.raise_for_status()
            payload = response.json()
            account_reference = _account_reference(config.settings, payload)
        except Exception as error:
            raise TelephonyCredentialProbeError(
                "Telephony credential verification failed."
            ) from error
        return TelephonyCredentialProbeResult(
            provider=config.provider,
            account_reference=account_reference,
        )


def _request(settings: TelephonyVendorSettings) -> httpx.Request:
    if isinstance(settings, TwilioSettings):
        account_sid = settings.account_sid
        return httpx.Request(
            "GET",
            f"{twilio_account_url(account_sid)}.json",
            headers={"Authorization": _basic(account_sid, settings.auth_token)},
        )
    if isinstance(settings, PlivoSettings):
        auth_id = settings.auth_id
        return httpx.Request(
            "GET",
            f"https://api.plivo.com/v1/Account/{auth_id}/",
            headers={"Authorization": _basic(auth_id, settings.auth_token)},
        )
    if isinstance(settings, VonageSettings):
        return httpx.Request(
            "GET",
            "https://rest.nexmo.com/account/get-balance",
            headers={
                "Authorization": _basic(
                    settings.api_key,
                    settings.api_secret,
                )
            },
        )
    if isinstance(settings, ExotelSettings):
        account_sid = settings.account_sid
        api_host = settings.api_host
        return httpx.Request(
            "GET",
            f"https://{api_host}/v1/Accounts/{account_sid}/Calls.json",
            params={"PageSize": 1},
            headers={
                "Authorization": _basic(
                    settings.api_key,
                    settings.api_token,
                )
            },
        )
    raise TelephonyCredentialProbeError("Unsupported telephony provider.")


def _account_reference(
    settings: TelephonyVendorSettings,
    payload: object,
) -> str:
    if not isinstance(payload, Mapping):
        raise TelephonyCredentialProbeError("Carrier returned an invalid response.")
    if isinstance(settings, TwilioSettings):
        expected = settings.account_sid
        if payload.get("sid") != expected:
            raise TelephonyCredentialProbeError("Twilio account identity mismatch.")
        return expected
    if isinstance(settings, PlivoSettings):
        expected = settings.auth_id
        if payload.get("auth_id") != expected:
            raise TelephonyCredentialProbeError("Plivo account identity mismatch.")
        return expected
    if isinstance(settings, VonageSettings):
        value = payload.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TelephonyCredentialProbeError("Vonage account response is invalid.")
        return settings.api_key
    if isinstance(settings, ExotelSettings):
        if not ({"Calls", "Metadata"} & set(payload)):
            raise TelephonyCredentialProbeError("Exotel account response is invalid.")
        return settings.account_sid
    raise TelephonyCredentialProbeError("Unsupported telephony provider.")


def _require_constructed_provider(
    service: BaseTelephonyService, provider: TelephonyProvider
) -> None:
    if service.provider is not provider:
        raise TelephonyCredentialProbeError("Carrier adapter construction failed.")
    if provider is TelephonyProvider.PLIVO:
        from eylo.sockets.telephony.plivo.service import PlivoService

        if not isinstance(service, PlivoService) or service.client is None:
            raise TelephonyCredentialProbeError("Carrier client construction failed.")
    if provider is TelephonyProvider.VONAGE:
        from eylo.sockets.telephony.vonage.service import VonageService

        if not isinstance(service, VonageService) or service.client is None:
            raise TelephonyCredentialProbeError("Carrier client construction failed.")


def _basic(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"
