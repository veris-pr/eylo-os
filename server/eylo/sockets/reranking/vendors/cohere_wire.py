"""Cohere v2 rerank JSON; native fields never cross the adapter boundary."""

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue

MAX_DOCUMENTS = 1000


class CohereRerankRequest(BaseModel):
    """Only the active text request; generic dumps omit candidate/query text."""

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
    top_n: int = Field(ge=1, le=MAX_DOCUMENTS)

    def to_payload(self) -> dict[str, JsonValue]:
        request = type(self).model_validate(self)
        return {
            "model": request.model,
            "query": request.query,
            "documents": list(request.documents),
            "top_n": request.top_n,
        }


class CohereRankedDocument(BaseModel):
    """Consumed result fields; optional vendor metadata/document echoes are ignored."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    index: int = Field(ge=0)
    relevance_score: FiniteFloat


class CohereRerankResponse(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    results: list[CohereRankedDocument] = Field(max_length=MAX_DOCUMENTS)
