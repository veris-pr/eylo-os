"""Twilio telephony service implementation.

This module implements the BaseTelephonyService interface for Twilio,
providing WebSocket media streaming and call control capabilities.
"""

import base64
import json
import logging
from http import HTTPStatus
from typing import Any, Dict, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import WebSocket
from pydantic import ValidationError

from eylo.common.contracts.speech_runtime import (
    SpeechTransportEncoding,
    SpeechTransportFormat,
)
from eylo.common.outbound import (
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendSucceeded,
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
    StreamTokenRequirement,
    TelephonyConfig,
    TelephonyControlResult,
    TelephonyMessageParser,
    TelephonyOperationCapabilities,
    TelephonyOperationProfile,
    TelephonyOperationSupport,
    TelephonyProvider,
    classify_provider_failure,
)
from eylo.sockets.telephony.config import TwilioSettings
from eylo.sockets.telephony.twilio.rest_client import TwilioRestClient
from eylo.sockets.telephony.twilio.rest_contracts import (
    CREATE_FAILURE_OPERATION,
    CREATE_OPERATION,
    CallFailureCode,
)
from eylo.sockets.telephony.twilio.stream_contracts import (
    ClearCommand,
    MediaCommand,
    OutboundAudio,
    StreamMessage,
)
from eylo.sockets.telephony.twilio.stream_contracts import Event as StreamEvent
from eylo.sockets.telephony.twilio.stream_contracts import Start as StreamStart

logger = logging.getLogger(__name__)


class TwilioMessageParser(TelephonyMessageParser):
    """Normalize Twilio frames once; routing is still untrusted here."""

    def parse_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        if isinstance(raw_message, bytes):
            return CarrierIgnoredMessage()
        message = StreamMessage.model_validate_json(raw_message)
        if message.event == StreamEvent.START:
            start = message.start or StreamStart()
            custom = start.custom_parameters
            return CarrierStartMessage(
                metadata=CallMetadata(
                    call_sid=custom.call_sid or start.call_sid,
                    stream_sid=start.stream_sid,
                    from_number=custom.from_number,
                    to_number=custom.to_number,
                    organization_id=UUID(custom.organization_id)
                    if custom.organization_id
                    else None,
                    agent_id=UUID(custom.agent_id) if custom.agent_id else None,
                    direction=CallMetadata.normalize_direction(custom.direction),
                    initial_message=custom.initial_message,
                    media_stream_token=custom.stream_token
                    or custom.legacy_stream_token,
                    stream_token_requirement=(
                        StreamTokenRequirement.REQUIRED
                        if custom.requires_stream_token
                        else StreamTokenRequirement.NOT_REQUIRED
                    ),
                )
            )
        if (
            message.event == StreamEvent.MEDIA
            and message.media
            and message.media.payload
        ):
            return InboundMediaMessage(
                payload=base64.b64decode(message.media.payload),
                timestamp=message.media.timestamp,
                track=message.media.track,
                sequence_number=message.sequence_number,
            )
        if message.event == StreamEvent.DTMF and message.dtmf:
            digits = message.dtmf.digit or message.dtmf.digits
            if digits:
                return CarrierDtmfMessage(digits=digits)
        return CarrierIgnoredMessage()


