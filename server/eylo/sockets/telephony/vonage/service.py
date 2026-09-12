"""Vonage telephony service implementation.

This module implements the BaseTelephonyService interface for Vonage,
providing WebSocket audio streaming and call control via NCCO.

Based on vocode-core production implementation:
- https://github.com/vocodedev/vocode-core/tree/main/vocode/streaming/telephony/conversation/vonage_phone_conversation.py
- https://github.com/vocodedev/vocode-core/tree/main/vocode/streaming/telephony/client/vonage_client.py

Key Differences from Twilio/Plivo:
- Audio Format: LINEAR16 @ 16kHz (vs μ-law @ 8kHz)
- Protocol: Binary WebSocket frames (vs JSON events)
- Call Control: NCCO JSON (vs TwiML XML)
- No mark/checkpoint events (simplified protocol)
"""

import json
import logging
import time
from http import HTTPStatus
from typing import Any, Dict, Optional
from uuid import uuid4

import aiohttp
import jwt
from fastapi import HTTPException, WebSocket
from pydantic import ValidationError

from eylo.common.contracts.speech_runtime import (
    SpeechTransportEncoding,
    SpeechTransportFormat,
)
from eylo.common.outbound import (
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendRetryable,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
    OutboundTransportKind,
)
from eylo.sockets.telephony.base import (
    AudioEncoding,
    BaseTelephonyService,
    CallMetadata,
    CarrierAudioFormat,
    CarrierDtmfMessage,
    CarrierIgnoredMessage,
    CarrierStartMessage,
    InboundMediaMessage,
    OutboundMediaMessage,
    ParsedCarrierMessage,
    TelephonyConfig,
    TelephonyControlAccepted,
    TelephonyControlFailureCode,
    TelephonyControlOperation,
    TelephonyControlResult,
    TelephonyControlUnknown,
    TelephonyMessageParser,
    TelephonyOperationCapabilities,
    TelephonyOperationProfile,
    TelephonyOperationSupport,
    TelephonyProvider,
    classify_control_failure,
)
from eylo.sockets.telephony.config import VonageSettings
from eylo.sockets.telephony.vonage.contracts import (
    CALLS_URL,
    CREATE_OPERATION,
    REQUEST_TIMEOUT_SECONDS,
    VOICE_ORIGIN,
    ConnectAction,
    CreateCallRequest,
    CreateCallResponse,
    CreateFailureCode,
    DtmfRequest,
    HangupRequest,
    MediaContentType,
    NccoDestination,
    PhoneEndpoint,
    TransferRequest,
    WebSocketEndpoint,
)
from eylo.sockets.telephony.vonage.stream_contracts import ClearCommand, StreamMessage
from eylo.sockets.telephony.vonage.stream_contracts import Event as StreamEvent

logger = logging.getLogger(__name__)

# Vonage audio constants (from vocode-core)
VONAGE_SAMPLING_RATE = 16000  # 16kHz
VONAGE_AUDIO_ENCODING = AudioEncoding.LINEAR16
VONAGE_CHUNK_SIZE = 640  # 20ms at 16kHz with 16-bit samples (640 bytes)
VONAGE_CONTENT_TYPE = MediaContentType.PCM16_16KHZ.value
PCM_SILENCE_BYTE = b"\x00"


class _VonageApplicationClient:
    """Minimal application JWT signer for the async Voice API calls below."""

    def __init__(self, *, application_id: str, private_key: str) -> None:
        self._application_id = application_id
        self._private_key = private_key

    def generate_application_jwt(self) -> str:
        issued_at = int(time.time())
        return jwt.encode(
            {
                "application_id": self._application_id,
                "iat": issued_at,
                "exp": issued_at + 60,
                "jti": str(uuid4()),
            },
            self._private_key,
            algorithm="RS256",
        )


