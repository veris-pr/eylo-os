"""Vendor-neutral identity and lifecycle vocabulary for external effects."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import ClassVar, Self, TypeAlias
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from eylo.common.identifiers import normalize_uuid_like

OUTBOUND_OPERATION_MAX_LENGTH = 192
OUTBOUND_FAILURE_CODE_MAX_LENGTH = 128
OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH = 320
OUTBOUND_DESTINATION_ORIGIN_MAX_LENGTH = 512
OUTBOUND_REQUEST_FINGERPRINT_LENGTH = 64
OUTBOUND_STATUS_CODE_MIN = 100
OUTBOUND_STATUS_CODE_MAX = 599

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]*$")
_FINGERPRINT = re.compile(rf"^[0-9a-f]{{{OUTBOUND_REQUEST_FINGERPRINT_LENGTH}}}$")
_ATTEMPT_NAMESPACE = uuid5(NAMESPACE_URL, "https://eylo.ai/outbound-attempt/v1")


class OutboundOwnerKind(StrEnum):
    """Stable product records that may own one external effect."""

    TOOL_CALL = "tool_call"
    CONVERSATION_MESSAGE = "conversation_message"
    CAMPAIGN_ATTEMPT = "campaign_attempt"
    VOICE_RECORDING = "voice_recording"
    TELEPHONY_CALL = "telephony_call"
    PHONE_NUMBER = "phone_number"
    TELEPHONY_OPERATION = "telephony_operation"
    WEBRTC_NEGOTIATION = "webrtc_negotiation"


class OutboundTransportKind(StrEnum):
    """Wire family used by an operation, not its product/provider identity."""

    HTTP = "http"
    PROVIDER_SDK = "provider_sdk"
    OBJECT_STORAGE = "object_storage"
    WEBSOCKET = "websocket"


class OutboundAttemptState(StrEnum):
    """Honest last-known state of one logical mutating external effect."""

    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


OUTBOUND_FINAL_STATES = frozenset(
    {
        OutboundAttemptState.SUCCEEDED,
        OutboundAttemptState.TERMINAL,
        OutboundAttemptState.CANCELLED,
    }
)


class OutboundAttemptError(Exception):
    """Base error for the shared external-effect boundary."""


class OutboundAttemptNotFound(OutboundAttemptError):
    """The attempt is absent from the caller's organization scope."""


class OutboundAttemptConflict(OutboundAttemptError):
    """A stable owner identity was reused for different effect input."""


class OutboundAttemptNotSendable(OutboundAttemptError):
    """Current durable state does not authorize another provider send."""


class OutboundAttemptReconciliationRequired(OutboundAttemptNotSendable):
    """A prior send is ambiguous and must not be repeated."""


class OutboundAttemptCancelled(OutboundAttemptNotSendable):
    """Cancellation fenced this effect before another send."""


