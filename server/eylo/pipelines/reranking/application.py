"""One bounded, failure-visible reranking stage for retrieval pipelines."""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from eylo.common.contracts.reranking import (
    RankingMetadata,
    RankingReason,
    RankingState,
    RerankResult,
    RerankingError,
    RerankingErrorCode,
    RerankingRecovery,
)
from eylo.pipelines.reranking.resolver import RerankingRuntime

logger = logging.getLogger(__name__)

MAX_RERANK_CHARACTERS = 200_000
RERANK_TIMEOUT_SECONDS = 3.0
_SELECTIONS = TypeAdapter(list[RerankResult])


class BoundedRerankingOutcome(BaseModel):
    """Validated selections, or ``None`` when retrieval order must be used."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    selections: tuple[RerankResult, ...] | None
    metadata: RankingMetadata


async def bounded_rerank(
    query: str,
    documents: list[str],
    reranker: RerankingRuntime | None,
    *,
    top_k: int,
    pre_degraded_reason: RankingReason | None = None,
) -> BoundedRerankingOutcome:
    """Rerank bounded candidates without making retrieval depend on the provider."""
    returned_count = min(top_k, len(documents))
    if reranker is None:
        return BoundedRerankingOutcome(
            selections=None,
            metadata=_metadata(
                state=RankingState.NOT_REQUESTED,
                comparable=False,
                reranker=None,
                reason=None,
                candidate_count=len(documents),
                returned_count=returned_count,
            ),
        )

    degraded_reason = pre_degraded_reason
    if (
        degraded_reason is None
        and len(documents) > reranker.adapter.capabilities.max_documents
    ):
        degraded_reason = RankingReason.CANDIDATE_BUDGET_EXCEEDED
    if (
        degraded_reason is None
        and sum(len(document) for document in documents) > MAX_RERANK_CHARACTERS
    ):
        degraded_reason = RankingReason.CANDIDATE_CONTENT_BUDGET_EXCEEDED

    if degraded_reason is None and documents:
        try:
            async with asyncio.timeout(RERANK_TIMEOUT_SECONDS):
                selections = await reranker.adapter.rerank(
                    query,
                    documents,
                    top_k=returned_count,
                )
            selections = _validate_selections(
                selections,
                candidate_count=len(documents),
                expected_count=returned_count,
            )
        except RerankingError as error:
            degraded_reason = safe_degraded_reason(error.code)
        except TimeoutError:
            degraded_reason = RankingReason.PROVIDER_TIMEOUT
        else:
            return BoundedRerankingOutcome(
                selections=tuple(selections),
                metadata=_metadata(
                    state=RankingState.APPLIED,
                    comparable=True,
                    reranker=reranker,
                    reason=None,
                    candidate_count=len(documents),
                    returned_count=len(selections),
                ),
            )

    if not documents and degraded_reason is None:
        return BoundedRerankingOutcome(
            selections=(),
            metadata=_metadata(
                state=RankingState.APPLIED,
                comparable=True,
                reranker=reranker,
                reason=RankingReason.NO_CANDIDATES,
                candidate_count=0,
                returned_count=0,
            ),
        )

    _log_degradation(reranker, degraded_reason)
    return BoundedRerankingOutcome(
        selections=None,
        metadata=_metadata(
            state=RankingState.DEGRADED,
            comparable=False,
            reranker=reranker,
            reason=degraded_reason,
            candidate_count=len(documents),
            returned_count=returned_count,
        ),
    )


def _validate_selections(
    selections: object,
    *,
    candidate_count: int,
    expected_count: int,
) -> list[RerankResult]:
    try:
        validated = _SELECTIONS.validate_python(selections, strict=True)
    except ValidationError:
        raise RerankingError(
            "Reranking provider returned invalid selections.",
            code=RerankingErrorCode.INVALID_RESPONSE,
            recovery=RerankingRecovery.RETRY,
        ) from None
    indices = [selection.index for selection in validated]
    if (
        len(validated) != expected_count
        or len(indices) != len(set(indices))
        or any(index < 0 or index >= candidate_count for index in indices)
    ):
        raise RerankingError(
            "Reranking provider returned invalid selections.",
            code=RerankingErrorCode.INVALID_RESPONSE,
            recovery=RerankingRecovery.RETRY,
        )
    return validated


def _metadata(
    *,
    state: RankingState,
    comparable: bool,
    reranker: RerankingRuntime | None,
    reason: RankingReason | None,
    candidate_count: int,
    returned_count: int,
) -> RankingMetadata:
    return RankingMetadata(
        state=state,
        comparable=comparable,
        reason=reason,
        provider=reranker.provider if reranker else None,
        provider_config_id=reranker.provider_config_id if reranker else None,
        provider_config_revision=(
            reranker.provider_config_revision if reranker else None
        ),
        candidate_count=candidate_count,
        returned_count=returned_count,
    )


def _log_degradation(
    reranker: RerankingRuntime,
    reason: RankingReason | None,
) -> None:
    logger.warning(
        "Reranking degraded provider=%s config_id=%s revision=%d reason=%s",
        reranker.provider,
        reranker.provider_config_id,
        reranker.provider_config_revision,
        reason,
    )


def safe_degraded_reason(code: RerankingErrorCode) -> RankingReason:
    return {
        RerankingErrorCode.TRANSPORT: RankingReason.PROVIDER_UNAVAILABLE,
        RerankingErrorCode.RATE_LIMITED: RankingReason.PROVIDER_RATE_LIMITED,
        RerankingErrorCode.PROVIDER_UNAVAILABLE: RankingReason.PROVIDER_UNAVAILABLE,
        RerankingErrorCode.AUTHENTICATION: RankingReason.PROVIDER_AUTHENTICATION_FAILED,
        RerankingErrorCode.INVALID_REQUEST: RankingReason.PROVIDER_REJECTED_REQUEST,
        RerankingErrorCode.INVALID_RESPONSE: RankingReason.INVALID_PROVIDER_RESPONSE,
    }.get(code, RankingReason.PROVIDER_UNAVAILABLE)


__all__ = [
    "BoundedRerankingOutcome",
    "MAX_RERANK_CHARACTERS",
    "RERANK_TIMEOUT_SECONDS",
    "bounded_rerank",
    "safe_degraded_reason",
]
