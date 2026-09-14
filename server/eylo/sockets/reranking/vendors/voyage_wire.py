"""Voyage rerank JSON, including its distinct result envelope and truncation flag."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue

MAX_DOCUMENTS = 1000


class VoyageRerankRequest(BaseModel):
    """The existing non-truncating request, with private text until dispatch."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    model: str = Field(min_length=1, max_length=255)
    query: str = Field(min_length=1, repr=False, exclude=True)
    documents: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_DOCUMENTS, repr=False, exclude=True
    )
    top_k: int = Field(ge=1, le=MAX_DOCUMENTS)
    truncation: Literal[False] = False

    def to_payload(self) -> dict[str, JsonValue]:
        request = type(self).model_validate(self)
        return {
            "model": request.model,
            "query": request.query,
            "documents": list(request.documents),
            "top_k": request.top_k,
            "truncation": request.truncation,
        }


class VoyageRankedDocument(BaseModel):
    """Consumed native score/index; echoed documents are not used as source data."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    index: int = Field(ge=0)
    relevance_score: FiniteFloat


class VoyageRerankResponse(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    data: list[VoyageRankedDocument] = Field(max_length=MAX_DOCUMENTS)
