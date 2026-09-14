"""Plivo telephony service implementation.

This module implements the BaseTelephonyService interface for Plivo,
providing WebSocket audio streaming and call control capabilities.

Based on real-world implementations:
- https://github.com/bolna-ai/bolna (production Plivo integration)
- https://www.plivo.com/docs/voice/api/audio-stream/

WebSocket Message Format:
- Start event: {"event": "start", "start": {"streamId": "...", "callId": "...", ...}}
- Media event: {"event": "media", "media": {"payload": "base64_mulaw", "timestamp": "..."}}
- Stop event: {"event": "stop"}
- PlayAudio (outbound): {"event": "playAudio", "media": {"payload": "base64", "sampleRate": 8000, "contentType": "audio/x-mulaw"}}
- ClearAudio (interruption): {"event": "clearAudio", "streamId": "..."}
- Checkpoint (mark): {"event": "checkpoint", "streamId": "...", "name": "..."}

Audio Format: μ-law @ 8kHz (same as Twilio)
"""

import asyncio
import base64
import binascii
import json
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING, Optional

import httpx
from fastapi import WebSocket
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
    TELEPHONY_SAMPLE_RATE,
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
    TelephonyControlUnsupported,
    TelephonyMessageParser,
    TelephonyOperationCapabilities,
    TelephonyOperationProfile,
    TelephonyOperationSupport,
    TelephonyProvider,
    classify_control_failure,
)
from eylo.sockets.telephony.config import PlivoSettings
from eylo.sockets.telephony.plivo.bootstrap import render_stream_xml
from eylo.sockets.telephony.plivo.rest_contracts import (
    CREATE_OPERATION,
    CREATE_ORIGIN,
    CREATE_TIMEOUT_SECONDS,
    CallbackMethod,
    CreateCallRequest,
    CreateCallResponse,
    CreateFailureCode,
)
from eylo.sockets.telephony.plivo.stream_contracts import (
    ClearCommand,
    MediaCommand,
    OutboundAudio,
    StreamMessage,
)
from eylo.sockets.telephony.plivo.stream_contracts import Event as StreamEvent
from eylo.sockets.telephony.plivo.stream_contracts import Start as StreamStart
from eylo.sockets.telephony.stream_parameters import StreamParameters

if TYPE_CHECKING:
    from plivo.rest.client import Client

logger = logging.getLogger(__name__)


class PlivoMessageParser(TelephonyMessageParser):
    """Normalize Plivo JSON; retain the existing malformed-audio drop policy."""

    def parse_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        if isinstance(raw_message, bytes):
            return CarrierIgnoredMessage()
        message = StreamMessage.model_validate_json(raw_message)
        if message.event == StreamEvent.START:
            start = message.start or StreamStart()
            return CarrierStartMessage(
                metadata=CallMetadata(
                    call_sid=start.call_id,
                    stream_sid=start.stream_id,
                    from_number=start.from_number,
                    to_number=start.to_number,
                )
            )
        if (
            message.event == StreamEvent.MEDIA
            and message.media
            and message.media.payload
        ):
            try:
                payload = base64.b64decode(message.media.payload)
            except (ValueError, binascii.Error):
                logger.warning("Plivo audio payload could not be decoded.")
                return CarrierIgnoredMessage()
            return InboundMediaMessage(
                payload=payload,
                timestamp=message.media.timestamp,
                track=message.media.track,
                sequence_number=message.sequence_number,
            )
        if message.event in {StreamEvent.DTMF, StreamEvent.LEGACY_DIGITS}:
            digits = message.keypad_digits
            if digits:
                return CarrierDtmfMessage(digits=digits)
        return CarrierIgnoredMessage()


