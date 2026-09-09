"""AWS Bedrock Runtime adapter for Titan Text Embeddings V2."""

from __future__ import annotations

from http import HTTPStatus

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from eylo.sockets.embedding.base import EmbeddingVendorAdapter
from eylo.sockets.embedding.schemas import (
    BedrockEmbeddingConfig,
    EmbeddingCapabilities,
    EmbeddingError,
    EmbeddingErrorCode,
    EmbeddingInput,
    EmbeddingSemanticOptions,
)

from .bedrock_wire import (
    BEDROCK_RUNTIME_SERVICE,
    JSON_CONTENT_TYPE,
    BedrockErrorResponse,
    BedrockFailureCode,
    BedrockInvocationResponse,
    TitanEmbeddingRequest,
    TitanEmbeddingResponse,
)

PROVIDER = "bedrock"
MAX_BATCH = 1


class BedrockEmbeddingAdapter(EmbeddingVendorAdapter):
    """Invoke one explicit Titan V2 model through AWS Bedrock Runtime."""

    def __init__(self, config: BedrockEmbeddingConfig) -> None:
        self._config = config
        self._session = aioboto3.Session(
            aws_access_key_id=config.access_key_id.get_secret_value(),
            aws_secret_access_key=config.secret_access_key.get_secret_value(),
            aws_session_token=(
                config.session_token.get_secret_value()
                if config.session_token is not None
                else None
            ),
            region_name=config.region,
        )

    @property
    def provider(self) -> str:
        return PROVIDER

    @property
    def capabilities(self) -> EmbeddingCapabilities:
        return EmbeddingCapabilities(
            asymmetric=False,
            max_batch=MAX_BATCH,
            dimensions=self._config.dimensions,
        )

    @property
    def semantic_options(self) -> EmbeddingSemanticOptions:
        return {
            "protocol_revision": 1,
            "input_mode": "symmetric",
            "normalize": self._config.normalize,
        }

    async def embed(
        self,
        texts: list[str],
        *,
        input_type: EmbeddingInput = EmbeddingInput.DOCUMENT,
    ) -> list[list[float]]:
        del input_type  # Titan V2 uses one symmetric request shape for both intents.
        if not texts:
            return []

        try:
            vectors: list[list[float]] = []
            async with self._session.client(BEDROCK_RUNTIME_SERVICE) as client:
                for text in texts:
                    try:
                        request = TitanEmbeddingRequest(
                            input_text=text,
                            dimensions=self._config.dimensions,
                            normalize=self._config.normalize,
                        )
                    except ValidationError:
                        raise EmbeddingError(
                            "Bedrock embedding request is invalid.",
                            vendor=PROVIDER,
                            code=EmbeddingErrorCode.INVALID_REQUEST,
                        ) from None
                    response = BedrockInvocationResponse.model_validate(
                        await client.invoke_model(
                            modelId=self._config.model,
                            contentType=JSON_CONTENT_TYPE,
                            accept=JSON_CONTENT_TYPE,
                            body=request.to_body(),
                        )
                    )
                    payload = TitanEmbeddingResponse.model_validate_json(
                        await response.body.read()
                    )
                    vector = payload.embedding
                    if len(vector) != self._config.dimensions:
                        raise _invalid_response(
                            "Bedrock returned a vector with unexpected dimensions."
                        )
                    vectors.append(vector)
            return vectors
        except EmbeddingError:
            raise
        except ClientError as error:
            raise _client_error(error) from None
        except BotoCoreError:
            raise EmbeddingError(
                "Bedrock embedding transport failed.",
                vendor=PROVIDER,
                code=EmbeddingErrorCode.TRANSPORT,
                retryable=True,
            ) from None
        except (TypeError, ValueError):
            raise _invalid_response("Bedrock returned an invalid response.") from None


def _client_error(error: ClientError) -> EmbeddingError:
    try:
        response = BedrockErrorResponse.model_validate(error.response)
    except ValidationError:
        return _invalid_response("Bedrock returned an invalid error response.")
    provider_code = response.error.code
    status = response.metadata.status
    if provider_code in {
        BedrockFailureCode.ACCESS_DENIED,
        BedrockFailureCode.EXPIRED_TOKEN,
        BedrockFailureCode.INVALID_SIGNATURE,
        BedrockFailureCode.UNRECOGNIZED_CLIENT,
    } or status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        code = EmbeddingErrorCode.AUTHENTICATION
        retryable = False
    elif provider_code in {
        BedrockFailureCode.THROTTLED,
        BedrockFailureCode.QUOTA_EXCEEDED,
    }:
        code = EmbeddingErrorCode.RATE_LIMITED
        retryable = True
    elif provider_code in {
        BedrockFailureCode.INTERNAL_SERVER,
        BedrockFailureCode.MODEL_NOT_READY,
        BedrockFailureCode.MODEL_TIMEOUT,
        BedrockFailureCode.SERVICE_UNAVAILABLE,
    } or (status is not None and status >= HTTPStatus.INTERNAL_SERVER_ERROR):
        code = EmbeddingErrorCode.PROVIDER_ERROR
        retryable = True
    else:
        code = EmbeddingErrorCode.INVALID_REQUEST
        retryable = False
    return EmbeddingError(
        "Bedrock rejected the embedding request.",
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
