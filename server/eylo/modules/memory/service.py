"""Domain persistence for observable memory recall state."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.common.contracts.memory import MemoryError, MemoryLevel, MemoryResult
from eylo.modules.memory.models import MemoryModel


async def record_recalled_memories(
    session: AsyncSession, memories: Sequence[MemoryResult]
) -> None:
    """Atomically count one real Agent-facing recall for every returned fact."""
    if not memories:
        return
    organization_ids = {memory.scope.organization_id for memory in memories}
    memory_ids = {memory.id for memory in memories}
    if len(organization_ids) != 1 or len(memory_ids) != len(memories):
        raise MemoryError("Memory recall audit input is inconsistent.")

    organization_id = organization_ids.pop()
    result = await session.execute(
        update(MemoryModel)
        .where(
            MemoryModel.id.in_(memory_ids),
            MemoryModel.organization_id == organization_id,
            MemoryModel.deleted.is_(False),
            (MemoryModel.expires_at.is_(None) | (MemoryModel.expires_at > func.now())),
        )
        .values(
            recall_count=MemoryModel.recall_count + 1,
            last_recalled_at=func.now(),
        )
    )
    if not isinstance(result, CursorResult) or result.rowcount != len(memory_ids):
        raise MemoryError("Memory recall audit lost an active fact.")


def memory_owner_id(model: MemoryModel) -> UUID:
    """Return the single owner guaranteed by the DB scope constraint."""
    owner = {
        MemoryLevel.AGENT: model.agent_id,
        MemoryLevel.USER: model.contact_id,
        MemoryLevel.CONVERSATION: model.conversation_id,
    }[model.scope_level]
    if owner is None:
        raise MemoryError("Stored memory scope is incomplete.")
    return owner


__all__ = ["memory_owner_id", "record_recalled_memories"]
