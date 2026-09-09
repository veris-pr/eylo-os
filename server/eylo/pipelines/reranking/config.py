"""Translate validated reranking domain config into socket runtime config."""

from __future__ import annotations

from eylo.modules.reranking_configs.catalog import RerankingProviders
from eylo.modules.reranking_configs.domain import (
    ApiKeyRerankingCredentials,
    AwsRerankingCredentials,
    BedrockRerankingSettings,
    InvalidRerankingConfig,
    RerankingProviderConfig,
    ResolvedReranking,
)
from eylo.sockets.reranking.schemas import (
    BedrockRerankingConfig,
    RerankingConfig,
    RerankingRuntimeConfig,
)


def build_reranking_runtime_config(
    config: RerankingProviderConfig | ResolvedReranking,
) -> RerankingRuntimeConfig:
    config = type(config).model_validate(config)
    if config.provider is RerankingProviders.BEDROCK:
        if not isinstance(config.settings, BedrockRerankingSettings) or not isinstance(
            config.credentials, AwsRerankingCredentials
        ):
            raise InvalidRerankingConfig("Bedrock reranking material is invalid.")
        return BedrockRerankingConfig.model_validate(
            {
                "model": config.settings.model,
                "region": config.settings.region,
                "access_key_id": config.credentials.access_key_id,
                "secret_access_key": config.credentials.secret_access_key,
                "session_token": config.credentials.session_token,
            }
        )
    if not isinstance(config.credentials, ApiKeyRerankingCredentials):
        raise InvalidRerankingConfig("API-key reranking material is invalid.")
    return RerankingConfig(
        model=config.model,
        api_key=config.credentials.api_key,
        base_url=config.endpoint,
    )
