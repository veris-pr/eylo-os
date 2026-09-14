"""Decode Redis transport values before interpreting conversation ownership."""

from enum import IntEnum

from pydantic import StrictInt, TypeAdapter, field_validator

from eylo.modules.conversations.schemas.runtime_status import (
    ConversationRuntimeClaimResult,
    ConversationRuntimeReleaseDecision,
    ConversationRuntimeStatus,
)

_STATUS_HASH = TypeAdapter(dict[str, str])
_CLAIM_REPLY = TypeAdapter(tuple[StrictInt, StrictInt, str, str])
_INTEGER_REPLY = TypeAdapter(StrictInt)


class RuntimeOwnershipReply(IntEnum):
    REFUSED = 0
    ACCEPTED = 1


class RuntimeDrainReply(IntEnum):
    LOST = -1
    RELEASED = 0
    CONTINUE = 1


class _StoredRuntimeStatus(ConversationRuntimeStatus):
    """Storage-only empty-string conventions; public status keeps native types."""

    @field_validator(
        "active_request_id",
        "active_user_message_id",
        "last_enqueued_request_id",
        "last_enqueued_user_message_id",
        "heartbeat_epoch",
        "expires_epoch",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("pending_count", mode="before")
    @classmethod
    def empty_count_to_zero(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Redis pending count must be text.")
        return int(value or 0)

    @field_validator("wake_requested", mode="before")
    @classmethod
    def decode_wake(cls, value: object) -> bool:
        if value not in {"0", "1"}:
            raise ValueError("Redis wake flag must be 0 or 1.")
        return value == "1"


def decode_status_hash(value: object) -> ConversationRuntimeStatus:
    """Validate a flat Redis hash, retaining the existing absent/empty field rules."""
    return _StoredRuntimeStatus.model_validate(_STATUS_HASH.validate_python(value))


def decode_ownership_reply(value: object) -> bool:
    """Only the Lua script's integer success code proves ownership."""
    return (
        RuntimeOwnershipReply(_INTEGER_REPLY.validate_python(value))
        is RuntimeOwnershipReply.ACCEPTED
    )


def decode_claim_reply(value: object) -> ConversationRuntimeClaimResult:
    """Lua always returns four values; incomplete/unknown replies fail closed."""
    acquired, stale_takeover, request_id, user_message_id = (
        _CLAIM_REPLY.validate_python(value)
    )
    return ConversationRuntimeClaimResult(
        acquired=decode_ownership_reply(acquired),
        stale_takeover=decode_ownership_reply(stale_takeover),
        previous_active_request_id=request_id or None,
        previous_active_user_message_id=user_message_id or None,
    )


def decode_drain_reply(value: object) -> ConversationRuntimeReleaseDecision:
    reply = RuntimeDrainReply(_INTEGER_REPLY.validate_python(value))
    if reply is RuntimeDrainReply.CONTINUE:
        return ConversationRuntimeReleaseDecision.CONTINUE
    if reply is RuntimeDrainReply.RELEASED:
        return ConversationRuntimeReleaseDecision.RELEASED
    return ConversationRuntimeReleaseDecision.LOST