class TwilioService(BaseTelephonyService):
    """Twilio telephony service implementation."""

    def __init__(
        self, config: TelephonyConfig, websocket: Optional[WebSocket] = None
    ) -> None:
        """Initialize Twilio service.

        Args:
            config: Telephony configuration
            websocket: Optional WebSocket connection for media streaming

        """
        self.settings = config.require_settings(TwilioSettings)
        super().__init__(config)
        self.websocket = websocket
        self._parser = TwilioMessageParser()

    @property
    def provider(self) -> TelephonyProvider:
        """Get the provider identifier.

        Returns:
            TelephonyProvider.TWILIO

        """
        return TelephonyProvider.TWILIO

    def set_websocket(self, websocket: WebSocket) -> None:
        """Set the WebSocket connection.

        Args:
            websocket: WebSocket connection

        """
        self.websocket = websocket
        self._is_connected = True

    async def send_media(self, message: OutboundMediaMessage) -> None:
        """Send media (audio) to Twilio via WebSocket.

        Args:
            message: Outbound media message

        """
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        # Encode audio to base64 for Twilio
        payload_b64 = base64.b64encode(message.payload).decode("utf-8")

        command = MediaCommand(
            stream_sid=message.stream_sid, media=OutboundAudio(payload=payload_b64)
        )
        await self.websocket.send_json(command.model_dump(mode="json", by_alias=True))

    async def send_clear(self, stream_sid: str) -> bool:
        """Send clear signal to Twilio to empty audio buffer.

        Args:
            stream_sid: Stream identifier

        """
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        try:
            command = ClearCommand(stream_sid=stream_sid)
            await self.websocket.send_json(
                command.model_dump(mode="json", by_alias=True)
            )
            logger.debug(f"Sent Twilio clear event for stream {stream_sid}")
            return True

        except Exception:
            logger.warning("Twilio clear write failed.")
            raise

    def build_twiml_response(
        self,
        ws_url: str,
        custom_params: Dict[str, Any],
    ) -> str:
        """Build TwiML response for Twilio call control.

        Args:
            ws_url: WebSocket URL for media streaming
            custom_params: Custom parameters to pass to the stream

        Returns:
            TwiML XML string

        """
        params_xml: list[str] = []
        for k, v in custom_params.items():
            params_xml.append(f'<Parameter name="{k}" value="{quote(str(v))}" />')
        params_str = "\n".join(params_xml)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
      <Connect>
        <Stream url="{ws_url}">
          {params_str}
        </Stream>
      </Connect>
    </Response>"""

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        ws_url: str,
        custom_params: Dict[str, Any],
        authorization: OutboundSendAuthorization,
        status_callback_url: Optional[str] = None,
    ) -> OutboundSendOutcome:
        """Initiate an outbound call via Twilio REST API.

        Args:
            to_number: Destination phone number
            from_number: Source phone number
            ws_url: WebSocket URL for media streaming
            custom_params: Custom parameters
            status_callback_url: URL for call status updates

        Returns:
            Response data from Twilio API

        """
        del authorization  # Twilio Calls API exposes no client idempotency slot.
        twiml = self.build_twiml_response(ws_url, custom_params)
        client = self._make_rest_client()
        try:
            response = await client.create_call(
                to_number=to_number,
                from_number=from_number,
                twiml=twiml,
                status_callback_url=status_callback_url or "",
            )
        except ValidationError:
            return OutboundSendUnknown(failure_code=CallFailureCode.RESPONSE_INVALID)
        except Exception as error:  # noqa: BLE001 - adapter owns provider taxonomy
            return classify_provider_failure(error, operation=CREATE_FAILURE_OPERATION)
        call_sid = (response.sid or "").strip()
        if not call_sid:
            return OutboundSendUnknown(failure_code=CallFailureCode.RESPONSE_INVALID)
        return OutboundSendSucceeded(
            provider_reference=call_sid,
            status_code=HTTPStatus.CREATED,
        )

    def create_message_parser(self) -> TelephonyMessageParser:
        """Create a message parser for Twilio.

        Returns:
            TwilioMessageParser instance

        """
        return self._parser

    def get_config(self) -> SpeechTransportFormat:
        """Return the Twilio baseline STT configuration."""
        return SpeechTransportFormat(
            encoding=SpeechTransportEncoding.MULAW, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    def get_output_format(self) -> CarrierAudioFormat:
        """Return the Twilio baseline TTS output format metadata."""
        return CarrierAudioFormat(
            encoding=AudioEncoding.PCM_MULAW, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    async def disconnect(self) -> None:
        """Disconnect from Twilio service."""
        self._is_connected = False
        self.websocket = None

    def _make_rest_client(self) -> TwilioRestClient:
        """Create a TwilioRestClient using per-org credentials from config."""
        return TwilioRestClient(
            account_sid=self.settings.account_sid,
            auth_token=self.settings.auth_token,
        )

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Terminate an active Twilio call.

        Args:
            call_sid: The Twilio Call SID

        Returns:
            Response data from Twilio API

        """
        return await self._make_rest_client().end_call(call_sid)

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Transfer an active Twilio call to another number.

        Args:
            call_sid: The Twilio Call SID
            to_number: Destination phone number in E.164 format

        Returns:
            Response data from Twilio API

        """
        return await self._make_rest_client().transfer_call(call_sid, to_number)

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones on an active Twilio call.

        Args:
            call_sid: The Twilio Call SID
            digits: DTMF digits to send

        Returns:
            Response data from Twilio API

        """
        return await self._make_rest_client().send_dtmf(call_sid, digits)

    def outbound_call_profile(self) -> TelephonyOperationProfile:
        return TelephonyOperationProfile(
            provider_operation=CREATE_OPERATION,
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin="https://api.twilio.com",
            capabilities=TelephonyOperationCapabilities(
                provider_idempotency=TelephonyOperationSupport.UNSUPPORTED,
                reconciliation=TelephonyOperationSupport.UNSUPPORTED,
            ),
        )
