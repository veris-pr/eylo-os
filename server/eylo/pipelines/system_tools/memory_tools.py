"""Agent Memory tools backed by exact runtime-derived ownership.

The model chooses only `agent`, `user`, or `conversation`. Organization and
subject IDs always come from the validated ConversationContext. Mutations name
the level again so a recalled ID cannot widen its own authority.
"""

from uuid import UUID

from pydantic import JsonValue

from eylo.common.contracts.memory import MemoryError, MemoryLevel
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.tools.services.executors.system_tools import logger
from eylo.pipelines.agent_execution_context import PlatformExecutionContext
from eylo.pipelines.memory.application import (
    forget_context_fact,
    recall_context_memory,
    refresh_context_fact,
    remember_context_fact,
)
from eylo.pipelines.memory.tool_results import (
    MemoryChangeView,
    MemoryConflictFactView,
    MemoryConflictView,
    MemoryFactView,
    MemoryForgetResult,
    MemoryRecallFactView,
    MemoryRecallFailure,
    MemoryRecallResult,
    MemoryRefreshResult,
    MemoryRememberResult,
)

MAX_RESULTS = 5

_NOT_CONFIGURED = (
    "Memory is not configured for this organization, so there is nothing to "
    "remember with. This is not the same as finding no matching fact."
)
_NO_CONTEXT = "No conversation in context."


async def memory_recall(
    query: str,
    ctx: PlatformExecutionContext | None = None,
) -> dict[str, JsonValue]:
    """Recall relevant Agent, User, and Conversation memories.

    Use this when prior learned facts could help answer or act now. Results are
    globally ranked across all three levels. Keep each returned `id` and
    `level` together if you later need to refresh or forget that exact fact.
    Direct objectives without a conversation recall only this Agent's memories.

    Args:
        query (str): What to recall, written as a natural-language question.

    Returns:
        `success`, ordered `memories` (`id`, `level`, `content`, `score`), and
        a `message` when nothing matched or Memory is unavailable.

    """
    if ctx is None:
        return MemoryRecallFailure(message=_NO_CONTEXT).model_dump(mode="json")

    try:
        recall = await recall_context_memory(ctx, query, limit=MAX_RESULTS)
    except NotConfiguredError:
        return MemoryRecallFailure(message=_NOT_CONFIGURED).model_dump(mode="json")
    except MemoryError as error:
        logger.warning("Memory recall failed: %s", type(error).__name__)
        return MemoryRecallFailure(
            message="Memory is unavailable right now.",
        ).model_dump(mode="json")

    found = recall.memories
    return MemoryRecallResult(
        memories=tuple(
            MemoryRecallFactView(
                id=memory.id,
                level=memory.scope.level,
                content=memory.content,
                score=memory.score,
            )
            for memory in found
        ),
        conflicts=tuple(
            MemoryConflictView(
                relationship_id=conflict.relationship_id,
                level=conflict.facts[0].scope.level,
                facts=(
                    MemoryConflictFactView(
                        id=conflict.facts[0].id, content=conflict.facts[0].content
                    ),
                    MemoryConflictFactView(
                        id=conflict.facts[1].id, content=conflict.facts[1].content
                    ),
                ),
            )
            for conflict in recall.conflicts
        ),
        message=(
            "Unresolved memory conflicts require user clarification."
            if recall.conflicts
            else ""
            if found
            else "Nothing remembered that matches."
        ),
        ranking=recall.ranking,
    ).model_dump(mode="json")


