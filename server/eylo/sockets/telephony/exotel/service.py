"""Exotel call creation/control and carrier media translation."""

import base64
import json
import logging
import time
from http import HTTPStatus
from typing import Optional
from uuid import UUID

import aiohttp
from fastapi import HTTPException, WebSocket
from pydantic import ValidationError

from eylo.common.contracts.phone_numbers import PhoneNumberNormalizationService
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
    StreamTokenRequirement,
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
from eylo.sockets.telephony.config import ExotelSettings
from eylo.sockets.telephony.exotel.contracts import (
    CONNECT_OPERATION,
    CONNECT_TIMEOUT_SECONDS,
    ConnectFailureCode,
    ConnectParameters,
    ConnectRequest,
    ConnectResponse,
)
from eylo.sockets.telephony.exotel.stream_contracts import (
    ClearCommand,
    MediaCommand,
    OutboundAudio,
    StreamMessage,
    unpack_routing,
)
from eylo.sockets.telephony.exotel.stream_contracts import Event as StreamEvent
from eylo.sockets.telephony.exotel.stream_contracts import Start as StreamStart
from eylo.sockets.telephony.stream_parameters import StreamParameters

logger = logging.getLogger(__name__)
MILLISECONDS_PER_SECOND = 1000


class ExotelMessageParser(TelephonyMessageParser):
    """Normalize Exotel frames without logging raw media or routing secrets."""

    def parse_message(self, raw_message: str | bytes) -> ParsedCarrierMessage:
        if isinstance(raw_message, bytes):
            return CarrierIgnoredMessage()
        message = StreamMessage.model_validate_json(raw_message)
        if message.event == StreamEvent.START:
            return CarrierStartMessage(metadata=self._metadata(message))
        if (
            message.event == StreamEvent.MEDIA
            and message.media
            and message.media.payload
        ):
            media = message.media
            return InboundMediaMessage(
                payload=base64.b64decode(media.payload),
                timestamp=media.timestamp,
                track=media.track,
                sequence_number=(
                    message.sequence_number
                    if message.sequence_number is not None
                    else media.sequence_number
                ),
            )
        if message.event in {StreamEvent.DTMF, StreamEvent.LEGACY_DIGITS}:
            digits = message.keypad_digits
            if digits:
                return CarrierDtmfMessage(digits=digits)
        return CarrierIgnoredMessage()

    def _metadata(self, message: StreamMessage) -> CallMetadata:
        start = message.start or StreamStart()
        custom = unpack_routing(start.custom_parameters or {})
        if not start.from_number or not start.to_number:
            raise ValueError("From and To numbers are required")
        normalizer = PhoneNumberNormalizationService()
        from_result = normalizer.parse_to_e164(start.from_number)
        to_result = normalizer.parse_to_e164(start.to_number)
        if not from_result.success or not to_result.success:
            raise ValueError("From and To numbers must be valid phone numbers")
        if not from_result.e164 or not to_result.e164:
            raise ValueError("Phone number normalization returned no E.164 value")
        organization_id = custom.org_id or custom.alternate_org_id
        agent_id = custom.agent_id or custom.alternate_agent_id
        initial_message = custom.initial_message or custom.alternate_initial_message
        return CallMetadata(
            call_sid=start.call_sid,
            stream_sid=message.stream_sid,
            from_number=from_result.e164,
            to_number=to_result.e164,
            organization_id=UUID(organization_id) if organization_id else None,
            agent_id=UUID(agent_id) if agent_id else None,
            direction=CallMetadata.normalize_direction(
                custom.direction or custom.alternate_direction or "INBOUND"
            ),
            initial_message=initial_message if initial_message is not None else "Hello",
            media_stream_token=custom.stream_token or custom.alternate_stream_token,
            stream_token_requirement=(
                StreamTokenRequirement.REQUIRED
                if custom.requires_stream_token
                else StreamTokenRequirement.NOT_REQUIRED
            ),
        )


