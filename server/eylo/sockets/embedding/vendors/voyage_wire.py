"""Voyage text embedding HTTP contracts, kept inside the vendor boundary."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue

MAX_BATCH = 128
OUTPUT_DTYPE = "float"
TRUNCATION = False


class VoyageInputType(StrEnum):
    """Native retrieval intents; translated from the capability enum by the adapter."""

    QUERY = "query"
    DOCUMENT = "document"


class VoyageEmbeddingRequest(BaseModel):
    """Explicit intent with no truncation; serialize input only for the HTTP body."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    model: str
    input: list[str] = Field(
        min_length=1, max_length=MAX_BATCH, repr=False, exclude=True
    )
    input_type: VoyageInputType
    truncation: Literal[False] = TRUNCATION
    output_dtype: Literal["float"] = OUTPUT_DTYPE

    def to_payload(self) -> dict[str, JsonValue]:
        validated = type(self).model_validate(self)
        return {
            "model": validated.model,
            "input": list(validated.input),
            "input_type": validated.input_type.value,
            "truncation": validated.truncation,
            "output_dtype": validated.output_dtype,
        }


class VoyageEmbeddingItem(BaseModel):
    """A float vector plus its exact correspondence to the request batch."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    index: int = Field(ge=0)
    embedding: list[FiniteFloat] = Field(min_length=1, repr=False, exclude=True)


class VoyageEmbeddingResponse(BaseModel):
    """Reject malformed entries rather than silently dropping them from a batch."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    data: list[VoyageEmbeddingItem] = Field(repr=False, exclude=True)
