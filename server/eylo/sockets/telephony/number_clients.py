"""Carrier adapters for searching and purchasing phone numbers.

Each client follows the same pattern as TwilioRestClient: async httpx calls
with per-org credentials passed at construction time.
"""

import base64
import logging
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from eylo.common.outbound import (
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendSucceeded,
    OutboundSendTerminal,
    OutboundSendUnknown,
)
from eylo.sockets.telephony.base import TelephonyOperationProfile
from eylo.sockets.telephony.exotel import number_contracts as exotel_wire
from eylo.sockets.telephony.number_purchase import (
    NumberPurchaseFailureCode,
    classify_number_purchase_status,
    number_purchase_profile,
    number_purchase_transport_unknown,
)
from eylo.sockets.telephony.plivo import number_contracts as plivo_wire
from eylo.sockets.telephony.vonage import number_contracts as vonage_wire

logger = logging.getLogger(__name__)


def _provider_error(
    provider: str,
    operation: str,
    status_code: int,
) -> HTTPException:
    """Keep provider response content out of logs and user-facing errors."""
    logger.error("%s %s error: status=%d", provider, operation, status_code)
    return HTTPException(
        status_code=min(status_code, 502),
        detail=f"{provider} {operation} failed (status {status_code}). Check provider credentials and account status.",
    )


