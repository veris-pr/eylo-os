"""Voyage hosted reranking with no tenant-controlled endpoint."""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from eylo.sockets.reranking.base import RerankingVendorAdapter
from eylo.sockets.reranking.schemas import (
    RerankResult,
    RerankingCapabilities,
    RerankingConfig,
    RerankingError,
    RerankingErrorCode,
    RerankingRecovery,
    RerankingTruncation,
)
from eylo.sockets.reranking.validation import (
    raise_for_status,
    validate_rerank_request,
    validate_rerank_results,
)
from eylo.sockets.reranking.vendors.voyage_wire import (
    MAX_DOCUMENTS,
    VoyageRerankRequest,
    VoyageRerankResponse,
)

PROVIDER = "voyage"
API_URL = "https://api.voyageai.com/v1/rerank"
TIMEOUT_SECONDS = 10


class VoyageRerankAdapter(RerankingVendorAdapter):
    def __init__(self, config: RerankingConfig) -> None:
        self._config = RerankingConfig.model_validate(config)

    @property
    def provider(self) -> str:
        return PROVIDER

    @property
    def capabilities(self) -> RerankingCapabilities:
        return RerankingCapabilities(
            max_documents=MAX_DOCUMENTS, truncation=RerankingTruncation.DISABLED
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int,
    ) -> list[RerankResult]:
        if not documents:
            return []
        expected_count = validate_rerank_request(
            query,
            documents,
            top_k=top_k,
            max_documents=MAX_DOCUMENTS,
            vendor=PROVIDER,
        )
        try:
            request = VoyageRerankRequest(
                model=self._config.model,
                query=query,
                documents=tuple(documents),
                top_k=expected_count,
            )
        except ValidationError:
            raise RerankingError(
                "Voyage reranking request is invalid.",
                vendor=PROVIDER,
                code=RerankingErrorCode.INVALID_REQUEST,
            ) from None
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                    json=request.to_payload(),
                )
            raise_for_status(response, vendor=PROVIDER)
            payload = VoyageRerankResponse.model_validate(response.json())
            return validate_rerank_results(
                [
                    RerankResult(index=item.index, score=item.relevance_score)
                    for item in payload.data
                ],
                expected_count=expected_count,
                candidate_count=len(documents),
                vendor=PROVIDER,
            )
        except RerankingError:
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            raise RerankingError(
                "Voyage reranking transport failed.",
                vendor=PROVIDER,
                code=RerankingErrorCode.TRANSPORT,
                recovery=RerankingRecovery.RETRY,
            ) from None
        except (TypeError, ValueError):
            raise RerankingError(
                "Voyage returned invalid JSON.",
                vendor=PROVIDER,
                code=RerankingErrorCode.INVALID_RESPONSE,
                recovery=RerankingRecovery.RETRY,
            ) from None
