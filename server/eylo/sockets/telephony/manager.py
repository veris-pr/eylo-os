"""Telephony Real-time Manager.

This module provides a unified interface for managing telephony services
across different providers (Twilio, Plivo, Exotel, etc.), following the
same pattern as STT and TTS managers.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import WebSocket

from eylo.common.contracts.speech_runtime import SpeechTransportFormat
from eylo.sockets.telephony.base import (
    BaseTelephonyService,
    CallMetadata,
    CarrierAudioFormat,
    CarrierMediaFailureCode,
    CarrierMediaResult,
    CarrierMediaStatus,
    CarrierStartMessage,
    OutboundMediaMessage,
    ParsedCarrierMessage,
    TelephonyConfig,
    TelephonyControlResult,
    TelephonyMessageParser,
    TelephonyProvider,
)
from eylo.sockets.telephony.factory import TelephonyFactory

logger = logging.getLogger(__name__)


class TelephonyRealtime:
    """Real-time telephony service with vendor abstraction.

    This class manages communication with telephony providers, providing:
    1. Vendor-agnostic message handling
    2. Media streaming (audio in/out)
    3. Call metadata extraction
    4. WebSocket lifecycle management
    """

    def __init__(
        self,
        websocket: WebSocket,
        provider: TelephonyProvider,
    ) -> None:
        """Initialize only the untrusted provider parser.

        The authenticated adapter is attached after start metadata resolves to
        an explicit organization-owned provider config revision.
        """
        self._organization_id: UUID | None = None
        self._session_id: str | None = None
        self._websocket = websocket
        self._provider = provider
        self._telephony_service: BaseTelephonyService | None = None
        self._parser = _create_message_parser(provider)

        # Call metadata
        self._call_metadata: Optional[CallMetadata] = None

    def activate(
        self,
        *,
        organization_id: UUID,
        session_id: str,
        telephony_config: TelephonyConfig,
    ) -> None:
        """Attach the authenticated adapter for the resolved config revision."""
        if self._telephony_service is not None:
            raise RuntimeError("Telephony realtime adapter is already active.")
        if telephony_config.provider is not self._provider:
            raise ValueError("Telephony config differs from the authenticated carrier.")
        service = TelephonyFactory(telephony_config).service
        service.set_websocket(self._websocket)
        self._organization_id = organization_id
        self._session_id = session_id
        self._telephony_service = service

    @property
    def provider(self) -> TelephonyProvider:
        """Get the telephony provider name.

        Returns:
            Provider name

        """
        return self._provider

    def get_config(self) -> SpeechTransportFormat:
        """Return the current provider's base configuration."""
        return self._active_service().get_config()

    def get_output_format(self) -> CarrierAudioFormat:
        """Return the provider-specific TTS output format metadata."""
        return self._active_service().get_output_format()

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Ask the active pinned carrier adapter to terminate its call."""
        return await self._active_service().end_call(call_sid)

    async def close_media_stream(self) -> None:
        """Close the local carrier WebSocket when remote control cannot finish."""
        await self._websocket.close(code=1000)

    @property
    def call_metadata(self) -> Optional[CallMetadata]:
        """Get the call metadata.

        Returns:
            CallMetadata if available, None otherwise

        """
        return self._call_metadata

    @property
    def is_connected(self) -> bool:
        """Check if the telephony service is connected.

        Returns:
            True if connected, False otherwise

        """
        return bool(self._telephony_service and self._telephony_service.is_connected)

    async def handle_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        """Decode once; start metadata remains untrusted until pipeline resolution."""
        try:
            message = self._parser.parse_message(raw_message)
            if isinstance(message, CarrierStartMessage):
                self._call_metadata = message.metadata
            return message
        except Exception:
            logger.error("Telephony message handling failed.")
            raise

    async def send_audio(
        self,
        audio_data: bytes,
        stream_sid: str,
    ) -> CarrierMediaResult:
        """Send audio data to the telephony provider.

        Args:
            audio_data: Raw audio bytes
            stream_sid: Stream identifier

        """
        try:
            message = OutboundMediaMessage(
                payload=audio_data,
                stream_sid=stream_sid,
            )
            await self._active_service().send_media(message)
            return CarrierMediaResult(
                status=CarrierMediaStatus.ACCEPTED,
                bytes_count=len(audio_data),
            )
        except Exception:
            logger.warning("Carrier audio write failed.")
            return CarrierMediaResult(
                status=CarrierMediaStatus.FAILED,
                bytes_count=len(audio_data),
                failure_code=CarrierMediaFailureCode.AUDIO_WRITE_FAILED,
            )

    async def handle_interruption(self, stream_sid: str) -> CarrierMediaResult:
        try:
            supported = await self._active_service().send_clear(stream_sid)
            return CarrierMediaResult(
                status=(
                    CarrierMediaStatus.ACCEPTED
                    if supported
                    else CarrierMediaStatus.UNSUPPORTED
                )
            )
        except Exception:
            logger.warning("Carrier interruption write failed.")
            return CarrierMediaResult(
                status=CarrierMediaStatus.FAILED,
                failure_code=CarrierMediaFailureCode.INTERRUPTION_WRITE_FAILED,
            )

    async def disconnect(self) -> None:
        """Disconnect from the telephony service."""
        try:
            if self._telephony_service is None:
                return
            await self._telephony_service.disconnect()
            logger.info(
                {
                    "message": "Telephony service disconnected",
                    "provider": self._provider,
                    "session_id": self._session_id,
                }
            )
        except Exception:
            logger.warning("Telephony service disconnect failed.")

    def _active_service(self) -> BaseTelephonyService:
        if self._telephony_service is None:
            raise RuntimeError("Telephony realtime adapter is not active.")
        return self._telephony_service


def _create_message_parser(provider: TelephonyProvider) -> TelephonyMessageParser:
    if provider is TelephonyProvider.TWILIO:
        from eylo.sockets.telephony.twilio.service import TwilioMessageParser

        return TwilioMessageParser()
    if provider is TelephonyProvider.PLIVO:
        from eylo.sockets.telephony.plivo.service import PlivoMessageParser

        return PlivoMessageParser()
    if provider is TelephonyProvider.VONAGE:
        from eylo.sockets.telephony.vonage.service import VonageMessageParser

        return VonageMessageParser()
    if provider is TelephonyProvider.EXOTEL:
        from eylo.sockets.telephony.exotel.service import ExotelMessageParser

        return ExotelMessageParser()
    raise ValueError(f"Unsupported telephony provider: {provider}")
