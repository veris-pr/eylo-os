"""Perform authenticated Twilio call-control REST requests."""

import base64
import logging
import re
from http import HTTPStatus
from xml.sax.saxutils import escape as xml_escape

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from eylo.common.outbound import (
    OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH,
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendSucceeded,
    OutboundSendUnknown,
)
from eylo.sockets.telephony.base import (
    TelephonyControlAccepted,
    TelephonyControlFailureCode,
    TelephonyControlOperation,
    TelephonyControlResult,
    TelephonyControlUnknown,
    TelephonyOperationProfile,
    classify_control_failure,
)
from eylo.sockets.telephony.number_purchase import (
    classify_number_purchase_status,
    number_purchase_profile,
    number_purchase_transport_unknown,
)
from eylo.sockets.telephony.twilio.endpoint import twilio_account_url
from eylo.sockets.telephony.twilio.number_contracts import (
    NUMBER_PURCHASE_TIMEOUT_SECONDS,
    NUMBER_SEARCH_DEFAULT_LIMIT,
    NUMBER_SEARCH_MAX_LIMIT,
    NUMBER_SEARCH_TIMEOUT_SECONDS,
    AvailableNumber,
    AvailableNumbersResponse,
    NumberFailureCode,
    NumberPurchaseRequest,
    NumberSearchRequest,
    NumberType,
    PurchasedNumber,
)
from eylo.sockets.telephony.twilio.rest_contracts import (
    CALL_TIMEOUT_SECONDS,
    CreateCallRequest,
    CreatedCall,
    EndCallRequest,
    TwimlUpdateRequest,
)

logger = logging.getLogger(__name__)


