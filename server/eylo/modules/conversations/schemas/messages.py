"""Conversation-module exports for neutral persisted-message contracts."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from eylo.common.contracts.messages import (
    ConversationMessagesPaginated as ConversationMessagesPaginated,
)
from eylo.common.contracts.messages import (
    MessageApiResponseSchema as MessageApiResponseSchema,
)
from eylo.common.contracts.messages import (
    MessageContentKind as MessageContentKind,
)
from eylo.common.contracts.messages import (
    MessageContentType as MessageContentType,
)
from eylo.common.contracts.messages import (
    MessageCreate as MessageCreate,
)
from eylo.common.contracts.messages import (
    MessageInDb as MessageInDb,
)
from eylo.common.contracts.messages import (
    MessageKind as MessageKind,
)
from eylo.common.contracts.messages import (
    MessageMeta as MessageMeta,
)
from eylo.common.contracts.messages import (
    MessageModelSchema as MessageModelSchema,
)
from eylo.common.contracts.messages import (
    MessageRequestFeedback as MessageRequestFeedback,
)
from eylo.common.contracts.messages import (
    RequestStatus as RequestStatus,
)


class MessageUpdate(BaseModel):
    """Internal message changes; omitted fields do not clear persisted values.

    Conversation services retain authority, locking and transition ownership.
    This is not a public arbitrary-message-edit API.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_run_id: UUID | None = None
    request_status: RequestStatus | None = None
    request_feedback: MessageRequestFeedback | None = None
    meta: MessageMeta | None = None

    @field_validator("request_status", mode="before")
    @classmethod
    def validate_request_status(cls, value: object) -> RequestStatus | None:
        """Reuse the persisted-message check; legacy enum construction is permissive."""
        return MessageModelSchema.validate_request_status(value)

    @field_validator("request_feedback", mode="before")
    @classmethod
    def validate_request_feedback(cls, value: object) -> MessageRequestFeedback | None:
        return MessageModelSchema.validate_request_feedback(value)


__all__ = [
    "ConversationMessagesPaginated",
    "MessageApiResponseSchema",
    "MessageContentKind",
    "MessageContentType",
    "MessageCreate",
    "MessageInDb",
    "MessageKind",
    "MessageMeta",
    "MessageModelSchema",
    "MessageRequestFeedback",
    "MessageUpdate",
    "RequestStatus",
]
