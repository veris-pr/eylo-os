"""LLM prompt and response shapes; local indexes never confer Memory authority."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from eylo.common.contracts.memory_reconciliation import (
    MEMORY_RECONCILIATION_MAX_CANDIDATES,
    MEMORY_RECONCILIATION_MAX_CHANGES,
    MemoryReconciliationOutcome,
)


class _ReconciliationWireValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ReconciliationPromptCandidate(_ReconciliationWireValue):
    id: int = Field(ge=0)
    content: str = Field(repr=False)


class ReconciliationPromptFact(_ReconciliationWireValue):
    id: int = Field(ge=0)
    content: str = Field(repr=False)
    candidates: tuple[ReconciliationPromptCandidate, ...] = Field(
        max_length=MEMORY_RECONCILIATION_MAX_CANDIDATES
    )


class ReconciliationPrompt(_ReconciliationWireValue):
    facts: tuple[ReconciliationPromptFact, ...] = Field(
        min_length=1, max_length=MEMORY_RECONCILIATION_MAX_CHANGES
    )


class ReconciliationResponseDecision(_ReconciliationWireValue):
    fact: StrictInt
    outcome: MemoryReconciliationOutcome
    related: StrictInt | None

    @field_validator("outcome", mode="before")
    @classmethod
    def normalize_outcome(cls, value: object) -> MemoryReconciliationOutcome:
        if not isinstance(value, str):
            raise ValueError("Memory reconciliation outcome must be text.")
        return MemoryReconciliationOutcome(value.strip().lower())


class ReconciliationResponse(_ReconciliationWireValue):
    decisions: list[ReconciliationResponseDecision] = Field(
        max_length=MEMORY_RECONCILIATION_MAX_CHANGES
    )
