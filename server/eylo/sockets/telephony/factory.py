"""Construct the explicitly selected carrier service from resolved settings."""

from eylo.sockets.telephony.base import BaseTelephonyService, TelephonyConfig
from eylo.sockets.telephony.config import TelephonyProvider


class TelephonyFactory:
    """Own one lazily constructed carrier service; no environment fallback."""

    def __init__(self, config: TelephonyConfig) -> None:
        self._config = config
        self._telephony_service: BaseTelephonyService | None = None

    def create_telephony_service(self) -> BaseTelephonyService:
        if self.provider is TelephonyProvider.TWILIO:
            from eylo.sockets.telephony.twilio.service import TwilioService

            return TwilioService(config=self._config)
        if self.provider is TelephonyProvider.PLIVO:
            from eylo.sockets.telephony.plivo.service import PlivoService

            return PlivoService(config=self._config)
        if self.provider is TelephonyProvider.VONAGE:
            from eylo.sockets.telephony.vonage.service import VonageService

            return VonageService(config=self._config)
        if self.provider is TelephonyProvider.EXOTEL:
            from eylo.sockets.telephony.exotel.service import ExotelService

            return ExotelService(config=self._config)
        raise ValueError("Unsupported telephony provider.")

    def initialize_service(self) -> BaseTelephonyService:
        if self._telephony_service is None:
            self._telephony_service = self.create_telephony_service()
        return self._telephony_service

    @property
    def service(self) -> BaseTelephonyService:
        return self.initialize_service()

    @property
    def provider(self) -> TelephonyProvider:
        return self._config.provider

    def get_config(self) -> dict[str, object]:
        """Return the service's public media configuration, not its credentials."""
        return self.service.get_config()

    async def disconnect(self) -> None:
        if self._telephony_service is not None:
            await self._telephony_service.disconnect()
            self._telephony_service = None