class _FrozenOutboundModel(BaseModel):
    """Strict immutable values shared by effect owners and transport adapters."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class OutboundSendAuthorization(_FrozenOutboundModel):
    """The only stable attempt fields a socket needs to authorize one send."""

    attempt_id: UUID
    provider_idempotency_key: str

    @model_validator(mode="after")
    def validate_idempotency_key(self) -> Self:
        if self.provider_idempotency_key != f"eylo_{self.attempt_id.hex}":
            raise ValueError("Outbound provider idempotency key is not canonical.")
        return self


class _OutboundSendResult(_FrozenOutboundModel):
    """Bounded provider evidence, not raw responses or exception content."""

    provider_reference: str | None = None
    status_code: int | None = None

    @model_validator(mode="after")
    def validate_provider_evidence(self) -> Self:
        _validate_outcome_values(
            provider_reference=self.provider_reference,
            status_code=self.status_code,
        )
        return self


class OutboundSendSucceeded(_OutboundSendResult):
    """The provider accepted the requested effect."""

    state: ClassVar[OutboundAttemptState] = OutboundAttemptState.SUCCEEDED


class _OutboundSendFailure(_OutboundSendResult):
    """A normalized failure category owned by the calling adapter or product."""

    failure_code: str

    @field_validator("failure_code")
    @classmethod
    def validate_failure_code(cls, value: str) -> str:
        return require_failure_code(value)


class OutboundSendRetryable(_OutboundSendFailure):
    """The provider confirmed this exact send may be attempted again."""

    state: ClassVar[OutboundAttemptState] = OutboundAttemptState.RETRYABLE


class OutboundSendTerminal(_OutboundSendFailure):
    """The provider rejected the effect without safe retry."""

    state: ClassVar[OutboundAttemptState] = OutboundAttemptState.TERMINAL


class OutboundSendUnknown(_OutboundSendFailure):
    """The effect may have happened and requires provider reconciliation."""

    state: ClassVar[OutboundAttemptState] = OutboundAttemptState.UNKNOWN


OutboundSendOutcome: TypeAlias = (
    OutboundSendSucceeded
    | OutboundSendRetryable
    | OutboundSendTerminal
    | OutboundSendUnknown
)


class OutboundAttemptIdentity(_FrozenOutboundModel):
    """Deterministic identity under one organization-owned product record."""

    organization_id: UUID
    owner_kind: OutboundOwnerKind
    owner_id: UUID
    operation_key: str

    @field_validator("organization_id", "owner_id", mode="before")
    @classmethod
    def normalize_uuid_library(cls, value: object) -> object:
        return normalize_uuid_like(value)

    @field_validator("operation_key")
    @classmethod
    def validate_operation_key(cls, value: str) -> str:
        return _require_identifier(
            value,
            field="operation_key",
            max_length=OUTBOUND_OPERATION_MAX_LENGTH,
        )

    @property
    def attempt_id(self) -> UUID:
        seed = ":".join(
            (
                str(self.organization_id),
                self.owner_kind.value,
                str(self.owner_id),
                self.operation_key,
            )
        )
        return uuid5(_ATTEMPT_NAMESPACE, seed)

    @property
    def provider_idempotency_key(self) -> str:
        """Opaque stable value safe to send only through a declared provider slot."""
        return f"eylo_{self.attempt_id.hex}"


class OutboundAttemptSpec(_FrozenOutboundModel):
    """Immutable safe audit fields agreed before the first network send."""

    identity: OutboundAttemptIdentity
    provider_operation: str
    transport_kind: OutboundTransportKind
    destination_origin: str
    request_fingerprint: str

    @field_validator("provider_operation")
    @classmethod
    def validate_provider_operation(cls, value: str) -> str:
        return _require_identifier(
            value,
            field="provider_operation",
            max_length=OUTBOUND_OPERATION_MAX_LENGTH,
        )

    @field_validator("destination_origin")
    @classmethod
    def normalize_destination_origin(cls, value: str) -> str:
        origin = value.strip()
        if not origin or len(origin) > OUTBOUND_DESTINATION_ORIGIN_MAX_LENGTH:
            raise ValueError(
                "destination_origin must be a non-empty bounded normalized origin."
            )
        return origin

    @field_validator("request_fingerprint")
    @classmethod
    def validate_request_fingerprint(cls, value: str) -> str:
        if not _FINGERPRINT.fullmatch(value):
            raise ValueError(
                "request_fingerprint must be a lowercase SHA-256 hex value."
            )
        return value


def fingerprint_outbound_input(value: object) -> str:
    """Hash canonical JSON without retaining request content in the ledger."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Outbound fingerprint input must be canonical JSON."
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def require_failure_code(value: str) -> str:
    """Validate one allowlisted category, never arbitrary provider/error prose."""
    return _require_identifier(
        value,
        field="failure_code",
        max_length=OUTBOUND_FAILURE_CODE_MAX_LENGTH,
    )


def _validate_outcome_values(
    *,
    provider_reference: str | None,
    status_code: int | None,
) -> None:
    if provider_reference is not None:
        normalized = provider_reference.strip()
        if (
            not normalized
            or normalized != provider_reference
            or len(normalized) > OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH
        ):
            raise ValueError("provider_reference must be normalized and bounded.")
    if (
        status_code is not None
        and not OUTBOUND_STATUS_CODE_MIN <= status_code <= OUTBOUND_STATUS_CODE_MAX
    ):
        raise ValueError("status_code must be an HTTP status between 100 and 599.")


def _require_identifier(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > max_length
        or not _IDENTIFIER.fullmatch(normalized)
    ):
        raise ValueError(
            f"{field} must match {_IDENTIFIER.pattern!r} and be at most "
            f"{max_length} characters."
        )
    return normalized


__all__ = [
    "OUTBOUND_DESTINATION_ORIGIN_MAX_LENGTH",
    "OUTBOUND_FAILURE_CODE_MAX_LENGTH",
    "OUTBOUND_FINAL_STATES",
    "OUTBOUND_OPERATION_MAX_LENGTH",
    "OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH",
    "OUTBOUND_REQUEST_FINGERPRINT_LENGTH",
    "OUTBOUND_STATUS_CODE_MIN",
    "OUTBOUND_STATUS_CODE_MAX",
    "OutboundAttemptCancelled",
    "OutboundAttemptConflict",
    "OutboundAttemptError",
    "OutboundAttemptIdentity",
    "OutboundAttemptNotFound",
    "OutboundAttemptNotSendable",
    "OutboundAttemptReconciliationRequired",
    "OutboundAttemptSpec",
    "OutboundAttemptState",
    "OutboundOwnerKind",
    "OutboundSendAuthorization",
    "OutboundSendOutcome",
    "OutboundSendRetryable",
    "OutboundSendSucceeded",
    "OutboundSendTerminal",
    "OutboundSendUnknown",
    "OutboundTransportKind",
    "fingerprint_outbound_input",
    "require_failure_code",
]
