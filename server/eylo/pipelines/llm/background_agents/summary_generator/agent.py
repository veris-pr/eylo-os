"""Context Management Background Agent.

This agent monitors conversation token usage and proactively manages context
by summarizing old messages when approaching token limits. It runs in the
background and does not impact user-facing latency.

Trigger logic (see utils.context_management_trigger):
- **Token trigger**: token usage ≥ 70 % of model context window.
- **Group trigger**: ≥ 20 request groups since the last SYSTEM SUMMARY.
  A "request group" is the set of messages sharing the same request_id
  (one user turn + agent response + tool calls).
"""

import logging
from uuid import UUID

import arrow
from pydantic import BaseModel, ConfigDict, Field

from eylo.common.context_compaction import (
    ContextSummaryMetadata,
    compaction_meta,
    latest_context_compaction,
    ordered_messages,
    uncompacted_messages,
)
from eylo.common.contracts.background_task import BackgroundTaskOutcome
from eylo.common.database import start_transaction
from eylo.common.instrumentation import traced_agent
from eylo.modules.agents.schemas.indb import AgentInDb
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.conversations.schemas.message_content import SystemMessageContent
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageCreate,
    MessageInDb,
    MessageKind,
    MessageMeta,
)
from eylo.modules.conversations.services.messages import MessageService

from ..framework_prompt import resolve_background_agent
from .constants import (
    DEFAULT_GROUP_THRESHOLD,
    DEFAULT_RECENT_GROUPS,
    DEFAULT_TOKEN_THRESHOLD,
    SUMMARY_GENERATION_OVERRIDES,
    ContextManagementTrigger,
)
from .utils import (
    context_management_trigger,
    count_conversation_tokens,
    flatten_groups,
    get_max_tokens_for_model,
    group_messages_by_request,
    summarize_messages_with_llm,
)

logger = logging.getLogger(__name__)


class _CompactionSelection(BaseModel):
    """Selected live messages and cursor; never serialize their private contents."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    messages: tuple[MessageInDb, ...] = Field(min_length=1, repr=False, exclude=True)
    through: MessageInDb = Field(repr=False, exclude=True)
    previous_summary: MessageInDb | None = Field(repr=False, exclude=True)


@traced_agent("summary_generator")
async def process_context_management_request(
    ctx: ConversationContext,
    agent: AgentInDb,
) -> BackgroundTaskOutcome:
    """Compact conversation history using the executing background agent.

    The conversation agent defines the context window being measured; the
    dispatched background agent defines generation authority. Both configs are
    resolved in short read transactions. Inference runs outside transactions,
    then one write transaction stores the summary and its exact cursor.
    """
    conversation = ctx.conversation
    messages = ctx.messages or []
    if not messages:
        return BackgroundTaskOutcome.SKIPPED
    context_agent = ctx.primary_agent
    principal = ctx.get_primary_contact()
    if context_agent is None or principal is None:
        logger.warning(
            "Summary context lacks agent or contact conversation=%s", conversation.id
        )
        return BackgroundTaskOutcome.SKIPPED

    try:
        async with start_transaction(ro=True):
            context_llm = await resolve_background_agent(context_agent)
    except Exception as error:
        logger.error(
            "Could not resolve context LLM conversation=%s error_type=%s",
            conversation.id,
            type(error).__name__,
        )
        return BackgroundTaskOutcome.SKIPPED

    max_tokens = get_max_tokens_for_model(context_llm.generation.model)
    current_tokens = await count_conversation_tokens(ctx, context_llm)
    trigger = context_management_trigger(
        current_tokens=current_tokens,
        max_tokens=max_tokens,
        tokens_threshold=DEFAULT_TOKEN_THRESHOLD,
        messages=uncompacted_messages(messages),
        group_threshold=DEFAULT_GROUP_THRESHOLD,
    )
    if trigger is ContextManagementTrigger.NOT_REQUIRED:
        return BackgroundTaskOutcome.SKIPPED

    selection = _select_messages_to_summarize(messages, trigger)
    if selection is None:
        return BackgroundTaskOutcome.SKIPPED

    try:
        async with start_transaction(ro=True):
            resolved = await resolve_background_agent(
                agent,
                generation_overrides=SUMMARY_GENERATION_OVERRIDES,
            )
        summary = await summarize_messages_with_llm(
            messages=list(selection.messages),
            conversation_id=conversation.id,
            agent=agent,
            resolved=resolved,
            prior_summary=(
                None
                if selection.previous_summary is None
                else selection.previous_summary.get_text_content()
            ),
        )
        if not summary:
            return BackgroundTaskOutcome.SKIPPED
    except Exception as error:
        logger.error(
            "Generating summary failed conversation=%s error_type=%s",
            conversation.id,
            type(error).__name__,
        )
        return BackgroundTaskOutcome.SKIPPED

    async with start_transaction():
        await _create_context_summary_message(
            ctx,
            summary=summary,
            sender_participant_id=principal.id,
            original_token_count=current_tokens,
            selection=selection,
        )
    logger.info(
        "Context management completed conversation=%s trigger=%s",
        conversation.id,
        trigger.value,
    )
    return BackgroundTaskOutcome.COMPLETED


def _select_messages_to_summarize(
    messages: list[MessageInDb],
    trigger: ContextManagementTrigger,
) -> _CompactionSelection | None:
    """Return the subset of messages that should be fed to the summarizer.

    Both triggers keep complete recent request groups. A new summary is
    cumulative: it includes the previous summary plus only the newly compacted
    range, then advances an exact persisted message cursor.
    """
    if trigger not in {
        ContextManagementTrigger.TOKENS,
        ContextManagementTrigger.GROUPS,
    }:
        return None
    groups = group_messages_by_request(uncompacted_messages(messages))
    if len(groups) <= DEFAULT_RECENT_GROUPS:
        logger.info(
            "Not enough complete request groups to compact (%s <= %s).",
            len(groups),
            DEFAULT_RECENT_GROUPS,
        )
        return None
    selected = ordered_messages(flatten_groups(groups[:-DEFAULT_RECENT_GROUPS]))
    if not selected:
        return None
    compaction = latest_context_compaction(messages)
    return _CompactionSelection(
        messages=tuple(selected),
        through=selected[-1],
        previous_summary=None if compaction is None else compaction.summary,
    )


async def _create_context_summary_message(
    ctx: ConversationContext,
    summary: str,
    original_token_count: int,
    selection: _CompactionSelection,
    sender_participant_id: UUID,
) -> MessageInDb:
    """Persist summary text and a typed cursor inside the caller's transaction."""
    conversation_id = ctx.conversation.id

    payload = SystemMessageContent(content=summary)

    metadata = ContextSummaryMetadata(
        original_token_count=original_token_count,
        context_compaction=compaction_meta(
            through=selection.through,
            source_message_count=len(selection.messages),
            previous_summary_id=(
                None
                if selection.previous_summary is None
                else selection.previous_summary.id
            ),
        ),
    )
    message_create = MessageCreate(
        conversation_id=conversation_id,
        sender_participant_id=sender_participant_id,
        created_at=arrow.utcnow().datetime,
        kind=MessageKind.SYSTEM,
        content_kind=MessageContentKind.SUMMARY,
        content=payload,
        request_id=None,  # System messages don't have request IDs
        meta=MessageMeta.model_validate(metadata.model_dump(mode="json")),
    )

    message = await MessageService().create_(message_create)

    logger.info(
        f"Created context summary SYSTEM message {message.id} for conversation {conversation_id}"
    )

    return message
