"""Transient platform messages for non-conversation LLM loops."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from eylo.common.contracts.llm_response import (
    LLMContentBlock,
    LLMContentType,
    LLMResponse,
    LLMToolUseBlock,
)
from eylo.common.contracts.message_content import (
    AssistantMessageContent,
    TextContent,
    ToolResultContent,
    ToolResultMessageContent,
    ToolUseContent,
    ToolUseMessageContent,
    UserMessageContent,
)
from eylo.common.contracts.messages import (
    MessageContentKind,
    MessageInDb,
    MessageKind,
    MessageMeta,
)


def text_message(
    sender_id: UUID,
    conversation_id: UUID,
    kind: MessageKind,
    text: str,
    *,
    request_id: UUID | None = None,
    meta: MessageMeta | None = None,
) -> MessageInDb:
    """Build a transient USER or ASSISTANT message for adapter input."""
    created_at = datetime.now(UTC)
    content = (
        UserMessageContent(content=[TextContent(type="text", text=text)])
        if kind == MessageKind.USER
        else AssistantMessageContent(content=[TextContent(type="text", text=text)])
    )
    return MessageInDb(
        id=uuid4(),
        deleted=False,
        conversation_id=conversation_id,
        sender_participant_id=sender_id,
        kind=kind,
        content_kind=MessageContentKind.TEXT,
        content=content,
        request_id=request_id or uuid4(),
        meta=meta,
        created_at=created_at,
        updated_at=created_at,
    )


def text_parts(response_content: list[LLMContentBlock]) -> list[str]:
    return [
        block.content.text
        for block in response_content
        if block.type == LLMContentType.TEXT and block.content.text
    ]


def tool_uses(response_content: list[LLMContentBlock]) -> list[LLMToolUseBlock]:
    return [
        block.content
        for block in response_content
        if block.type == LLMContentType.TOOL_USE
    ]


def response_messages(
    *,
    sender_id: UUID,
    conversation_id: UUID,
    request_id: UUID,
    response: LLMResponse,
) -> list[MessageInDb]:
    """Retain response identity and block provenance across non-conversation turns."""
    messages: list[MessageInDb] = []
    for index, block in enumerate(response.content):
        meta = MessageMeta(
            llm_response=response.model_dump(mode="json"),
            response_block_index=index,
        )
        if block.type == LLMContentType.TEXT:
            text = block.content.text
            if text:
                messages.append(
                    text_message(
                        sender_id,
                        conversation_id,
                        MessageKind.ASSISTANT,
                        text,
                        request_id=request_id,
                        meta=meta,
                    )
                )
        elif block.type == LLMContentType.TOOL_USE:
            tool_use = block.content
            created_at = datetime.now(UTC)
            messages.append(
                MessageInDb(
                    id=uuid4(),
                    deleted=False,
                    conversation_id=conversation_id,
                    sender_participant_id=sender_id,
                    kind=MessageKind.TOOL_USE,
                    content_kind=MessageContentKind.TOOL,
                    content=ToolUseMessageContent(
                        content=ToolUseContent(
                            id=tool_use.id,
                            name=tool_use.name,
                            input=tool_use.input,
                        )
                    ),
                    request_id=request_id,
                    meta=meta,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
    return messages


def tool_result_messages(
    *,
    sender_id: UUID,
    conversation_id: UUID,
    request_id: UUID,
    calls: list[LLMToolUseBlock],
    results: Sequence[object],
) -> list[MessageInDb]:
    """Build transient tool-result messages paired to normalized calls."""
    messages: list[MessageInDb] = []
    for call, result in zip(calls, results):
        created_at = datetime.now(UTC)
        messages.append(
            MessageInDb(
                id=uuid4(),
                deleted=False,
                conversation_id=conversation_id,
                sender_participant_id=sender_id,
                kind=MessageKind.TOOL_RESULT,
                content_kind=MessageContentKind.TOOL,
                content=ToolResultMessageContent(
                    content=[
                        ToolResultContent(
                            tool_use_id=call.id,
                            name=call.name,
                            content=result,
                        )
                    ]
                ),
                request_id=request_id,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return messages