class VonageMessageParser(TelephonyMessageParser):
    """Separate binary PCM from typed JSON controls without granting routing authority."""

    def __init__(self) -> None:
        self._metadata: CallMetadata | None = None

    def parse_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        if isinstance(raw_message, bytes):
            return self.parse_binary_message(raw_message)
        message = StreamMessage.model_validate_json(raw_message)
        if message.event in {
            StreamEvent.DTMF,
            StreamEvent.LEGACY_DTMF,
            StreamEvent.LEGACY_INPUT,
        }:
            digits = message.keypad_digits
            if digits:
                return CarrierDtmfMessage(digits=digits)
        if message.event == StreamEvent.LEGACY_START and self._metadata is not None:
            return CarrierStartMessage(metadata=self._metadata)
        return CarrierIgnoredMessage()

    def parse_binary_message(self, raw_bytes: bytes) -> InboundMediaMessage:
        """Keep native PCM bytes and their resource identity without JSON conversion."""
        return InboundMediaMessage(payload=raw_bytes, timestamp="", track="inbound")

    def set_metadata(self, metadata: CallMetadata) -> None:
        """Accept only the caller's already resolved metadata, never JSON overrides."""
        self._metadata = metadata


class VonageService(BaseTelephonyService):
    """Vonage telephony service implementation.

    Provides real-time LINEAR16 audio streaming at 16kHz via WebSocket
    and call control using NCCO (Nexmo Call Control Objects).

    Audio Format:
    - Encoding: LINEAR16 (PCM signed 16-bit little-endian)
    - Sample Rate: 16000 Hz
    - Chunk Size: 640 bytes (20ms)
    - Content-Type: audio/l16;rate=16000
    """

    def __init__(
        self, config: TelephonyConfig, websocket: Optional[WebSocket] = None
    ) -> None:
        """Initialize Vonage service with REST client.

        Args:
            config: Telephony configuration containing Vonage credentials
            websocket: Optional WebSocket connection for audio streaming

        """
        self.settings = config.require_settings(VonageSettings)
        # Override config for Vonage-specific settings
        config.encoding = VONAGE_AUDIO_ENCODING
        config.sample_rate = VONAGE_SAMPLING_RATE

        super().__init__(config)
        self.websocket = websocket
        self._parser = VonageMessageParser()
        self.client: _VonageApplicationClient | None = None

        try:
            self.client = _VonageApplicationClient(
                application_id=self.settings.application_id,
                private_key=self.settings.private_key,
            )
            logger.info("Vonage client initialized successfully")
        except Exception as error:
            logger.error(
                "Failed to initialize Vonage client error_type=%s",
                type(error).__name__,
            )
            self.client = None

    @property
    def provider(self) -> TelephonyProvider:
        """Get the provider identifier.

        Returns:
            TelephonyProvider.VONAGE

        """
        return TelephonyProvider.VONAGE

    def set_websocket(self, websocket: WebSocket) -> None:
        """Set the WebSocket connection.

        Args:
            websocket: WebSocket connection for audio streaming

        """
        self.websocket = websocket
        self._is_connected = True

    async def send_media(self, message: OutboundMediaMessage) -> None:
        """Send LINEAR16 audio to Vonage via binary WebSocket.

        Vonage expects raw LINEAR16 audio bytes, not JSON-wrapped payloads.
        Audio is sent as binary WebSocket frames.

        Args:
            message: Outbound media message with LINEAR16 audio

        """
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        try:
            # Pad odd-length chunks with silence (Vonage requirement)
            payload = message.payload
            if len(payload) % 2 == 1:
                payload += PCM_SILENCE_BYTE

            # Send raw binary audio (no JSON wrapper)
            await self.websocket.send_bytes(payload)

        except Exception:
            logger.warning("Vonage media write failed.")
            raise

    async def send_clear(self, stream_sid: str) -> bool:
        """Request buffered playback cancellation on this call's WebSocket."""
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")
        await self.websocket.send_text(ClearCommand().model_dump_json())
        return True

    def build_ncco_response(
        self,
        ws_url: str,
        custom_params: Dict[str, Any],
    ) -> str:
        """Serialize the same typed stream instruction used by outbound calls."""
        return json.dumps(
            [
                action.model_dump(mode="json", by_alias=True)
                for action in self._stream_ncco(ws_url, custom_params)
            ]
        )

    def _stream_ncco(
        self,
        ws_url: str,
        custom_params: Dict[str, Any],
    ) -> list[ConnectAction]:
        """Preserve encoded routing parameters without interpreting platform identity."""
        # Build WebSocket endpoint
        final_url = ws_url
        if custom_params:
            # Encode params in URL query string
            import urllib.parse

            query_params = urllib.parse.urlencode(custom_params)
            separator = "&" if "?" in ws_url else "?"
            final_url = f"{ws_url}{separator}{query_params}"

        return [ConnectAction(endpoint=[WebSocketEndpoint(uri=final_url)])]

    def build_twiml_response(
        self,
        ws_url: str,
        custom_params: Dict[str, Any],
    ) -> str:
        """Alias for build_ncco_response to satisfy BaseTelephonyService interface.

        Args:
            ws_url: WebSocket URL for audio streaming
            custom_params: Custom parameters

        Returns:
            NCCO JSON string

        """
        return self.build_ncco_response(ws_url, custom_params)

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        ws_url: str,
        custom_params: Dict[str, Any],
        authorization: OutboundSendAuthorization,
        status_callback_url: Optional[str] = None,
    ) -> OutboundSendOutcome:
        """Initiate an outbound call via Vonage Voice API.

        Args:
            to_number: Destination phone number (E.164 format)
            from_number: Source phone number (Vonage number)
            ws_url: WebSocket URL for audio streaming
            custom_params: Custom parameters
            status_callback_url: Optional URL for call status events

        Returns:
            Response data from Vonage API containing uuid

        Raises:
            RuntimeError: If Vonage client not initialized or call fails

        """
        del authorization  # Vonage Voice API exposes no client idempotency slot.
        if not self.client:
            return OutboundSendTerminal(failure_code=CreateFailureCode.NOT_CONFIGURED)

        try:
            request = CreateCallRequest(
                to=[PhoneEndpoint(number=to_number)],
                from_endpoint=PhoneEndpoint(number=from_number),
                ncco=self._stream_ncco(ws_url, custom_params),
                event_url=[status_callback_url] if status_callback_url else None,
            )

            # Make REST API call using aiohttp (async)
            jwt_token = self.client.generate_application_jwt()

            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    CALLS_URL,
                    json=request.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    headers={"Authorization": f"Bearer {jwt_token}"},
                ) as response:
                    if not response.ok:
                        await response.read()
                        if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                            return OutboundSendRetryable(
                                failure_code=CreateFailureCode.REJECTED,
                                status_code=response.status,
                            )
                        if (
                            HTTPStatus.BAD_REQUEST
                            <= response.status
                            < HTTPStatus.INTERNAL_SERVER_ERROR
                            and response.status != HTTPStatus.REQUEST_TIMEOUT
                        ):
                            return OutboundSendTerminal(
                                failure_code=CreateFailureCode.REJECTED,
                                status_code=response.status,
                            )
                        return OutboundSendUnknown(
                            failure_code=CreateFailureCode.UNCONFIRMED,
                            status_code=response.status,
                        )

                    try:
                        response_data = CreateCallResponse.model_validate(
                            await response.json()
                        )
                    except ValidationError:
                        return OutboundSendUnknown(
                            failure_code=CreateFailureCode.RESPONSE_INVALID,
                            status_code=response.status,
                        )
                    vonage_uuid = response_data.uuid.strip()
                    if not vonage_uuid:
                        return OutboundSendUnknown(
                            failure_code=CreateFailureCode.RESPONSE_INVALID,
                            status_code=response.status,
                        )
                    logger.info("Initiated Vonage call")
                    return OutboundSendSucceeded(
                        provider_reference=vonage_uuid,
                        status_code=response.status,
                    )

        except Exception:  # noqa: BLE001 - transport ambiguity forbids resend
            logger.warning("Vonage call initiation outcome is unconfirmed")
            return OutboundSendUnknown(failure_code=CreateFailureCode.UNCONFIRMED)

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """End an active Vonage call.

        Args:
            call_sid: Vonage call UUID

        Returns:
            Response data confirming call hangup

        Raises:
            RuntimeError: If Vonage client not initialized or request fails

        """
        if not self.client:
            raise RuntimeError("Vonage client not initialized. Check credentials.")

        try:
            jwt_token = self.client.generate_application_jwt()

            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(
                    f"{CALLS_URL}/{call_sid}",
                    json=HangupRequest().model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {jwt_token}"},
                ) as response:
                    if not response.ok:
                        return classify_control_failure(
                            HTTPException(status_code=response.status),
                            operation=TelephonyControlOperation.END,
                        )

                    logger.info("Ended Vonage call")
                    return TelephonyControlAccepted(status_code=response.status)

        except (TimeoutError, aiohttp.ClientError):
            logger.warning("Vonage call end outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.END_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - JWT/provider failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.END
            )

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Transfer an active Vonage call to another number.

        Uses NCCO transfer action to connect the call to a new phone number.

        Args:
            call_sid: Vonage call UUID
            to_number: Destination phone number in E.164 format

        Returns:
            Response data from Vonage API

        """
        ncco = [ConnectAction(endpoint=[PhoneEndpoint(number=to_number)])]
        return await self.update_call(call_sid, ncco)

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones to Vonage call.

        Args:
            call_sid: Vonage call UUID
            digits: DTMF digits to send (0-9, *, #)

        Returns:
            Response data confirming DTMF sent

        Raises:
            RuntimeError: If Vonage client not initialized or request fails

        """
        if not self.client:
            raise RuntimeError("Vonage client not initialized. Check credentials.")

        try:
            jwt_token = self.client.generate_application_jwt()

            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(
                    f"{CALLS_URL}/{call_sid}/dtmf",
                    json=DtmfRequest(digits=digits).model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {jwt_token}"},
                ) as response:
                    if not response.ok:
                        return classify_control_failure(
                            HTTPException(status_code=response.status),
                            operation=TelephonyControlOperation.DTMF,
                        )

                    logger.debug("Sent DTMF to Vonage call")
                    return TelephonyControlAccepted(status_code=response.status)

        except (TimeoutError, aiohttp.ClientError):
            logger.warning("Vonage DTMF outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.DTMF_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - JWT/provider failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.DTMF
            )

    async def update_call(
        self,
        call_uuid: str,
        ncco: list[ConnectAction],
    ) -> TelephonyControlResult:
        """Update an active call with new NCCO actions.

        Used for transferring calls or changing call flow.

        Args:
            call_uuid: Vonage call UUID
            ncco: New NCCO actions (as list of dicts)

        Returns:
            True if successful

        Raises:
            RuntimeError: If Vonage client not initialized or request fails

        """
        if not self.client:
            raise RuntimeError("Vonage client not initialized. Check credentials.")

        try:
            jwt_token = self.client.generate_application_jwt()

            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.put(
                    f"{CALLS_URL}/{call_uuid}",
                    json=TransferRequest(
                        destination=NccoDestination(ncco=ncco),
                    ).model_dump(mode="json", by_alias=True),
                    headers={"Authorization": f"Bearer {jwt_token}"},
                ) as response:
                    if not response.ok:
                        return classify_control_failure(
                            HTTPException(status_code=response.status),
                            operation=TelephonyControlOperation.TRANSFER,
                        )

                    logger.info("Updated Vonage call")
                    return TelephonyControlAccepted(status_code=response.status)

        except (TimeoutError, aiohttp.ClientError):
            logger.warning("Vonage call transfer outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.TRANSFER_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - JWT/provider failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.TRANSFER
            )

    def create_message_parser(self) -> TelephonyMessageParser:
        """Create a message parser for Vonage.

        Returns:
            VonageMessageParser instance

        """
        return self._parser

    async def receive_binary_audio(self, audio_bytes: bytes) -> InboundMediaMessage:
        """Receive and parse binary audio from Vonage WebSocket.

        Args:
            audio_bytes: Raw LINEAR16 audio bytes from WebSocket

        Returns:
            InboundMediaMessage with parsed audio

        """
        return self._parser.parse_binary_message(audio_bytes)

    async def disconnect(self) -> None:
        """Disconnect from Vonage service."""
        self._is_connected = False
        self.websocket = None

    def get_config(self) -> SpeechTransportFormat:
        """Return provider-specific base configuration for audio processing."""
        return SpeechTransportFormat(
            encoding=SpeechTransportEncoding.LINEAR16, sample_rate=VONAGE_SAMPLING_RATE
        )

    def get_output_format(self) -> CarrierAudioFormat:
        """Return provider-specific TTS output format metadata."""
        return CarrierAudioFormat(
            encoding=AudioEncoding.PCM_S16LE, sample_rate=VONAGE_SAMPLING_RATE
        )

    def outbound_call_profile(self) -> TelephonyOperationProfile:
        return TelephonyOperationProfile(
            provider_operation=CREATE_OPERATION,
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin=VOICE_ORIGIN,
            capabilities=TelephonyOperationCapabilities(
                provider_idempotency=TelephonyOperationSupport.UNSUPPORTED,
                reconciliation=TelephonyOperationSupport.UNSUPPORTED,
            ),
        )
