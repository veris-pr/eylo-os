"""Constants for the telephony module."""

from enum import StrEnum
from typing import Literal

APP_DB_PREFIX = "telephony_"
APP_TAG = "Telephony"
OUTBOUND_CALL_REJECTED = "provider_rejected"
OUTBOUND_CALL_OPERATION = "telephony.call.create"
CALL_IDEMPOTENCY_KEY_MAX_LENGTH = 255
NUMBER_PURCHASE_OPERATION = "telephony.number.purchase"
NUMBER_PURCHASE_IDEMPOTENCY_KEY_MAX_LENGTH = 255
NUMBER_PURCHASE_RETRY_AFTER_SECONDS = 5


class CallControlStatus(StrEnum):
    """A submitted control is accepted, not proof of the call's final state."""

    ACCEPTED = "accepted"


class CallControlFailureCode(StrEnum):
    """Platform control refusals, distinct from carrier-native failure codes."""

    UNSUPPORTED = "UNSUPPORTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


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
