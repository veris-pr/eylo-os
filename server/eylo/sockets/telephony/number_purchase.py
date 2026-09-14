"""Shared safe result contract for charged carrier number purchases."""

import logging
from enum import StrEnum
from typing import Protocol

from eylo.common.outbound import (
    OutboundSendAuthorization,
    OutboundSendOutcome,
    OutboundSendUnknown,
    OutboundTransportKind,
)
from eylo.sockets.telephony.base import (
    TelephonyOperationCapabilities,
    TelephonyOperationProfile,
    TelephonyOperationSupport,
    classify_provider_failure,
)

logger = logging.getLogger(__name__)


class NumberPurchaseFailureCode(StrEnum):
    RESPONSE_INVALID = "number_purchase_response_invalid"
    IDENTITY_MISMATCH = "number_purchase_identity_mismatch"
    COUNTRY_REQUIRED = "number_purchase_country_required"
    REJECTED = "number_purchase_rejected"
    UNCONFIRMED = "number_purchase_unconfirmed"


class NumberPurchaseClient(Protocol):
    """One exact charged number-purchase adapter."""

    def purchase_profile(self) -> TelephonyOperationProfile: ...

    async def purchase_number(
        self,
        phone_number: str,
        *,
        authorization: OutboundSendAuthorization,
        country: str | None = None,
    ) -> OutboundSendOutcome: ...


class _ProviderStatusError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Provider request failed with status {status_code}.")


def number_purchase_profile(
    provider: str,
    destination_origin: str,
) -> TelephonyOperationProfile:
    return TelephonyOperationProfile(
        provider_operation=f"{provider}.phone_number.purchase",
        transport_kind=OutboundTransportKind.HTTP,
        destination_origin=destination_origin,
        capabilities=TelephonyOperationCapabilities(
            provider_idempotency=TelephonyOperationSupport.UNSUPPORTED,
            reconciliation=TelephonyOperationSupport.UNSUPPORTED,
        ),
    )


def classify_number_purchase_status(status_code: int) -> OutboundSendOutcome:
    return classify_provider_failure(
        _ProviderStatusError(status_code),
        operation="number_purchase",
    )


def number_purchase_transport_unknown(provider: str) -> OutboundSendUnknown:
    logger.warning("%s number purchase transport failed", provider)
    return OutboundSendUnknown(failure_code=NumberPurchaseFailureCode.UNCONFIRMED)


__all__ = [
    "NumberPurchaseClient",
    "classify_number_purchase_status",
    "number_purchase_profile",
    "number_purchase_transport_unknown",
]
