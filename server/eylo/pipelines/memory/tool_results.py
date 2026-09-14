"""Agent-facing Memory projections; domain ownership and provenance stay private."""

from __future__ import annotations

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from eylo.common.contracts.memory import MemoryEvent, MemoryLevel
from eylo.common.contracts.reranking import RankingMetadata


class _MemoryToolValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class MemoryFactView(_MemoryToolValue):
    id: UUID
    level: MemoryLevel
    content: str


class MemoryRecallFactView(MemoryFactView):
    score: float


class MemoryConflictFactView(_MemoryToolValue):
    id: UUID
    content: str


class MemoryConflictView(_MemoryToolValue):
    relationship_id: UUID
    level: MemoryLevel
    facts: tuple[MemoryConflictFactView, MemoryConflictFactView]


class MemoryChangeView(_MemoryToolValue):
    event: MemoryEvent
    content: str
    memory_id: UUID | None


class MemoryRecallResult(_MemoryToolValue):
    success: Literal[True] = True
    memories: tuple[MemoryRecallFactView, ...]
    conflicts: tuple[MemoryConflictView, ...]
    message: str
    ranking: RankingMetadata


class MemoryRecallFailure(_MemoryToolValue):
    """Unavailable recall is distinct from an empty, successfully ranked result."""

    success: Literal[False] = False
    memories: tuple[()] = ()
    conflicts: tuple[()] = ()
    message: str


class MemoryRememberResult(_MemoryToolValue):
    success: bool
    changes: tuple[MemoryChangeView, ...] = ()
    message: str

    @model_validator(mode="after")
    def consistent_changes(self) -> Self:
        if not self.success and self.changes:
            raise ValueError("Failed remember results cannot report applied changes.")
        return self


class MemoryRefreshResult(_MemoryToolValue):
    success: bool
    memory: MemoryFactView | None = None
    message: str

    @model_validator(mode="after")
    def consistent_memory(self) -> Self:
        if self.success != (self.memory is not None):
            raise ValueError("Refresh success requires the refreshed memory.")
        return self


class MemoryForgetResult(_MemoryToolValue):
    success: bool
    expired: bool
    message: str

    @model_validator(mode="after")
    def consistent_expiry(self) -> Self:
        if self.success != self.expired:
            raise ValueError("Forget success must match the expiry outcome.")
        return self
