"""Project split model-response rows into a valid tool exchange for vendor history."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from eylo.common.contracts.messages import MessageInDb, MessageKind


class _ResponseIdentity(BaseModel):
    """Read only the identity from a producer-owned response snapshot."""

    model_config = ConfigDict(extra="ignore", frozen=True, from_attributes=True)

    id: StrictStr = Field(min_length=1, pattern=r"\S")


class _MessageResponseIdentity(BaseModel):
    """Subset projection, not a competing definition of response content."""

    model_config = ConfigDict(extra="ignore", frozen=True, from_attributes=True)

    framework: Literal[True]
    model_response: _ResponseIdentity
    response_block_index: int = Field(ge=0, strict=True)


class _ResponseOwner(BaseModel):
    """Response identity is local to a conversation, request and speaker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: UUID
    request_id: UUID
    sender_participant_id: UUID
    response_id: str


def _response_owner(message: MessageInDb) -> _ResponseOwner | None:
    if message.meta is None or message.request_id is None:
        return None
    try:
        identity = _MessageResponseIdentity.model_validate(message.meta)
    except ValidationError:
        return None
    return _ResponseOwner(
        conversation_id=message.conversation_id,
        request_id=message.request_id,
        sender_participant_id=message.sender_participant_id,
        response_id=identity.model_response.id,
    )


def order_model_response_history(messages: Sequence[MessageInDb]) -> list[MessageInDb]:
    """Defer same-response text until pending tool results, without changing rows.

    The platform can file text following a tool block before that tool executes.
    That is still one assistant response, not an abandoned command. Vendor
    history must keep calls/results adjacent. Unrelated or unidentified messages
    retain their order; the existing sequence validator still rejects incomplete,
    duplicate or orphaned exchanges. Work is linear in rows and result entries.
    """
    ordered: list[MessageInDb] = []
    deferred: list[MessageInDb] = []
    pending: set[str] = set()
    owner: _ResponseOwner | None = None

    for message in messages:
        identity = _response_owner(message)
        if message.kind is MessageKind.ASSISTANT and pending and identity == owner:
            deferred.append(message)
            continue

        if message.kind is MessageKind.TOOL_USE and identity is not None:
            if identity != owner:
                ordered.extend(deferred)
                deferred.clear()
                pending.clear()
            owner = identity
            pending.add(message.get_tool_use_content().content.id)
        elif (
            message.kind is MessageKind.TOOL_RESULT
            and owner is not None
            and message.conversation_id == owner.conversation_id
            and message.request_id == owner.request_id
        ):
            results = message.get_tool_result_content().content or ()
            result_ids = [result.tool_use_id for result in results]
            if (
                result_ids
                and len(set(result_ids)) == len(result_ids)
                and set(result_ids) <= pending
            ):
                pending.difference_update(result_ids)
            else:
                ordered.extend(deferred)
                deferred.clear()
                pending.clear()
                owner = None
        else:
            ordered.extend(deferred)
            deferred.clear()
            pending.clear()
            owner = None

        ordered.append(message)
        if not pending:
            ordered.extend(deferred)
            deferred.clear()
            owner = None

    ordered.extend(deferred)
    return ordered
