"""Shared JSON contracts for persisted Memory operations and committed outcomes."""

from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    model_validator,
)

from eylo.common.contracts.memory import MemoryError as MemoryProviderError
from eylo.common.contracts.memory import MemoryOperation, MemoryOutcomeCounts


class MemoryOperationBatch(RootModel[list[MemoryOperation]]):
    """The persisted list shape; plan policy and committed outcomes are distinct."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    def __repr_args__(self) -> list[tuple[str, object]]:
        """Keep fact content out of both repr and str without changing JSON."""
        return []

    def to_json(self) -> list[dict[str, JsonValue]]:
        return [operation.model_dump(mode="json") for operation in self.root]


class MemoryFormationCountsMismatch(MemoryProviderError):
    """Structurally valid counts disagree with the committed operation list."""

    def __init__(self) -> None:
        super().__init__("Memory formation counts are inconsistent.")


class MemoryFormationOutcomes(BaseModel):
    """Exactly the committed operations and their independently checked counts."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    operations: list[MemoryOperation] = Field(repr=False)
    counts: MemoryOutcomeCounts

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if self.counts != MemoryOutcomeCounts.from_operations(self.operations):
            raise MemoryFormationCountsMismatch
        return self

    @classmethod
    def from_operations(cls, operations: list[MemoryOperation]) -> Self:
        return cls(
            operations=operations,
            counts=MemoryOutcomeCounts.from_operations(operations),
        )

    def to_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")
