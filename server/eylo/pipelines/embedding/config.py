"""Translate validated embedding domain config into socket runtime config."""

from __future__ import annotations

from eylo.modules.embedding_configs.catalog import EmbeddingProviders
from eylo.modules.embedding_configs.domain import (
    ApiKeyEmbeddingCredentials,
    AwsEmbeddingCredentials,
    BedrockEmbeddingSettings,
    EmbeddingProviderConfig,
    InvalidEmbeddingConfig,
    ResolvedEmbedding,
)
from eylo.sockets.embedding.schemas import (
    BedrockEmbeddingConfig,
    EmbeddingConfig,
    EmbeddingRuntimeConfig,
)


def build_embedding_runtime_config(
    config: EmbeddingProviderConfig | ResolvedEmbedding,
) -> EmbeddingRuntimeConfig:
    config = type(config).model_validate(config)
    if config.provider is EmbeddingProviders.BEDROCK:
        if not isinstance(config.settings, BedrockEmbeddingSettings) or not isinstance(
            config.credentials, AwsEmbeddingCredentials
        ):
            raise InvalidEmbeddingConfig("Bedrock embedding material is invalid.")
        return BedrockEmbeddingConfig.model_validate(
            {
                "model": config.settings.model,
                "region": config.settings.region,
                "dimensions": config.settings.dimensions,
                "normalize": config.settings.normalize,
                "access_key_id": config.credentials.access_key_id,
                "secret_access_key": config.credentials.secret_access_key,
                "session_token": config.credentials.session_token,
            }
        )
    if not isinstance(config.credentials, ApiKeyEmbeddingCredentials):
        raise InvalidEmbeddingConfig("API-key embedding material is invalid.")
    return EmbeddingConfig(
        model=config.model,
        api_key=config.credentials.api_key,
        base_url=config.base_url,
    )
