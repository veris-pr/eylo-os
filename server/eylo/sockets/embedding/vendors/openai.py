"""OpenAI and operator-trusted OpenAI-compatible embeddings."""

from __future__ import annotations

from http import HTTPStatus

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

from .openai_wire import MAX_BATCH, OpenAIEmbeddingRequest, OpenAIEmbeddingResponse

PROVIDER = "openai"


class OpenAIEmbeddingAdapter(EmbeddingVendorAdapter):
    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config

    @property
    def provider(self) -> str:
        return PROVIDER

    @property
    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(
            asymmetric=False,
            max_batch=MAX_BATCH,
            dimensions=None,
        )

    @property
    def semantic_options(self) -> EmbeddingSemanticOptions:
        return {"protocol_revision": 1, "input_mode": "symmetric"}

    async def embed(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInput = EmbeddingInput.DOCUMENT,
    ) -> list[list[float]]:
        if not texts:
            return []

        from openai import AsyncOpenAI

        try:
            async with AsyncOpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url or None,
            ) as client:
                vectors: list[list[float]] = []
                for start in range(0, len(texts), MAX_BATCH):
                    batch = texts[start : start + MAX_BATCH]
                    try:
                        request = OpenAIEmbeddingRequest(
                            model=self._config.model, input=batch
                        )
                    except ValidationError:
                        raise EmbeddingError(
                            "OpenAI embedding request is invalid.",
                            vendor=PROVIDER,
                            code=EmbeddingErrorCode.INVALID_REQUEST,
                        ) from None
                    try:
                        response = await client.embeddings.create(
                            model=request.model,
                            input=request.input,
                        )
                    except (AttributeError, TypeError, ValueError):
                        # The SDK's base64 post-parser runs before our projection.
                        raise _invalid_response() from None
                    payload = OpenAIEmbeddingResponse.model_validate(response)
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
        except ValidationError:
            raise _invalid_response() from None
        except Exception as error:
            raise _normalized_openai_error(error) from None


def _normalized_openai_error(error: Exception) -> EmbeddingError:
    from openai import (
        APIConnectionError,
        APIResponseValidationError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        RateLimitError,
    )

    if isinstance(error, APIResponseValidationError):
        return _invalid_response()
    if isinstance(error, AuthenticationError):
        return EmbeddingError(
            "OpenAI embedding authentication failed.",
            vendor=PROVIDER,
            code=EmbeddingErrorCode.AUTHENTICATION,
        )
    if isinstance(error, BadRequestError):
        return EmbeddingError(
            "OpenAI rejected the embedding request.",
            vendor=PROVIDER,
            code=EmbeddingErrorCode.INVALID_REQUEST,
        )
    if isinstance(error, RateLimitError):
        return EmbeddingError(
            "OpenAI rate-limited the embedding request.",
            vendor=PROVIDER,
            code=EmbeddingErrorCode.RATE_LIMITED,
            retryable=True,
        )
    if isinstance(error, (APIConnectionError, APITimeoutError)):
        return EmbeddingError(
            "OpenAI embedding transport failed.",
            vendor=PROVIDER,
            code=EmbeddingErrorCode.TRANSPORT,
            retryable=True,
        )
    if isinstance(error, APIStatusError):
        return EmbeddingError(
            "OpenAI embedding provider failed.",
            vendor=PROVIDER,
            code=EmbeddingErrorCode.PROVIDER_ERROR,
            retryable=error.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR,
        )
    return EmbeddingError(
        "OpenAI embedding request failed.",
        vendor=PROVIDER,
        code=EmbeddingErrorCode.PROVIDER_ERROR,
    )


def _invalid_response() -> EmbeddingError:
    return EmbeddingError(
        "OpenAI returned an invalid embedding response.",
        vendor=PROVIDER,
        code=EmbeddingErrorCode.INVALID_RESPONSE,
        retryable=True,
    )
