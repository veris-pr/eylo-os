"""Typed retrieval projections and the existing agent-facing JSON boundary."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue

from eylo.common.contracts.knowledgebase import KnowledgeScope
from eylo.common.contracts.reranking import RankingMetadata, RankingReason, RankingState
from eylo.events.schema.py_events.knowledgebase import KnowledgeObservationOutcome


class KnowledgeQueryCandidate(BaseModel):
    """A retrieved passage plus the granting knowledgebase's identity."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True,
    )

    document_id: str
    content: str = Field(repr=False)
    title: str | None
    source_uri: str | None
    scope: KnowledgeScope
    scope_id: str
    score: FiniteFloat
    knowledgebase_id: UUID
    knowledgebase: str
    retrieval_score: FiniteFloat | None = None

    def reranked(self, score: float) -> KnowledgeQueryCandidate:
        """Preserve retrieval provenance while validating the replacement score."""
        values = self.model_dump()
        values.update(score=score, retrieval_score=self.score)
        return KnowledgeQueryCandidate.model_validate(values)


class KnowledgeQueryCitation(BaseModel):
    """Stable source identity with a label assigned after final ordering."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    label: str
    knowledgebase_id: UUID
    document_id: str
    title: str | None
    source_uri: str | None


class KnowledgeQueryResult(KnowledgeQueryCandidate):
    """Final ranked passage; optional retrieval score retains its wire omission."""

    citation: KnowledgeQueryCitation
    ranking_state: RankingState
    score_comparable: bool

    def to_payload(self) -> dict[str, JsonValue]:
        result = KnowledgeQueryResult.model_validate(self)
        return result.model_dump(
            mode="json",
            exclude={"retrieval_score"} if self.retrieval_score is None else None,
        )


class KnowledgeQueryObservation(BaseModel):
    """Local metrics, never a field in an agent's tool result."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    outcome: KnowledgeObservationOutcome
    requested_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    ranking_state: RankingState
    ranking_reason: RankingReason | None
    failure_code: str | None = None


class KnowledgeQueryResponse(BaseModel):
    """Query outcome with an explicit boundary between product data and metrics."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True,
    )

    success: bool
    results: tuple[KnowledgeQueryResult, ...] = ()
    message: str
    ranking: RankingMetadata | None = None
    observation: KnowledgeQueryObservation | None = Field(
        default=None, exclude=True, repr=False
    )

    def to_payload(self) -> dict[str, JsonValue]:
        """Preserve public optional-field behavior without serializing local metrics."""
        response = KnowledgeQueryResponse.model_validate(self)
        payload: dict[str, JsonValue] = {
            "success": response.success,
            "results": [item.to_payload() for item in response.results],
            "message": response.message,
        }
        if response.ranking is not None:
            payload["ranking"] = response.ranking.model_dump(mode="json")
        return payload
