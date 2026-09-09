"""Voyage embeddings with explicit query/document intent."""

from __future__ import annotations

from http import HTTPStatus

import httpx
from pydantic import ValidationError

from eylo.sockets.embedding.base import EmbeddingVendorAdapter
from eylo.sockets.embedding.schemas import (
    EmbeddingCapabilities,
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingErrorCode,
    EmbeddingInput,
    EmbeddingSemanticOptions,
)
from eylo.sockets.embedding.validation import validate_indexed_vectors

from .voyage_wire import (
    MAX_BATCH,
    OUTPUT_DTYPE,
    TRUNCATION,
    VoyageEmbeddingRequest,
    VoyageEmbeddingResponse,
    VoyageInputType,
)

PROVIDER = "voyage"
API_URL = "https://api.voyageai.com/v1/embeddings"
TIMEOUT_SECONDS = 60


class VoyageEmbeddingAdapter(EmbeddingVendorAdapter):
    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config

    @property
    def provider(self) -> str:
        return PROVIDER

    @property
    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(
            asymmetric=True,
            max_batch=MAX_BATCH,
            dimensions=None,
        )

    @property
    def semantic_options(self) -> EmbeddingSemanticOptions:
        return {
            "protocol_revision": 1,
            "document_input_type": EmbeddingInput.DOCUMENT.value,
            "query_input_type": EmbeddingInput.QUERY.value,
            "truncation": TRUNCATION,
            "output_dtype": OUTPUT_DTYPE,
        }

    async def embed(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInput = EmbeddingInput.DOCUMENT,
    ) -> list[list[float]]:
        if not texts:
            return []

        try:
            vectors: list[list[float]] = []
            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                for start in range(0, len(texts), MAX_BATCH):
                    batch = texts[start : start + MAX_BATCH]
                    try:
                        request = VoyageEmbeddingRequest(
                            model=self._config.model,
                            input=batch,
                            input_type=VoyageInputType(input_type.value),
                        )
                    except ValueError:
                        raise EmbeddingError(
                            "Voyage embedding request is invalid.",
                            vendor=PROVIDER,
                            code=EmbeddingErrorCode.INVALID_REQUEST,
                        ) from None
                    response = await client.post(
                        API_URL,
                        headers={"Authorization": f"Bearer {self._config.api_key}"},
                        json=request.to_payload(),
                    )
                    _raise_for_status(response)
                    payload = VoyageEmbeddingResponse.model_validate_json(
                        response.content
                    )
                    vectors.extend(
                        validate_indexed_vectors(
                            [(item.index, item.embedding) for item in payload.data],
                            expected_count=len(batch),
                            vendor=PROVIDER,
                        )
                    )
            return vectors
        except EmbeddingError:
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            raise EmbeddingError(
                "Voyage embedding transport failed.",
                vendor=PROVIDER,
                code=EmbeddingErrorCode.TRANSPORT,
                retryable=True,
            ) from None
        except ValidationError:
            raise _invalid_response(
                "Voyage returned an invalid embedding response."
            ) from None
        except (TypeError, ValueError):
            raise _invalid_response("Voyage returned invalid JSON.") from None


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < HTTPStatus.BAD_REQUEST:
        return
    if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        code = EmbeddingErrorCode.AUTHENTICATION
        retryable = False
    elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        code = EmbeddingErrorCode.RATE_LIMITED
        retryable = True
    elif response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        code = EmbeddingErrorCode.PROVIDER_ERROR
        retryable = True
    else:
        code = EmbeddingErrorCode.INVALID_REQUEST
        retryable = False
    raise EmbeddingError(
        "Voyage rejected the embedding request.",
        vendor=PROVIDER,
        code=code,
        retryable=retryable,
    )


def _invalid_response(message: str) -> EmbeddingError:
    return EmbeddingError(
        message,
        vendor=PROVIDER,
        code=EmbeddingErrorCode.INVALID_RESPONSE,
        retryable=True,
    )