class PlivoNumberClient:
    """Client for Plivo phone number search and purchase APIs.

    Plivo docs: https://www.plivo.com/docs/phone-numbers/api/phone-number/

    Args:
        auth_id: Plivo Auth ID.
        auth_token: Plivo Auth Token.

    """

    def __init__(self, auth_id: str, auth_token: str) -> None:
        self.auth_id = auth_id
        self.auth_token = auth_token
        self.base_url = (
            f"{plivo_wire.NUMBER_ORIGIN}/v1/Account/{quote(auth_id, safe='')}"
        )
        auth_str = f"{auth_id}:{auth_token}".encode()
        self._auth_header = f"Basic {base64.b64encode(auth_str).decode()}"

    async def search_available_numbers(
        self,
        country: str,
        number_type: plivo_wire.NumberType = plivo_wire.NumberType.LOCAL,
        pattern: str | None = None,
        limit: int = plivo_wire.SEARCH_LIMIT,
    ) -> list[plivo_wire.AvailableNumber]:
        """Search available phone numbers on Plivo.

        Args:
            country: ISO 3166-1 alpha-2 country code.
            number_type: One of "local", "tollfree", "national".
            pattern: Optional area code or digit pattern.
            limit: Max results (1-20).

        """
        request = plivo_wire.SearchRequest(
            country_iso=country.upper(),
            type=number_type,
            limit=min(limit, plivo_wire.SEARCH_LIMIT),
            pattern=pattern or None,
        )

        async with httpx.AsyncClient(
            timeout=plivo_wire.SEARCH_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/PhoneNumber/",
                    params=request.model_dump(mode="json", exclude_none=True),
                    headers={"Authorization": self._auth_header},
                )
                if resp.status_code >= 300:
                    raise _provider_error("Plivo", "search", resp.status_code)

                try:
                    return plivo_wire.SearchResponse.model_validate_json(
                        resp.content
                    ).objects
                except ValidationError:
                    raise HTTPException(
                        502, "Plivo returned an invalid available-number response."
                    ) from None
            except httpx.RequestError:
                logger.warning("Plivo number search transport failed")
                raise HTTPException(502, "Unable to reach Plivo. Please try again.")

    def purchase_profile(self) -> TelephonyOperationProfile:
        return number_purchase_profile("plivo", plivo_wire.NUMBER_ORIGIN)

    async def purchase_number(
        self,
        phone_number: str,
        *,
        authorization: OutboundSendAuthorization,
        country: str | None = None,
    ) -> OutboundSendOutcome:
        """Purchase a phone number on Plivo.

        Args:
            phone_number: E.164 phone number (the '+' prefix is stripped for Plivo).

        """
        del authorization, country
        number = phone_number.lstrip("+")

        async with httpx.AsyncClient(
            timeout=plivo_wire.PURCHASE_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/PhoneNumber/{quote(number, safe='')}/",
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code >= 300:
                    return classify_number_purchase_status(resp.status_code)
                try:
                    purchased = plivo_wire.ConfirmedPurchase.model_validate_json(
                        resp.content
                    )
                except ValidationError:
                    return OutboundSendUnknown(
                        failure_code=NumberPurchaseFailureCode.RESPONSE_INVALID,
                        status_code=resp.status_code,
                    )
                if purchased.numbers[0].number.lstrip("+") != number:
                    return OutboundSendUnknown(
                        failure_code=NumberPurchaseFailureCode.IDENTITY_MISMATCH,
                        status_code=resp.status_code,
                    )
                return OutboundSendSucceeded(
                    provider_reference=purchased.api_id.strip(),
                    status_code=resp.status_code,
                )
            except httpx.RequestError:
                return number_purchase_transport_unknown("Plivo")


class VonageNumberClient:
    """Client for Vonage number search and purchase APIs.

    Uses the REST API with api_key/api_secret authentication.
    Vonage docs: https://developer.vonage.com/en/api/numbers

    Args:
        api_key: Vonage API Key.
        api_secret: Vonage API Secret.

    """

    BASE_URL = vonage_wire.NUMBER_ORIGIN

    def __init__(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    async def search_available_numbers(
        self,
        country: str,
        number_type: vonage_wire.NumberType = vonage_wire.NumberType.MOBILE,
        pattern: str | None = None,
        limit: int = vonage_wire.SEARCH_DEFAULT_LIMIT,
    ) -> list[vonage_wire.AvailableNumber]:
        """Search available phone numbers on Vonage.

        Args:
            country: ISO 3166-1 alpha-2 country code.
            number_type: One of "mobile", "landline", "landline-toll-free".
            pattern: Optional number pattern.
            limit: Max results.

        """
        request = vonage_wire.SearchRequest(
            api_key=self.api_key,
            api_secret=self.api_secret,
            country=country.upper(),
            type=number_type,
            size=min(limit, vonage_wire.SEARCH_MAX_LIMIT),
            pattern=pattern or None,
            search_pattern=vonage_wire.PatternMatch.CONTAINS if pattern else None,
        )

        async with httpx.AsyncClient(
            timeout=vonage_wire.SEARCH_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/number/search",
                    params=request.model_dump(mode="json", exclude_none=True),
                )
                if resp.status_code >= 300:
                    raise _provider_error("Vonage", "search", resp.status_code)

                try:
                    return vonage_wire.SearchResponse.model_validate_json(
                        resp.content
                    ).numbers
                except ValidationError:
                    raise HTTPException(
                        502, "Vonage returned an invalid available-number response."
                    ) from None
            except httpx.RequestError:
                logger.warning("Vonage number search transport failed")
                raise HTTPException(502, "Unable to reach Vonage. Please try again.")

    def purchase_profile(self) -> TelephonyOperationProfile:
        return number_purchase_profile("vonage", vonage_wire.NUMBER_ORIGIN)

    async def purchase_number(
        self,
        phone_number: str,
        *,
        authorization: OutboundSendAuthorization,
        country: str | None = None,
    ) -> OutboundSendOutcome:
        """Purchase a phone number on Vonage.

        Args:
            phone_number: The MSISDN (number without +).
            country: ISO 3166-1 alpha-2 country code.

        """
        del authorization
        if country is None:
            return OutboundSendTerminal(
                failure_code=NumberPurchaseFailureCode.COUNTRY_REQUIRED
            )
        msisdn = phone_number.lstrip("+")
        request = vonage_wire.PurchaseRequest(
            api_key=self.api_key,
            api_secret=self.api_secret,
            country=country.upper(),
            msisdn=msisdn,
        )

        async with httpx.AsyncClient(
            timeout=vonage_wire.PURCHASE_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.post(
                    f"{self.BASE_URL}/number/buy",
                    data=request.model_dump(mode="json"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code >= 300:
                    return classify_number_purchase_status(resp.status_code)
                try:
                    purchased = vonage_wire.PurchaseResponse.model_validate_json(
                        resp.content
                    )
                except ValidationError:
                    return OutboundSendUnknown(
                        failure_code=NumberPurchaseFailureCode.RESPONSE_INVALID,
                        status_code=resp.status_code,
                    )
                if purchased.error_code not in {
                    vonage_wire.PurchaseCode.SUCCESS,
                    vonage_wire.PurchaseCode.LEGACY_SUCCESS,
                }:
                    return OutboundSendTerminal(
                        failure_code=NumberPurchaseFailureCode.REJECTED,
                        status_code=resp.status_code,
                    )
                return OutboundSendSucceeded(
                    provider_reference=phone_number,
                    status_code=resp.status_code,
                )
            except httpx.RequestError:
                return number_purchase_transport_unknown("Vonage")


class ExotelNumberClient:
    """Client for Exotel virtual number search and purchase APIs.

    Uses Basic auth with api_key:api_token against the org's subdomain.
    Exotel docs: https://developer.exotel.com/api/exophones

    Args:
        api_key: Exotel API Key.
        api_token: Exotel API Token.
        account_sid: Exotel Account SID.
        subdomain: API subdomain (default: api.exotel.com).

    """

    def __init__(
        self,
        api_key: str,
        api_token: str,
        account_sid: str,
        subdomain: str = "api.exotel.com",
    ) -> None:
        _ALLOWED_EXOTEL_SUFFIXES = (".exotel.com", ".exotel.in")
        if not any(subdomain.endswith(s) for s in _ALLOWED_EXOTEL_SUFFIXES):
            raise ValueError(f"Invalid Exotel subdomain: {subdomain}")
        self.account_sid = account_sid
        self.base_url = f"https://{subdomain}/v2_beta/Accounts/{account_sid}"
        auth_str = f"{api_key}:{api_token}".encode()
        self._auth_header = f"Basic {base64.b64encode(auth_str).decode()}"

    async def search_available_numbers(
        self,
        country: str,
        number_type: exotel_wire.NumberType = exotel_wire.NumberType.LANDLINE,
        region: str | None = None,
        pattern: str | None = None,
        limit: int = exotel_wire.SEARCH_DEFAULT_LIMIT,
    ) -> list[exotel_wire.AvailableNumber]:
        """Search available ExoPhones by country and provider number type.

        Args:
            country: ISO 3166-1 alpha-2 country code.
            number_type: One of "Local", "TollFree", or "Mobile".
            region: Optional carrier region/circle filter.
            pattern: Optional number substring.
            limit: Maximum results returned to the caller.

        """
        request = exotel_wire.SearchRequest(
            region=region.upper() if region else None,
            contains=pattern or None,
        )

        async with httpx.AsyncClient(
            timeout=exotel_wire.SEARCH_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/AvailablePhoneNumbers/"
                    f"{country.upper()}/{number_type}",
                    params=request.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    headers={"Authorization": self._auth_header},
                )
                if resp.status_code >= 300:
                    raise _provider_error("Exotel", "search", resp.status_code)

                try:
                    numbers = exotel_wire.AVAILABLE_NUMBERS.validate_json(resp.content)
                except ValidationError:
                    raise HTTPException(
                        502,
                        "Exotel returned an invalid available-number response.",
                    ) from None
                return numbers[:limit]
            except httpx.RequestError:
                logger.warning("Exotel number search transport failed")
                raise HTTPException(502, "Unable to reach Exotel. Please try again.")

    def purchase_profile(self) -> TelephonyOperationProfile:
        return number_purchase_profile(
            "exotel",
            f"https://{self.base_url.split('/')[2]}",
        )

    async def purchase_number(
        self,
        phone_number: str,
        *,
        authorization: OutboundSendAuthorization,
        country: str | None = None,
    ) -> OutboundSendOutcome:
        """Purchase one exact available ExoPhone.

        Args:
            phone_number: The available ExoPhone selected by the user.

        """
        del authorization, country
        request = exotel_wire.PurchaseRequest(phone_number=phone_number)
        async with httpx.AsyncClient(
            timeout=exotel_wire.PURCHASE_TIMEOUT_SECONDS
        ) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/IncomingPhoneNumbers",
                    data=request.model_dump(mode="json", by_alias=True),
                    headers={
                        "Authorization": self._auth_header,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                if resp.status_code >= 300:
                    return classify_number_purchase_status(resp.status_code)
                try:
                    purchased = exotel_wire.PurchasedNumber.model_validate_json(
                        resp.content
                    )
                except ValidationError:
                    return OutboundSendUnknown(
                        failure_code=NumberPurchaseFailureCode.RESPONSE_INVALID,
                        status_code=resp.status_code,
                    )
                if purchased.phone_number.strip().removeprefix("+") != phone_number.removeprefix("+"):
                    return OutboundSendUnknown(
                        failure_code=NumberPurchaseFailureCode.IDENTITY_MISMATCH,
                        status_code=resp.status_code,
                    )
                return OutboundSendSucceeded(
                    provider_reference=purchased.sid.strip(),
                    status_code=resp.status_code,
                )
            except httpx.RequestError:
                return number_purchase_transport_unknown("Exotel")
