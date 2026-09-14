"""Conversation WebSocket inputs, read receipts, and response routing projections."""

from typing import Optional
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    field_validator,
    model_validator,
)

from eylo.common.contracts.message_content import (
    WidgetResponseMessageContent,
    normalize_widget_response_message_content,
)
from eylo.common.contracts.websocket import WsConversationQueryFilters, WsEvent
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageRequestFeedback,
)


class WsConversationCreatedRef(BaseModel):
    """Read only routing identity; do not revalidate the full conversation view."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    id: UUID


class WsMessageConversationRef(BaseModel):
    """Read the public message's owner without rebuilding its content or HTML."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    conversation_id: UUID = Field(alias="conversationId")


class WsConversationReadReceipt(BaseModel):
    """Committed contact read state; snake-case keys are the existing wire contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    conversation_id: UUID
    last_read_at: AwareDatetime
    unread_count: StrictInt = Field(ge=0)


class WsMessageEvent(WsEvent):
    """Message event for sending text or data."""

    model_config = ConfigDict(allow_inf_nan=False)

    conversation_id: UUID
    content_kind: MessageContentKind = MessageContentKind.TEXT
    text: Optional[str] = None
    content: WidgetResponseMessageContent | None = None
    parent_message_id: Optional[UUID] = None
    context: dict[str, JsonValue] | None = None

    @field_validator("content", mode="before")
    @classmethod
    def parse_widget_response(
        cls, value: object
    ) -> WidgetResponseMessageContent | None:
        if value is None:
            return None
        return normalize_widget_response_message_content(value)

    @model_validator(mode="after")
    def validate_payload(self) -> "WsMessageEvent":
        if self.content_kind == MessageContentKind.TEXT:
            if self.text and self.text.strip():
                if self.content is not None:
                    raise ValueError("content must not be provided for TEXT messages")
                return self
            raise ValueError("text is required for TEXT messages")

        if self.content_kind == MessageContentKind.WIDGET_RESPONSE:
            if self.parent_message_id is None:
                raise ValueError(
                    "parentMessageId is required for WIDGET_RESPONSE messages"
                )
            if self.content is None:
                raise ValueError("content is required for WIDGET_RESPONSE messages")
            return self

        raise ValueError(
            f"Unsupported websocket message content kind: {self.content_kind}"
        )


class WsMessageFeedbackEvent(WsEvent):
    conversation_id: UUID
    message_request_id: UUID
    request_feedback: MessageRequestFeedback


class WsMessagesQueryFilters(WsConversationQueryFilters):
    """Filters for querying conversations."""

    message_ids: list[UUID] = Field(default_factory=list)


class WsMessageQueryEvent(WsEvent):
    """Event to query messages in a conversation."""

    filters: WsMessagesQueryFilters = Field(default_factory=WsMessagesQueryFilters)
