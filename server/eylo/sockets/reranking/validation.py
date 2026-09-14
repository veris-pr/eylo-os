"""Atomic validation for untrusted reranking responses."""

from __future__ import annotations

import httpx
from pydantic import TypeAdapter, ValidationError

from eylo.sockets.reranking.schemas import (
    RerankResult,
    RerankingError,
    RerankingErrorCode,
    RerankingRecovery,
)

_RESULTS = TypeAdapter(list[RerankResult])


def raise_for_status(response: httpx.Response, *, vendor: str) -> None:
    if response.status_code < 400:
        return
    if response.status_code in {401, 403, 498}:
        code = RerankingErrorCode.AUTHENTICATION
        recovery = RerankingRecovery.TERMINAL
    elif response.status_code == 429:
        code = RerankingErrorCode.RATE_LIMITED
        recovery = RerankingRecovery.RETRY
    elif response.status_code >= 500:
        code = RerankingErrorCode.PROVIDER_UNAVAILABLE
        recovery = RerankingRecovery.RETRY
    else:
        code = RerankingErrorCode.INVALID_REQUEST
        recovery = RerankingRecovery.TERMINAL
    raise _error(
        "Reranking provider rejected the request.",
        vendor,
        code,
        recovery=recovery,
    )


def validate_rerank_request(
    query: str,
    documents: list[str],
    *,
    top_k: int,
    max_documents: int,
    vendor: str,
) -> int:
    if not isinstance(query, str) or not query.strip():
        raise _error(
            "Reranking query must be non-empty.",
            vendor,
            RerankingErrorCode.INVALID_REQUEST,
        )
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise _error(
            "top_k must be a positive integer.",
            vendor,
            RerankingErrorCode.INVALID_REQUEST,
        )
    if len(documents) > max_documents:
        raise _error(
            "Reranking candidate limit exceeded.",
            vendor,
            RerankingErrorCode.CANDIDATE_LIMIT,
        )
    if any(
        not isinstance(document, str) or not document.strip() for document in documents
    ):
        raise _error(
            "Reranking documents must be non-empty strings.",
            vendor,
            RerankingErrorCode.INVALID_REQUEST,
        )
    return min(top_k, len(documents))


def validate_rerank_results(
    entries: object,
    *,
    expected_count: int,
    candidate_count: int,
    vendor: str,
) -> list[RerankResult]:
    try:
        results = _RESULTS.validate_python(entries, strict=True)
    except ValidationError:
        raise _invalid_response(vendor) from None
    if len(results) != expected_count:
        raise _invalid_response(vendor)

    seen: set[int] = set()
    for entry in results:
        if entry.index >= candidate_count or entry.index in seen:
            raise _invalid_response(vendor)
        seen.add(entry.index)

    return sorted(results, key=lambda result: (-result.score, result.index))


def _invalid_response(vendor: str) -> RerankingError:
    return _error(
        "Reranking provider returned an invalid response.",
        vendor,
        RerankingErrorCode.INVALID_RESPONSE,
        recovery=RerankingRecovery.RETRY,
    )


def _error(
    message: str,
    vendor: str,
    code: RerankingErrorCode,
    *,
    recovery: RerankingRecovery = RerankingRecovery.TERMINAL,
) -> RerankingError:
    return RerankingError(
        message,
        vendor=vendor,
        code=code,
        recovery=recovery,
    )
