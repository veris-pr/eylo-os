"""Validated vendor-neutral vectors at live-result and durable replay boundaries."""

from typing import Self

from pydantic import ConfigDict, FiniteFloat, RootModel, ValidationError

from eylo.common.contracts.embedding import EmbeddingError, EmbeddingErrorCode


class EmbeddingVectorBatch(RootModel[list[list[FiniteFloat]]]):
    """Ordered vectors, never an authority for selecting their coordinate space."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    def __repr_args__(self) -> list[tuple[str, object]]:
        """Keep private vectors out of repr/str; explicit JSON retains the list."""
        return []

    @classmethod
    def validate_result(
        cls,
        value: object,
        *,
        expected_count: int,
        dimensions: int,
        vendor: str,
    ) -> Self:
        """Refuse malformed or partial results before checkpoint or DB effects.

        The caller supplies verified dimensions and input count. These failures
        are terminal contract errors; vendor transport/retry policy stays in the
        adapter. Replaying the same malformed checkpoint cannot repair it.
        """
        try:
            batch = cls.model_validate(value)
        except ValidationError:
            raise EmbeddingError(
                "Embedding result contains invalid vectors.",
                vendor=vendor,
                code=EmbeddingErrorCode.INVALID_RESPONSE,
            ) from None
        if len(batch.root) != expected_count:
            raise EmbeddingError(
                "Embedding result does not match the complete input batch.",
                vendor=vendor,
                code=EmbeddingErrorCode.INVALID_RESPONSE,
            )
        if any(len(vector) != dimensions for vector in batch.root):
            raise EmbeddingError(
                "Embedding vector dimensions do not match the verified space.",
                vendor=vendor,
                code=EmbeddingErrorCode.DIMENSION_MISMATCH,
            )
        return batch
