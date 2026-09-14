"""AWS Bedrock Agent Runtime reranking adapter."""

from __future__ import annotations

from http import HTTPStatus

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from eylo.sockets.reranking.base import RerankingVendorAdapter
from eylo.sockets.reranking.schemas import (
    BedrockRerankingConfig,
    RerankResult,
    RerankingCapabilities,
    RerankingError,
    RerankingErrorCode,
    RerankingRecovery,
    RerankingTruncation,
)
from eylo.sockets.reranking.validation import (
    validate_rerank_request,
    validate_rerank_results,
)
from eylo.sockets.reranking.vendors.bedrock_wire import (
    BEDROCK_AGENT_RUNTIME_SERVICE,
    MAX_DOCUMENTS,
    MAX_RESPONSE_PAGES,
    BedrockErrorResponse,
    BedrockFailureCode,
    BedrockRerankRequest,
    BedrockRerankResponse,
)

PROVIDER = "bedrock"


class BedrockRerankAdapter(RerankingVendorAdapter):
    """Rerank inline text through one explicitly selected Bedrock model."""

    def __init__(self, config: BedrockRerankingConfig) -> None:
        config = BedrockRerankingConfig.model_validate(config)
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
    def capabilities(self) -> RerankingCapabilities:
        return RerankingCapabilities(
            max_documents=MAX_DOCUMENTS, truncation=RerankingTruncation.ALLOWED
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
            request = BedrockRerankRequest(
                query=query,
                documents=tuple(documents),
                model_arn=self._model_arn,
                number_of_results=expected_count,
            )
        except ValidationError:
            raise RerankingError(
                "Bedrock reranking request is invalid.",
                vendor=PROVIDER,
                code=RerankingErrorCode.INVALID_REQUEST,
            ) from None
        try:
            entries: list[RerankResult] = []
            seen_tokens: set[str] = set()
            async with self._session.client(BEDROCK_AGENT_RUNTIME_SERVICE) as client:
                for _page_number in range(MAX_RESPONSE_PAGES):
                    response = BedrockRerankResponse.model_validate(
                        await client.rerank(**request.to_payload())
                    )
                    entries.extend(
                        RerankResult(index=item.index, score=item.relevance_score)
                        for item in response.results
                    )
                    if len(entries) > expected_count:
                        raise _invalid_response()
                    if response.next_token is None:
                        break
                    if response.next_token in seen_tokens:
                        raise _invalid_response()
                    seen_tokens.add(response.next_token)
                    request = request.model_copy(
                        update={"next_token": response.next_token}
                    )
                else:
                    raise _invalid_response()
            return validate_rerank_results(
                entries,
                expected_count=expected_count,
                candidate_count=len(documents),
                vendor=PROVIDER,
            )
        except RerankingError:
            raise
        except ValidationError:
            raise _invalid_response() from None
        except ClientError as error:
            raise _client_error(error) from None
        except BotoCoreError:
            raise RerankingError(
                "Bedrock reranking transport failed.",
                vendor=PROVIDER,
                code=RerankingErrorCode.TRANSPORT,
                recovery=RerankingRecovery.RETRY,
            ) from None

    @property
    def _model_arn(self) -> str:
        return (
            f"arn:aws:bedrock:{self._config.region}::foundation-model/"
            f"{self._config.model}"
        )


def _client_error(error: ClientError) -> RerankingError:
    try:
        response = BedrockErrorResponse.model_validate(error.response)
    except ValidationError:
        return _invalid_response()
    provider_code = response.error.code
    status = response.metadata.status
    if provider_code in {
        BedrockFailureCode.ACCESS_DENIED,
        BedrockFailureCode.EXPIRED_TOKEN,
        BedrockFailureCode.INVALID_SIGNATURE,
        BedrockFailureCode.UNRECOGNIZED_CLIENT,
    } or status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        code = RerankingErrorCode.AUTHENTICATION
        recovery = RerankingRecovery.TERMINAL
    elif provider_code in {
        BedrockFailureCode.THROTTLED,
        BedrockFailureCode.QUOTA_EXCEEDED,
    }:
        code = RerankingErrorCode.RATE_LIMITED
        recovery = RerankingRecovery.RETRY
    elif provider_code in {
        BedrockFailureCode.INTERNAL_SERVER,
        BedrockFailureCode.MODEL_NOT_READY,
        BedrockFailureCode.SERVICE_UNAVAILABLE,
    } or (status is not None and status >= HTTPStatus.INTERNAL_SERVER_ERROR):
        code = RerankingErrorCode.PROVIDER_UNAVAILABLE
        recovery = RerankingRecovery.RETRY
    else:
        code = RerankingErrorCode.INVALID_REQUEST
        recovery = RerankingRecovery.TERMINAL
    return RerankingError(
        "Bedrock rejected the reranking request.",
        vendor=PROVIDER,
        code=code,
        recovery=recovery,
    )


def _invalid_response() -> RerankingError:
    return RerankingError(
        "Bedrock returned an invalid reranking response.",
        vendor=PROVIDER,
        code=RerankingErrorCode.INVALID_RESPONSE,
        recovery=RerankingRecovery.RETRY,
    )