class ExotelService(BaseTelephonyService):
    """Own Exotel's carrier connections without platform routing policy."""

    def __init__(
        self, config: TelephonyConfig, websocket: Optional[WebSocket] = None
    ) -> None:
        """Initialize Exotel service.

        Args:
            config: Telephony configuration
            websocket: Optional WebSocket connection for media streaming

        """
        self.settings = config.require_settings(ExotelSettings)
        super().__init__(config)
        self.websocket = websocket
        self._parser = ExotelMessageParser()

    @property
    def provider(self) -> TelephonyProvider:
        """Get the provider identifier.

        Returns:
            TelephonyProvider.EXOTEL

        """
        return TelephonyProvider.EXOTEL

    def set_websocket(self, websocket: WebSocket) -> None:
        """Set the WebSocket connection.

        Args:
            websocket: WebSocket connection

        """
        self.websocket = websocket
        self._is_connected = True

    async def send_media(self, message: OutboundMediaMessage) -> None:
        """Send raw PCM audio to Exotel."""
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        # Convert raw bytes to base64
        payload_b64 = base64.b64encode(message.payload).decode("utf-8")

        command = MediaCommand(
            sequence_number=str(int(time.time())),
            stream_sid=message.stream_sid,
            media=OutboundAudio(
                payload=payload_b64,
                timestamp=str(int(time.time() * MILLISECONDS_PER_SECOND)),
            ),
        )

        try:
            await self.websocket.send_text(command.model_dump_json())
        except Exception:
            logger.warning("Exotel media write failed.")
            raise

    async def send_clear(self, stream_sid: str) -> bool:
        if not self.websocket:
            raise RuntimeError("Telephony WebSocket is not connected.")

        command = ClearCommand(stream_sid=stream_sid)

        try:
            await self.websocket.send_text(command.model_dump_json())
            return True
        except Exception:
            logger.warning("Exotel clear write failed.")
            raise

    def build_twiml_response(
        self,
        ws_url: str,
        custom_params: StreamParameters,
    ) -> str:
        """Return JSON bootstrap payload.

        Exotel Voicebot applets accept either a static WSS URL or an HTTPS endpoint that
        responds with {"url": "wss://..."}. We follow the latter so we can inject
        per-call query params (tokens, org IDs, etc.).
        """
        parameters = custom_params.as_wire()
        final_url = ws_url
        if parameters:
            from urllib.parse import urlencode

            query = urlencode(parameters)
            separator = "&" if "?" in final_url else "?"
            final_url = f"{final_url}{separator}{query}"

        return json.dumps({"url": final_url})

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        ws_url: str,
        custom_params: StreamParameters,
        authorization: OutboundSendAuthorization,
        status_callback_url: Optional[str] = None,
    ) -> OutboundSendOutcome:
        """Start the configured applet once; an ambiguous response never permits resend."""
        del authorization, ws_url  # Exotel exposes no client idempotency slot.

        api_key = self.settings.api_key
        api_token = self.settings.api_token
        account_sid = self.settings.account_sid
        app_id = self.settings.application_id

        phone_norm_service = PhoneNumberNormalizationService()

        # 2. Construct flow URL
        # Exotel docs specify my.exotel.com for the flow URL regardless of cluster.
        applet_url = f"http://my.exotel.com/{account_sid}/exoml/start_voice/{app_id}"
        # Exotel requires Url to be an HTTP applet.
        flow_url = applet_url

        # 3. Call Exotel REST API
        subdomain = self.settings.api_host
        url = f"https://{subdomain}/v1/Accounts/{account_sid}/Calls/connect.json"

        # Format numbers per Exotel expectations
        from_formatted = phone_norm_service.format_for_exotel(from_number)
        to_formatted = to_number  # E.164 accepted for customer leg

        timeout = aiohttp.ClientTimeout(total=CONNECT_TIMEOUT_SECONDS)
        try:
            parameters = ConnectParameters.model_validate(custom_params.as_wire())
            request = ConnectRequest(
                from_number=to_formatted,
                caller_id=from_formatted,
                url=flow_url,
                custom_field=parameters.packed_custom_field,
                status_callback=status_callback_url or None,
            )
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(api_key, api_token),
                timeout=timeout,
            ) as session:
                async with session.post(
                    url,
                    data=request.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                ) as resp:
                    text = await resp.text()
                    if resp.status >= HTTPStatus.BAD_REQUEST:
                        if resp.status == HTTPStatus.TOO_MANY_REQUESTS:
                            return OutboundSendRetryable(
                                failure_code=ConnectFailureCode.REJECTED,
                                status_code=resp.status,
                            )
                        if (
                            resp.status < HTTPStatus.INTERNAL_SERVER_ERROR
                            and resp.status != HTTPStatus.REQUEST_TIMEOUT
                        ):
                            return OutboundSendTerminal(
                                failure_code=ConnectFailureCode.REJECTED,
                                status_code=resp.status,
                            )
                        return OutboundSendUnknown(
                            failure_code=ConnectFailureCode.UNCONFIRMED,
                            status_code=resp.status,
                        )
                    try:
                        response = ConnectResponse.model_validate_json(text or "{}")
                    except ValidationError:
                        return OutboundSendUnknown(
                            failure_code=ConnectFailureCode.RESPONSE_INVALID,
                            status_code=resp.status,
                        )
                    call_sid = response.provider_reference
                    if not call_sid:
                        return OutboundSendUnknown(
                            failure_code=ConnectFailureCode.RESPONSE_INVALID,
                            status_code=resp.status,
                        )
                    logger.info("Initiated Exotel call")
                    return OutboundSendSucceeded(
                        provider_reference=call_sid,
                        status_code=resp.status,
                    )
        except Exception:  # noqa: BLE001 - transport ambiguity forbids resend
            logger.warning("Exotel call initiation outcome is unconfirmed")
            return OutboundSendUnknown(failure_code=ConnectFailureCode.UNCONFIRMED)

    def create_message_parser(self) -> TelephonyMessageParser:
        """Create a message parser for Exotel.

        Returns:
            ExotelMessageParser instance

        """
        return ExotelMessageParser()

    def get_config(self) -> SpeechTransportFormat:
        """Return the Exotel baseline STT configuration."""
        return SpeechTransportFormat(
            encoding=SpeechTransportEncoding.LINEAR16, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    def get_output_format(self) -> CarrierAudioFormat:
        return CarrierAudioFormat(
            encoding=AudioEncoding.PCM_S16LE, sample_rate=TELEPHONY_SAMPLE_RATE
        )

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Terminate an active Exotel call.

        Args:
            call_sid: The Exotel Call SID

        Returns:
            Response data from Exotel API

        """
        api_key = self.settings.api_key
        api_token = self.settings.api_token
        account_sid = self.settings.account_sid
        subdomain = self.settings.api_host
        url = f"https://{subdomain}/v1/Accounts/{account_sid}/Calls/{call_sid}.json"

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(api_key, api_token),
                timeout=timeout,
            ) as session:
                async with session.post(url, data={"Status": "completed"}) as resp:
                    if resp.status >= 300:
                        return classify_control_failure(
                            HTTPException(status_code=resp.status),
                            operation=TelephonyControlOperation.END,
                        )
                    return TelephonyControlAccepted(status_code=resp.status)
        except (TimeoutError, aiohttp.ClientError):
            logger.warning("Exotel call end outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.END_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - provider failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.END
            )

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Return explicit unsupported for Exotel live transfer."""
        del call_sid, to_number
        return TelephonyControlUnsupported(
            failure_code=TelephonyControlFailureCode.TRANSFER_UNSUPPORTED
        )

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones on an active Exotel call."""
        api_key = self.settings.api_key
        api_token = self.settings.api_token
        account_sid = self.settings.account_sid
        subdomain = self.settings.api_host
        url = (
            f"https://{subdomain}/v1/Accounts/{account_sid}/Calls/{call_sid}/SendDtmf/"
        )

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(api_key, api_token),
                timeout=timeout,
            ) as session:
                async with session.post(
                    url,
                    data={"Digits": digits, "Leg": "aleg"},
                ) as resp:
                    if resp.status >= 300:
                        return classify_control_failure(
                            HTTPException(status_code=resp.status),
                            operation=TelephonyControlOperation.DTMF,
                        )
                    return TelephonyControlAccepted(status_code=resp.status)
        except (TimeoutError, aiohttp.ClientError):
            logger.warning("Exotel DTMF outcome is unconfirmed")
            return TelephonyControlUnknown(
                failure_code=TelephonyControlFailureCode.DTMF_UNCONFIRMED
            )
        except Exception as error:  # noqa: BLE001 - provider failure taxonomy
            return classify_control_failure(
                error, operation=TelephonyControlOperation.DTMF
            )

    def outbound_call_profile(self) -> TelephonyOperationProfile:
        host = self.settings.api_host
        return TelephonyOperationProfile(
            provider_operation=CONNECT_OPERATION,
            transport_kind=OutboundTransportKind.HTTP,
            destination_origin=f"https://{host}",
            capabilities=TelephonyOperationCapabilities(
                provider_idempotency=TelephonyOperationSupport.UNSUPPORTED,
                reconciliation=TelephonyOperationSupport.UNSUPPORTED,
            ),
        )
