"""Detached, validated row projections owned by the PgVector Memory adapter."""

from typing import Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.contracts.memory import (
    Memory,
    MemoryChange,
    MemoryEvent,
    MemoryLevel,
    MemoryProvenance,
    MemoryResult,
    MemoryScope,
)
from eylo.common.contracts.memory import MemoryError as MemoryProviderError
from eylo.common.contracts.memory_formation import MemoryFormationOutcomes

PGVECTOR_PROVIDER = "pgvector"


class _MemoryRow(BaseModel):
    """Project consumed columns; fail without exposing fact/provenance values."""

    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
        strict=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    @classmethod
    def from_row(cls, row: object) -> Self:
        try:
            return cls.model_validate(row)
        except ValidationError:
            raise MemoryProviderError(
                "Memory database row is invalid.", vendor=PGVECTOR_PROVIDER
            ) from None


class MemoryOwnerRow(_MemoryRow):
    organization_id: UUID
    scope_level: MemoryLevel
    agent_id: UUID | None
    contact_id: UUID | None
    conversation_id: UUID | None

    @field_validator("scope_level", mode="before")
    @classmethod
    def parse_level(cls, value: object) -> MemoryLevel:
        if not isinstance(value, str):
            raise ValueError("Stored memory level must be a string.")
        return MemoryLevel(value)

    @model_validator(mode="after")
    def exact_owner(self) -> Self:
        owners = {
            MemoryLevel.AGENT: self.agent_id,
            MemoryLevel.USER: self.contact_id,
            MemoryLevel.CONVERSATION: self.conversation_id,
        }
        if (
            owners[self.scope_level] is None
            or sum(owner is not None for owner in owners.values()) != 1
        ):
            raise ValueError("Stored memory must have exactly its declared owner.")
        return self

    @property
    def scope(self) -> MemoryScope:
        owner = {
            MemoryLevel.AGENT: self.agent_id,
            MemoryLevel.USER: self.contact_id,
            MemoryLevel.CONVERSATION: self.conversation_id,
        }[self.scope_level]
        if owner is None:
            raise MemoryProviderError(
                "Stored memory scope is incomplete.", vendor=PGVECTOR_PROVIDER
            )
        return MemoryScope(
            organization_id=self.organization_id,
            level=self.scope_level,
            owner_id=owner,
        )


class _MemoryValueRow(MemoryOwnerRow):
    id: UUID
    content: str = Field(repr=False)
    updated_at: AwareDatetime
    meta: dict[str, JsonValue] | None = Field(repr=False)
    provenance: MemoryProvenance = Field(repr=False)


class MemoryFactRow(_MemoryValueRow):
    created_at: AwareDatetime

    def to_memory(self) -> Memory:
        return Memory(
            id=self.id,
            content=self.content,
            scope=self.scope,
            created_at=self.created_at,
            updated_at=self.updated_at,
            metadata=self.meta or {},
            provenance=self.provenance,
        )


class MemorySearchRow(_MemoryValueRow):
    distance: FiniteFloat

    def to_result(self) -> MemoryResult:
        return MemoryResult(
            id=self.id,
            content=self.content,
            score=1.0 - self.distance,
            scope=self.scope,
            updated_at=self.updated_at,
            metadata=self.meta or {},
            provenance=self.provenance,
        )


class MemoryLockedRow(MemoryFactRow):
    content_hash: str
    state_revision: int = Field(gt=0)


class MemoryChangeRow(MemoryOwnerRow):
    id: UUID
    memory_id: UUID
    event: MemoryEvent
    before: str | None = Field(repr=False)
    after: str | None = Field(repr=False)
    provenance: MemoryProvenance = Field(repr=False)
    created_at: AwareDatetime

    @field_validator("event", mode="before")
    @classmethod
    def parse_event(cls, value: object) -> MemoryEvent:
        if not isinstance(value, str):
            raise ValueError("Stored memory event must be a string.")
        return MemoryEvent(value)

    def to_change(self) -> MemoryChange:
        return MemoryChange(
            id=self.id,
            memory_id=self.memory_id,
            event=self.event,
            before=self.before,
            after=self.after,
            created_at=self.created_at,
            scope=self.scope,
            provenance=self.provenance,
        )


class MemoryTargetRow(_MemoryRow):
    id: UUID
    content: str = Field(repr=False)
    content_hash: str
    state_revision: int = Field(gt=0)


class MemoryDuplicateRow(MemoryTargetRow):
    expired: bool


class MemoryChangeTimestampRow(_MemoryRow):
    """The DB timestamp returned by history insertion and used by its cursor."""

    created_at: AwareDatetime


class MemoryFormationEffectRow(_MemoryRow):
    """Only a completed effect may supply a committed outcome for replay."""

    outcomes: MemoryFormationOutcomes | None = Field(repr=False)
    finished_at: AwareDatetime | None

    @model_validator(mode="after")
    def completed_outcomes(self) -> Self:
        if (self.finished_at is None) != (self.outcomes is None):
            raise ValueError("Memory effect completion and outcomes must agree.")
        return self
