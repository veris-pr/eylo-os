"""Title generation.

Generates a conversation title by invoking an LLM and updates the conversation
record, with fallbacks when LLM-based generation is not possible.

Runs as a background agent implementation, dispatched only where an operator
attached it. It used to be triggered by an event emitted on every user message;
that fan-out is gone.
"""

import logging
from typing import Final, Optional

from eylo.common.contracts.background_task import BackgroundTaskOutcome
from eylo.common.database import start_transaction
from eylo.common.instrumentation import traced_agent
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.messages import MessageKind
from eylo.modules.conversations.services.conversations import (
    ConversationService,
)
from eylo.modules.llm_configs.domain import LLMOverrides

from ..framework_prompt import resolve_background_agent
from .prompt import (
    build_title_generation_prompt,
)
from .utils import (
    call_llm_for_title_generation,
    ensure_title_max_length,
)

logger = logging.getLogger(__name__)

TITLE_MINIMUM_MESSAGES: Final = 5
TITLE_GENERATION_OVERRIDES: Final = LLMOverrides(max_tokens=30, temperature=0.3)


@traced_agent("title_generator")
async def process_title_generation_request(
    ctx: ConversationContext,
    agent: AgentInDb,
) -> BackgroundTaskOutcome:
    """Generate through the executing background agent's pinned LLM config.

    Conversation history is the input, not authority to choose another agent's
    provider. Read resolution and title persistence own short transactions;
    inference occurs between them. Cancellation propagates.
    """
    conversation = ctx.conversation
    if (
        len(ctx.filter_messages()) < TITLE_MINIMUM_MESSAGES
        or conversation.has_triggered_title_generation
    ):
        return BackgroundTaskOutcome.SKIPPED

    message_content = await _get_message_content_for_title_generation(ctx)
    if not message_content:
        return BackgroundTaskOutcome.SKIPPED
    try:
        prompt = build_title_generation_prompt(message_content)
        async with start_transaction(ro=True):
            resolved = await resolve_background_agent(
                agent,
                generation_overrides=TITLE_GENERATION_OVERRIDES,
            )
        generated_title = await call_llm_for_title_generation(
            prompt,
            agent,
            resolved,
            conversation.id,
        )
        if not generated_title or not generated_title.strip():
            return BackgroundTaskOutcome.SKIPPED
        title = ensure_title_max_length(generated_title, str(conversation.id))
        async with start_transaction():
            await ConversationService().update_title(
                conversation_id=conversation.id,
                title=title,
            )
        return BackgroundTaskOutcome.COMPLETED
    except Exception as error:
        logger.error(
            "LLM title generation failed conversation=%s error_type=%s",
            conversation.id,
            type(error).__name__,
        )
        return BackgroundTaskOutcome.SKIPPED


async def _get_message_content_for_title_generation(
    ctx: ConversationContext,
) -> Optional[str]:
    """Extract message content for title generation.

    Uses the common get_text_content() method to extract text from all message types.
    """
    # Filter to only USER and ASSISTANT messages
    messages = ctx.filter_messages([MessageKind.USER, MessageKind.ASSISTANT])

    if not messages:
        return None

    message_lines = []
    for message in messages:
        # Use the common text extraction method
        text = message.get_text_content()

        if text:
            # Format as "role: content"
            message_lines.append(f"{message.kind.name}: {text}")

    if not message_lines:
        return None

    return "\n".join(message_lines)