class PlivoService(BaseTelephonyService):
    """Plivo telephony service implementation.

    Provides real-time audio streaming and call control using Plivo's
    WebSocket-based Audio Stream API.

    Based on production implementation from bolna-ai.
    """

    def __init__(
        self, config: TelephonyConfig, websocket: Optional[WebSocket] = None
    ) -> None:
        """Initialize Plivo service with REST client.

        Args:
            config: Telephony configuration containing auth credentials
            websocket: Optional WebSocket connection for media streaming

        """
        self.settings = config.require_settings(PlivoSettings)
        super().__init__(config)
        self.websocket = websocket
        self._parser = PlivoMessageParser()
        self.client: Client | None = None

        try:
            import plivo

            self.client = plivo.RestClient(
                auth_id=self.settings.auth_id,
                auth_token=self.settings.auth_token,
            )
            logger.info("Plivo client initialized successfully")
        except ImportError:
            logger.error("Plivo SDK not installed. Install with: pip install plivo")
            self.client = None
        except Exception as error:
            logger.error(
                "Failed to initialize Plivo client error_type=%s",
                type(error).__name__,
            )
            self.client = None

    @property
    def provider(self) -> TelephonyProvider:
        """Get the provider identifier.

        Returns:
            TelephonyProvider.PLIVO

        """
        return TelephonyProvider.PLIVO

    def set_websocket(self, websocket: WebSocket) -> None:
        """Set the WebSocket connection.

        Args:
            websocket: WebSocket connection

        """
        self.websocket = websocket
        self._is_connected = True

    async def send_media(self, message: OutboundMediaMessage) -> None:
        """Send audio media to Plivo WebSocket stream.

        Plivo playAudio event format (from bolna-ai):
        {
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": 8000,
                "payload": "base64_encoded_audio"
            }
        }

        Args:
            message: Outbound media message with audio payload

        """
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        try:
            # Encode to base64
            payload_b64 = base64.b64encode(message.payload).decode("utf-8")

            command = MediaCommand(media=OutboundAudio(payload=payload_b64))
            await self.websocket.send_json(
                command.model_dump(mode="json", by_alias=True)
            )

        except Exception:
            logger.warning("Plivo media write failed.")
            raise

    def build_twiml_response(
        self,
        ws_url: str,
        custom_params: StreamParameters,
    ) -> str:
        """Build escaped XML with native SDK types; do not mask serialization errors."""
        return render_stream_xml(ws_url, custom_params)

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        ws_url: str,
        custom_params: StreamParameters,
        authorization: OutboundSendAuthorization,
        status_callback_url: Optional[str] = None,
    ) -> OutboundSendOutcome:
        """Initiate an outbound call via Plivo REST API.

        Plivo requires answer_url to be an HTTP endpoint that returns XML.
        We point it to our /api/voice/plivo/answer callback which returns
        Plivo XML with a <Stream> element pointing to the ws_url.

        The create response contains a request UUID. The actual call UUID arrives
        through callbacks. Direct async HTTP avoids the SDK's implicit POST retries.
        """
        del authorization  # Plivo Calls API exposes no client idempotency slot.

        try:
            from urllib.parse import quote, urlparse

            # Derive HTTP answer_url from ws_url's domain
            parsed = urlparse(ws_url)
            server_domain = parsed.netloc
            answer_url = (
                f"https://{server_domain}/api/voice/plivo/answer"
                f"?ws_url={quote(ws_url, safe='')}"
            )

            request = CreateCallRequest(
                from_number=from_number,
                to=to_number,
                answer_url=answer_url,
                hangup_url=status_callback_url or None,
                hangup_method=CallbackMethod.POST if status_callback_url else None,
            )
            async with httpx.AsyncClient(
                timeout=CREATE_TIMEOUT_SECONDS,
                auth=httpx.BasicAuth(self.settings.auth_id, self.settings.auth_token),
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{CREATE_ORIGIN}/v1/Account/{quote(self.settings.auth_id, safe='')}/Call/",
                    json=request.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                )
                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    return OutboundSendRetryable(
                        failure_code=CreateFailureCode.REJECTED,
                        status_code=response.status_code,
                    )
                if response.status_code >= HTTPStatus.MULTIPLE_CHOICES:
                    if (
                        HTTPStatus.BAD_REQUEST
                        <= response.status_code
                        < HTTPStatus.INTERNAL_SERVER_ERROR
                        and response.status_code != HTTPStatus.REQUEST_TIMEOUT
                    ):
                        return OutboundSendTerminal(
                            failure_code=CreateFailureCode.REJECTED,
                            status_code=response.status_code,
                        )
                    return OutboundSendUnknown(
                        failure_code=CreateFailureCode.UNCONFIRMED,
                        status_code=response.status_code,
                    )
                try:
                    accepted = CreateCallResponse.model_validate_json(response.content)
                except ValidationError:
                    return OutboundSendUnknown(
                        failure_code=CreateFailureCode.RESPONSE_INVALID,
                        status_code=response.status_code,
                    )
            request_uuid = accepted.request_uuid.strip()
            if not request_uuid:
                return OutboundSendUnknown(
                    failure_code=CreateFailureCode.RESPONSE_INVALID,
                    status_code=response.status_code,
                )
            logger.info("Initiated Plivo call")
            return OutboundSendSucceeded(
                provider_reference=request_uuid,
                status_code=response.status_code,
            )

        except Exception:  # noqa: BLE001 - transport ambiguity forbids resend
            logger.warning("Plivo call initiation failed")
            return OutboundSendUnknown(failure_code=CreateFailureCode.UNCONFIRMED)

    def create_message_parser(self) -> TelephonyMessageParser:
        """Create a message parser for Plivo.

        Returns:
            PlivoMessageParser instance

        """
        return self._parser

    async def send_clear(self, stream_sid: str) -> bool:
        """Send clear signal to Plivo to empty audio buffer.

        Args:
            stream_sid: Stream identifier

        """
        await self.clear_stream(stream_sid)
        return True

    async def clear_stream(self, stream_sid: str) -> None:
        """Clear Plivo stream buffer (interrupt audio playback).

        Plivo clearAudio event format (from bolna-ai):
        {
            "event": "clearAudio",
            "streamId": "..."
        }

        Args:
            stream_sid: Stream identifier

        """
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        try:
            command = ClearCommand(stream_id=stream_sid)
            await self.websocket.send_json(
                command.model_dump(mode="json", by_alias=True)
            )
            logger.debug(f"Cleared Plivo stream: {stream_sid}")

        except Exception:
            logger.warning("Plivo clear write failed.")
            raise

    def get_config(self) -> SpeechTransportFormat:
        """Return the Plivo baseline STT configuration."""
        return SpeechTransportFormat(
            encoding=SpeechTransportEncoding.MULAW, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    def get_output_format(self) -> CarrierAudioFormat:
        """Return the Plivo baseline TTS output format metadata."""
        return CarrierAudioFormat(
            encoding=AudioEncoding.PCM_MULAW, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    async def send_checkpoint(self, stream_sid: str, mark_id: str) -> None:
        """Send checkpoint event (Plivo's equivalent of Twilio's mark).

        Plivo checkpoint format (from bolna-ai):
        {
            "event": "checkpoint",
            "streamId": "...",
            "name": "..."
        }

        Args:
            stream_sid: Stream identifier
            mark_id: Checkpoint/mark identifier

        """
        if not self.websocket:
            logger.warning("Cannot send checkpoint: WebSocket not connected")
            return

        try:
            message = {
                "event": "checkpoint",
                "streamId": stream_sid,
                "name": mark_id,
            }
            await self.websocket.send_json(message)
            logger.debug(f"Sent Plivo checkpoint: {mark_id}")

        except Exception as error:
            logger.error(
                "Failed to send Plivo checkpoint error_type=%s",
                type(error).__name__,
            )
            raise

    async def disconnect(self) -> None:
        """Disconnect from Plivo service."""
        self._is_connected = False
        self.websocket = None

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Terminate an active Plivo call.

        Uses Plivo's DELETE /Call/{uuid}/ API to hang up the call.
        Ref: https://www.plivo.com/docs/voice/api/call/#delete-a-call

        Args:
            call_sid: Plivo call UUID

        Returns:
            Response data confirming call hangup

        """
        if not self.client:
            raise RuntimeError("Plivo client not initialized. Check credentials.")

        try:
            # Plivo SDK is synchronous — run in thread to avoid blocking the event loop
            await asyncio.wait_for(
                asyncio.to_thread(self.client.calls.delete, call_sid),
                timeout=20,
            )
            logger.info("Ended Plivo call")
            return TelephonyControlAccepted()
        except TimeoutError:
            logger.warning("Plivo call end outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.END_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - SDK failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.END
            )

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Return explicit unsupported until Eylo hosts a signed answer URL."""
        del call_sid, to_number
        return TelephonyControlUnsupported(
            failure_code=TelephonyControlFailureCode.TRANSFER_UNSUPPORTED
        )

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones on an active Plivo call.

        Uses Plivo's DTMF API to send keypad tones.
        Ref: https://www.plivo.com/docs/voice/api/call/#send-digits-on-a-call

        Args:
            call_sid: Plivo call UUID
            digits: DTMF digits to send (0-9, *, #)

        Returns:
            Response data from Plivo API

        """
        if not self.client:
            raise RuntimeError("Plivo client not initialized. Check credentials.")

        try:
            # Plivo SDK is synchronous — run in thread to avoid blocking the event loop
            await asyncio.wait_for(
                asyncio.to_thread(
                    self.client.calls.send_digits,
                    call_sid,
                    digits=digits,
                ),
                timeout=20,
            )
            logger.info("Sent DTMF to Plivo call")
            return TelephonyControlAccepted()
        except TimeoutError:
            logger.warning("Plivo DTMF outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.DTMF_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - SDK failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.DTMF
            )

    def outbound_call_profile(self) -> TelephonyOperationProfile:
        return TelephonyOperationProfile(
            provider_operation=CREATE_OPERATION,
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin=CREATE_ORIGIN,
            capabilities=TelephonyOperationCapabilities(
                provider_idempotency=TelephonyOperationSupport.UNSUPPORTED,
                reconciliation=TelephonyOperationSupport.UNSUPPORTED,
            ),
        )
