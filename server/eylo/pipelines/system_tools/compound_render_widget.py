"""Validate generated widgets and persist conversation messages transactionally."""

import logging
from datetime import UTC, datetime

from pydantic import JsonValue, ValidationError

from eylo.common.contracts.conversation import WIDGET_TOOL_PREFIX
from eylo.common.contracts.tool_metadata import ToolFunctionMetadata, set_tool_metadata
from eylo.common.database import current_transaction, start_transaction
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.message_content import (
    WidgetMessageContent,
)
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageCreate,
    MessageKind,
)
from eylo.modules.conversations.services.messages import MessageService
from eylo.modules.interfaces.schemas.tools import (
    CompoundRenderWidgetInput,
    WidgetDeliveryReceipt,
    WidgetDeliveryStatus,
)
from eylo.modules.interfaces.services.schema_validator import (
    CompoundWidgetSchemaValidatorService,
)
from eylo.pipelines.agent_execution_context import PlatformExecutionContext

logger = logging.getLogger(__name__)


def compound_widget_text_fallback(reason: str) -> str:
    """Tell the model to stop retrying and answer in text."""
    return (
        "Compound widget rendering could not be completed. "
        f"Reason: {reason} "
        f"Do not call `{WIDGET_TOOL_PREFIX}` again for this turn. "
        "Reply to the user in normal plain text instead."
    )


async def compound_render_widget(
    components: list[dict[str, JsonValue]],
    root: str | None = None,
    *,
    ctx: PlatformExecutionContext,
) -> str | dict[str, JsonValue]:
    """Render a compound layout of UI components in the user's chat widget.

    Use for collecting structured input and presenting interactive cards,
    alerts, progress, or compact titled layouts that Markdown cannot express.
    Use normal Markdown for prose, headings, lists, code, images, and tables.
    """
    if not isinstance(ctx, ConversationContext) or not ctx.widget_interfaces_enabled:
        return compound_widget_text_fallback(
            "Interactive widgets are unavailable in this conversation."
        )

    try:
        request = CompoundRenderWidgetInput.model_validate(
            {"components": components, "root": root}
        )
        validated = CompoundWidgetSchemaValidatorService().validate_compound_payload(
            request.model_dump(mode="json")
        )
    except (ValueError, TypeError, ValidationError) as error:
        logger.warning(
            "Widget input rejected conversation=%s error_type=%s",
            ctx.conversation.id,
            type(error).__name__,
        )
        return compound_widget_text_fallback(
            "Widget input was invalid. Reply in plain text instead."
        )

    participant = ctx.get_primary_agent()
    if participant is None:
        return compound_widget_text_fallback(
            "No primary agent participant is available for widget delivery."
        )
    latest_user_message = next(
        (
            message
            for message in reversed(ctx.messages or [])
            if message.kind is MessageKind.USER
        ),
        None,
    )
    message = MessageCreate(
        conversation_id=ctx.conversation.id,
        sender_participant_id=participant.id,
        kind=MessageKind.ASSISTANT,
        content_kind=MessageContentKind.WIDGET,
        content=WidgetMessageContent(content=validated),
        parent_message_id=latest_user_message.id if latest_user_message else None,
        request_id=latest_user_message.request_id if latest_user_message else None,
        created_at=datetime.now(UTC),
        meta={
            "role": MessageKind.ASSISTANT.value.lower(),
            "tool_name": WIDGET_TOOL_PREFIX,
            "message": {
                "content": [
                    {
                        "kind": MessageContentKind.WIDGET.value,
                        "value": validated.model_dump(),
                    }
                ]
            },
        },
    )

    # Borrow a caller's transaction without committing or closing it. Otherwise
    # own only the DB write, after validation. The service emits after commit.
    session = current_transaction()
    if session is None:
        async with start_transaction() as session:
            persisted = await MessageService(session).create_(message)
    else:
        persisted = await MessageService(session).create_(message)

    logger.info(
        "Widget message filed conversation=%s message=%s",
        ctx.conversation.id,
        persisted.id,
    )

    # Do not append uncommitted rows to caller-owned history. Text execution ends
    # with this artifact; the next context read hydrates authoritative DB messages.
    return WidgetDeliveryReceipt(
        status=WidgetDeliveryStatus.DELIVERED,
        widget_message_id=persisted.id,
        root=validated.root,
    ).model_dump(mode="json")


# The registry inspects this documented function-metadata extension. Keep the
# real function (not a callable wrapper) and validate its schema at registration.
set_tool_metadata(
    compound_render_widget,
    ToolFunctionMetadata(input_schema=CompoundRenderWidgetInput),
)
