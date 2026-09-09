"""Constants for the telephony module."""

from enum import StrEnum
from typing import Literal

APP_DB_PREFIX = "telephony_"
APP_TAG = "Telephony"
OUTBOUND_CALL_REJECTED = "provider_rejected"


class CallInitiationMarker(StrEnum):
    """Eylo's interim provider-status markers before carrier callbacks arrive.

    The provider-status column also holds native carrier values; it is not a
    closed enum column. These markers belong only to initiation and recovery.
    """

    ACCEPTED = "accepted"
    RETRYABLE = "retryable"
    UNKNOWN = "initiation-unknown"
    REJECTED = "rejected"


class CallOpenerDeliveryStatus(StrEnum):
    """Delivery of the configured opener, independent of carrier call status."""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    ACCEPTED = "accepted"
    FAILED = "failed"


CallOpenerDeliveryOutcome = Literal[
    CallOpenerDeliveryStatus.ACCEPTED,
    CallOpenerDeliveryStatus.FAILED,
]


class CallTransferStatus(StrEnum):
    """Platform transfer intent and observed outcome, not vendor-native status."""

    NONE = "none"
    TRANSFERRING = "transferring"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TRANSFERRED = "transferred"


CallTransferOutcome = Literal[
    CallTransferStatus.ACCEPTED,
    CallTransferStatus.FAILED,
    CallTransferStatus.UNKNOWN,
]