class TwilioRestClient:
    """A simple async client for interacting with the Twilio REST API.

    Args:
        account_sid: Twilio Account SID. Required.
        auth_token: Twilio Auth Token. Required.

    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.base_url = twilio_account_url(self.account_sid)
        self._auth_header = self._prepare_auth_header()

    def _prepare_auth_header(self) -> str:
        """Prepares the Basic authentication header."""
        auth_str = f"{self.account_sid}:{self.auth_token}".encode()
        return f"Basic {base64.b64encode(auth_str).decode()}"

    async def create_call(
        self, to_number: str, from_number: str, twiml: str, status_callback_url: str
    ) -> CreatedCall:
        """Send once and validate the consumed response before returning to orchestration."""
        request = CreateCallRequest(
            to=to_number,
            from_number=from_number,
            twiml=twiml,
            status_callback=status_callback_url,
        )

        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS) as client:
            url = f"{self.base_url}/Calls.json"
            try:
                resp = await client.post(
                    url,
                    data=request.model_dump(mode="json", by_alias=True),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if resp.status_code >= 300:
                    logger.error(
                        "Twilio call creation failed: status=%d",
                        resp.status_code,
                    )
                    raise HTTPException(
                        min(resp.status_code, 502),
                        f"Twilio call creation failed (status {resp.status_code}). Check provider credentials and account status.",
                    )

                return CreatedCall.model_validate_json(resp.content)
            except httpx.RequestError:
                logger.warning("Twilio call creation transport failed")
                raise HTTPException(
                    status_code=502,
                    detail="Unable to reach Twilio. Please try again.",
                )

    async def end_call(self, call_sid: str) -> TelephonyControlResult:
        """Terminate an active call.

        Args:
            call_sid: The Twilio Call SID to terminate.

        Returns:
            The JSON response from the Twilio API.

        Raises:
            HTTPException: If the API call to Twilio fails.

        """
        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS) as client:
            url = f"{self.base_url}/Calls/{call_sid}.json"
            try:
                resp = await client.post(
                    url,
                    data=EndCallRequest().model_dump(mode="json", by_alias=True),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if resp.status_code >= 300:
                    return classify_control_failure(
                        HTTPException(status_code=resp.status_code),
                        operation=TelephonyControlOperation.END,
                    )

                return TelephonyControlAccepted(status_code=resp.status_code)
            except httpx.RequestError:
                logger.warning("Twilio call end outcome is unconfirmed")
                return TelephonyControlUnknown(
                    failure_code=TelephonyControlFailureCode.END_UNCONFIRMED
                )

    async def transfer_call(
        self,
        call_sid: str,
        to_number: str,
    ) -> TelephonyControlResult:
        """Transfer an active call to another number using TwiML update.

        Args:
            call_sid: The Twilio Call SID to transfer.
            to_number: Destination phone number in E.164 format.

        Returns:
            The JSON response from the Twilio API.

        """
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Dial>{xml_escape(to_number)}</Dial>
</Response>"""

        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS) as client:
            url = f"{self.base_url}/Calls/{call_sid}.json"
            try:
                resp = await client.post(
                    url,
                    data=TwimlUpdateRequest(twiml=twiml).model_dump(
                        mode="json", by_alias=True
                    ),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if resp.status_code >= 300:
                    return classify_control_failure(
                        HTTPException(status_code=resp.status_code),
                        operation=TelephonyControlOperation.TRANSFER,
                    )

                return TelephonyControlAccepted(status_code=resp.status_code)
            except httpx.RequestError:
                logger.warning("Twilio call transfer outcome is unconfirmed")
                return TelephonyControlUnknown(
                    failure_code=TelephonyControlFailureCode.TRANSFER_UNCONFIRMED
                )

    async def send_dtmf(
        self,
        call_sid: str,
        digits: str,
    ) -> TelephonyControlResult:
        """Send DTMF tones on an active call using TwiML update.

        Args:
            call_sid: The Twilio Call SID.
            digits: DTMF digits to send (0-9, *, #, w for 0.5s pause).

        Returns:
            The JSON response from the Twilio API.

        """
        if not re.match(r"^[0-9*#wW]+$", digits):
            raise ValueError("Invalid DTMF digit sequence")
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Play digits="{xml_escape(digits)}"/>
</Response>"""

        async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS) as client:
            url = f"{self.base_url}/Calls/{call_sid}.json"
            try:
                resp = await client.post(
                    url,
                    data=TwimlUpdateRequest(twiml=twiml).model_dump(
                        mode="json", by_alias=True
                    ),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if resp.status_code >= 300:
                    return classify_control_failure(
                        HTTPException(status_code=resp.status_code),
                        operation=TelephonyControlOperation.DTMF,
                    )

                return TelephonyControlAccepted(status_code=resp.status_code)
            except httpx.RequestError:
                logger.warning("Twilio DTMF outcome is unconfirmed")
                return TelephonyControlUnknown(
                    failure_code=TelephonyControlFailureCode.DTMF_UNCONFIRMED
                )

    async def search_available_numbers(
        self,
        country: str,
        number_type: NumberType = NumberType.LOCAL,
        area_code: str | None = None,
        contains: str | None = None,
        limit: int = NUMBER_SEARCH_DEFAULT_LIMIT,
    ) -> list[AvailableNumber]:
        """Search for available phone numbers to purchase.

        Args:
            country: ISO 3166-1 alpha-2 country code (e.g. "US", "GB").
            number_type: One of "Local", "TollFree", "Mobile".
            area_code: Optional area code filter.
            contains: Optional pattern the number should contain.
            limit: Max results to return (1-30).

        Returns:
            List of available number dicts from Twilio.

        """
        request = NumberSearchRequest(
            page_size=min(limit, NUMBER_SEARCH_MAX_LIMIT),
            area_code=area_code or None,
            contains=contains or None,
        )

        url = f"{self.base_url}/AvailablePhoneNumbers/{country}/{number_type}.json"

        async with httpx.AsyncClient(timeout=NUMBER_SEARCH_TIMEOUT_SECONDS) as client:
            try:
                resp = await client.get(
                    url,
                    params=request.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    headers={"Authorization": self._auth_header},
                )

                if resp.status_code >= 300:
                    logger.error(
                        "Twilio number search failed: status=%d", resp.status_code
                    )
                    raise HTTPException(
                        min(resp.status_code, 502),
                        f"Twilio search failed (status {resp.status_code}). Check provider credentials and account status.",
                    )

                try:
                    response = AvailableNumbersResponse.model_validate_json(
                        resp.content
                    )
                except ValidationError:
                    raise HTTPException(
                        HTTPStatus.BAD_GATEWAY,
                        "Twilio returned an invalid available-number response.",
                    ) from None
                return response.available_phone_numbers
            except httpx.RequestError:
                logger.warning("Twilio number search transport failed")
                raise HTTPException(
                    status_code=502,
                    detail="Unable to reach Twilio. Please try again.",
                )

    def purchase_profile(self) -> TelephonyOperationProfile:
        return number_purchase_profile("twilio", "https://api.twilio.com")

    async def purchase_number(
        self,
        phone_number: str,
        *,
        authorization: OutboundSendAuthorization,
        country: str | None = None,
    ) -> OutboundSendOutcome:
        """Purchase (provision) a phone number on Twilio.

        Args:
            phone_number: E.164 phone number to purchase.

        Returns:
            The JSON response from the Twilio IncomingPhoneNumbers API.

        """
        del authorization, country
        request = NumberPurchaseRequest(phone_number=phone_number)
        async with httpx.AsyncClient(timeout=NUMBER_PURCHASE_TIMEOUT_SECONDS) as client:
            url = f"{self.base_url}/IncomingPhoneNumbers.json"
            try:
                resp = await client.post(
                    url,
                    data=request.model_dump(mode="json", by_alias=True),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if resp.status_code >= 300:
                    return classify_number_purchase_status(resp.status_code)
                try:
                    purchased = PurchasedNumber.model_validate_json(resp.content)
                except ValidationError:
                    return OutboundSendUnknown(
                        failure_code=NumberFailureCode.RESPONSE_INVALID,
                        status_code=resp.status_code,
                    )
                if (
                    purchased.phone_number is not None
                    and purchased.phone_number != phone_number
                ):
                    return OutboundSendUnknown(
                        failure_code=NumberFailureCode.IDENTITY_MISMATCH,
                        status_code=resp.status_code,
                    )
                reference = purchased.sid.strip()
                if len(reference) > OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH:
                    return OutboundSendUnknown(
                        failure_code=NumberFailureCode.RESPONSE_INVALID,
                        status_code=resp.status_code,
                    )
                return OutboundSendSucceeded(
                    provider_reference=reference,
                    status_code=resp.status_code,
                )
            except httpx.RequestError:
                return number_purchase_transport_unknown("Twilio")
