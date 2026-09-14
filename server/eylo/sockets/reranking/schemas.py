"""Runtime configs plus vendor-neutral reranking exports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from eylo.common.contracts import reranking as reranking_contracts

RerankResult = reranking_contracts.RerankResult
RerankingCapabilities = reranking_contracts.RerankingCapabilities
RerankingConfig = reranking_contracts.RerankingConfig
RerankingError = reranking_contracts.RerankingError
RerankingErrorCode = reranking_contracts.RerankingErrorCode
RerankingRecovery = reranking_contracts.RerankingRecovery
RerankingTruncation = reranking_contracts.RerankingTruncation


class BedrockRerankingConfig(BaseModel):
    """Explicit AWS Bedrock Agent Runtime reranking configuration."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    model: Literal["amazon.rerank-v1:0", "cohere.rerank-v3-5:0"]
    region: str = Field(
        min_length=5,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)+$",
    )
    access_key_id: SecretStr = Field(
        min_length=1, max_length=512, repr=False, exclude=True
    )
    secret_access_key: SecretStr = Field(
        min_length=1, max_length=8192, repr=False, exclude=True
    )
    session_token: SecretStr | None = Field(
        default=None, max_length=8192, repr=False, exclude=True
    )


RerankingRuntimeConfig = RerankingConfig | BedrockRerankingConfig