async def memory_remember(
    fact: str,
    level: MemoryLevel,
    ctx: ConversationContext | None = None,
) -> dict[str, JsonValue]:
    """Remember a fact at the Agent, User, or Conversation level.

    Choose `agent` for reusable knowledge learned by this Agent, `user` for a
    preference or detail about the current User, and `conversation` for working
    context that matters only inside this extended conversation. The fact is
    reconciled with existing memories, so it may add, update, or do nothing.

    Args:
        fact (str): A standalone fact without turn-dependent pronouns.
        level (MemoryLevel): `agent`, `user`, or `conversation`.

    Returns:
        `success`, the exact inferred `changes`, and a status `message`.

    """
    if ctx is None:
        return MemoryRememberResult(success=False, message=_NO_CONTEXT).model_dump(
            mode="json"
        )
    if not fact.strip():
        return MemoryRememberResult(
            success=False, message="Nothing to remember."
        ).model_dump(mode="json")

    try:
        operations = await remember_context_fact(ctx, fact, level=level)
    except NotConfiguredError:
        return MemoryRememberResult(success=False, message=_NOT_CONFIGURED).model_dump(
            mode="json"
        )
    except MemoryError as error:
        logger.warning("Memory remember failed: %s", type(error).__name__)
        return MemoryRememberResult(
            success=False, message="Memory is unavailable right now."
        ).model_dump(mode="json")

    changes = tuple(
        MemoryChangeView(
            event=operation.event,
            content=operation.content,
            memory_id=operation.target_id,
        )
        for operation in operations
    )
    return MemoryRememberResult(
        success=True,
        changes=changes,
        message="" if changes else "No memory change was needed.",
    ).model_dump(mode="json")


async def memory_refresh(
    memory_id: UUID,
    level: MemoryLevel,
    fact: str,
    ctx: ConversationContext | None = None,
) -> dict[str, JsonValue]:
    """Refresh one active memory while preserving its identity and history.

    Use the `id` and `level` returned by `memory_recall`. This is an exact
    correction, not another extraction pass. Expired or foreign facts are not
    revealed and cannot be refreshed.

    Args:
        memory_id (UUID): Exact ID returned by `memory_recall`.
        level (MemoryLevel): The level returned with that ID.
        fact (str): The complete corrected standalone fact.

    Returns:
        `success`, refreshed `memory`, and a status `message`.

    """
    if ctx is None:
        return MemoryRefreshResult(success=False, message=_NO_CONTEXT).model_dump(
            mode="json"
        )
    try:
        memory = await refresh_context_fact(
            ctx,
            memory_id,
            fact,
            level=level,
        )
    except NotConfiguredError:
        return MemoryRefreshResult(success=False, message=_NOT_CONFIGURED).model_dump(
            mode="json"
        )
    except MemoryError as error:
        logger.warning("Memory refresh failed: %s", type(error).__name__)
        return MemoryRefreshResult(
            success=False, message="No active memory was found at that level."
        ).model_dump(mode="json")
    return MemoryRefreshResult(
        success=True,
        memory=MemoryFactView(
            id=memory.id, level=memory.scope.level, content=memory.content
        ),
        message="Memory refreshed.",
    ).model_dump(mode="json")


async def memory_forget(
    memory_id: UUID,
    level: MemoryLevel,
    ctx: ConversationContext | None = None,
) -> dict[str, JsonValue]:
    """Expire one active memory so Agents no longer recall it.

    Use the `id` and `level` returned by `memory_recall`. Forgetting is not hard
    deletion: operators can still inspect the expired fact and its history.

    Args:
        memory_id (UUID): Exact ID returned by `memory_recall`.
        level (MemoryLevel): The level returned with that ID.

    Returns:
        `success`, `expired`, and a status `message`.

    """
    if ctx is None:
        return MemoryForgetResult(
            success=False, expired=False, message=_NO_CONTEXT
        ).model_dump(mode="json")
    try:
        expired = await forget_context_fact(ctx, memory_id, level=level)
    except NotConfiguredError:
        return MemoryForgetResult(
            success=False, expired=False, message=_NOT_CONFIGURED
        ).model_dump(mode="json")
    except MemoryError as error:
        logger.warning("Memory forget failed: %s", type(error).__name__)
        return MemoryForgetResult(
            success=False, expired=False, message="Memory is unavailable right now."
        ).model_dump(mode="json")
    return MemoryForgetResult(
        success=expired,
        expired=expired,
        message="Memory expired."
        if expired
        else "No active memory was found at that level.",
    ).model_dump(mode="json")


__all__ = [
    "memory_forget",
    "memory_recall",
    "memory_refresh",
    "memory_remember",
]
