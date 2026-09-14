"""Provider-owned reranking material and immutable resolved runtime authority."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from types import MappingProxyType
from typing import Annotated, Self
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    Tag,
    ValidationError,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)
from eylo.modules.reranking_configs.catalog import (
    BEDROCK_RERANKING_MODELS,
    BEDROCK_RERANKING_REGIONS,
    RerankingProviders,
)

COHERE_API_URL = "https://api.cohere.com/v2/rerank"
VOYAGE_API_URL = "https://api.voyageai.com/v1/rerank"
MAX_MODEL_LENGTH = 255
MAX_REGION_LENGTH = 64
MAX_ACCESS_KEY_LENGTH = 512
MAX_SECRET_LENGTH = 8192
MAX_ENDPOINT_LENGTH = 2048
_AWS_REGION = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


class InvalidRerankingConfig(InvalidProviderConfig):
    """Invalid reranking material; messages never contain credential values."""


class _RerankingValue(BaseModel):
    """Private validated material, rechecked when copied objects cross boundaries."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        validate_by_name=True,
        validate_default=True,
    )


class RerankingEndpointPolicy(_RerankingValue):
    """Deployment-owned exact compatible endpoints trusted with org data/keys."""

    allowed_base_urls: frozenset[str] = frozenset()

    @field_validator("allowed_base_urls", mode="before")
    @classmethod
    def _urls(cls, value: object) -> frozenset[str]:
        if not isinstance(value, Collection) or isinstance(
            value, (str, bytes, Mapping)
        ):
            raise InvalidRerankingConfig(
                "Allowed reranking endpoints must be a collection."
            )
        return frozenset(
            _normalize_http_url(item, field_name="allowed base URL") for item in value
        )

    def require_allowed(self, value: object) -> str:
        policy = type(self).model_validate(self)
        normalized = _normalize_http_url(value, field_name="base_url")
        if normalized not in policy.allowed_base_urls:
            raise InvalidRerankingConfig(
                "base_url is not trusted by this deployment. Add the exact URL "
                "to RERANKING_BASE_URL_ALLOWLIST before storing org credentials."
            )
        return normalized


class RerankingModelSettings(_RerankingValue):
    """Model-only settings, currently used by Voyage."""

    model: str

    @field_validator("model", mode="before")
    @classmethod
    def _model(cls, value: object) -> str:
        return _required_string(value, "model", maximum=MAX_MODEL_LENGTH)


class CohereRerankingSettings(RerankingModelSettings):
    base_url: str | None = None


class BedrockRerankingSettings(RerankingModelSettings):
    region: str

    @field_validator("model")
    @classmethod
    def _supported_model(cls, value: str) -> str:
        if value not in BEDROCK_RERANKING_MODELS:
            raise InvalidRerankingConfig(
                "model is not a supported AWS Bedrock reranking model."
            )
        return value

    @field_validator("region", mode="before")
    @classmethod
    def _region(cls, value: object) -> str:
        region = _required_string(value, "region", maximum=MAX_REGION_LENGTH)
        if not _AWS_REGION.fullmatch(region):
            raise InvalidRerankingConfig("region is not a valid AWS region name.")
        return region

    @model_validator(mode="after")
    def _available_region(self) -> Self:
        if self.region not in BEDROCK_RERANKING_REGIONS[self.model]:
            raise InvalidRerankingConfig(
                "model is not available for reranking in the configured region."
            )
        return self


class ApiKeyRerankingCredentials(_RerankingValue):
    api_key: str = Field(repr=False, exclude=True)

    @field_validator("api_key", mode="before")
    @classmethod
    def _key(cls, value: object) -> str:
        return _required_string(value, "api_key", maximum=MAX_SECRET_LENGTH)


class AwsRerankingCredentials(_RerankingValue):
    access_key_id: str = Field(repr=False, exclude=True)
    secret_access_key: str = Field(repr=False, exclude=True)
    session_token: str | None = Field(default=None, repr=False, exclude=True)

    @field_validator(
        "access_key_id", "secret_access_key", "session_token", mode="before"
    )
    @classmethod
    def _secret(cls, value: object, info: ValidationInfo) -> str | None:
        if info.field_name == "session_token" and value is None:
            return None
        return _required_string(
            value,
            info.field_name or "credential",
            maximum=MAX_ACCESS_KEY_LENGTH
            if info.field_name == "access_key_id"
            else MAX_SECRET_LENGTH,
        )


def _reranking_settings_tag(value: object) -> str | None:
    """Tag already-parsed material; raw input is selected by its owning provider."""
    if type(value) is BedrockRerankingSettings:
        return RerankingProviders.BEDROCK.value
    if type(value) is CohereRerankingSettings:
        return RerankingProviders.COHERE.value
    if type(value) is RerankingModelSettings:
        return RerankingProviders.VOYAGE.value
    return None


def _reranking_settings_json_schema(schema: dict[str, JsonValue]) -> None:
    """Wire shapes overlap without a tag field; the parent provider selects one."""
    variants = schema.pop("oneOf", None)
    if variants is not None:
        schema["anyOf"] = variants


type RerankingSettings = Annotated[
    Annotated[BedrockRerankingSettings, Tag(RerankingProviders.BEDROCK.value)]
    | Annotated[CohereRerankingSettings, Tag(RerankingProviders.COHERE.value)]
    | Annotated[RerankingModelSettings, Tag(RerankingProviders.VOYAGE.value)],
    Discriminator(_reranking_settings_tag),
    Field(json_schema_extra=_reranking_settings_json_schema),
]


def parse_reranking_provider(value: object) -> RerankingProviders:
    """Normalize the existing provider vocabulary at API and domain boundaries."""
    if not isinstance(value, str):
        raise InvalidRerankingConfig("Reranking provider must be a string identifier.")
    try:
        return RerankingProviders(value.strip().lower())
    except ValueError:
        raise InvalidRerankingConfig("Reranking provider is not supported.") from None


def parse_reranking_settings(
    provider: RerankingProviders, value: object
) -> RerankingSettings:
    """Preserve provider-specific fields and refuse foreign settings models."""
    schema: type[RerankingSettings]
    if provider is RerankingProviders.BEDROCK:
        schema = BedrockRerankingSettings
    elif provider is RerankingProviders.COHERE:
        schema = CohereRerankingSettings
    elif provider is RerankingProviders.VOYAGE:
        schema = RerankingModelSettings
    else:
        raise InvalidRerankingConfig("Reranking provider is not supported.")
    if isinstance(value, BaseModel) and type(value) is not schema:
        raise InvalidRerankingConfig("Settings do not match the reranking provider.")
    return schema.model_validate(dict(value) if isinstance(value, Mapping) else value)


class RerankingProviderConfig(_RerankingValue):
    """Typed runtime material; mapping projections exist only for persistence."""

    provider: RerankingProviders
    settings: RerankingSettings = Field(validation_alias="config")
    credentials: AwsRerankingCredentials | ApiKeyRerankingCredentials = Field(
        validation_alias="secrets", repr=False, exclude=True
    )
    endpoint_policy: RerankingEndpointPolicy = Field(
        default_factory=RerankingEndpointPolicy, repr=False, exclude=True
    )

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidRerankingConfig(
                "Reranking configuration contains invalid fields or types."
            ) from None

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: object) -> RerankingProviders:
        return parse_reranking_provider(value)

    @field_validator("settings", mode="before")
    @classmethod
    def _settings(cls, value: object, info: ValidationInfo) -> RerankingSettings:
        provider = info.data.get("provider")
        if not isinstance(provider, RerankingProviders):
            raise InvalidRerankingConfig("Reranking provider is not supported.")
        return parse_reranking_settings(provider, value)

    @field_validator("credentials", mode="before")
    @classmethod
    def _credentials(
        cls, value: object, info: ValidationInfo
    ) -> AwsRerankingCredentials | ApiKeyRerankingCredentials:
        if isinstance(value, Mapping):
            value = dict(value)
        if info.data.get("provider") is RerankingProviders.BEDROCK:
            return AwsRerankingCredentials.model_validate(value)
        return ApiKeyRerankingCredentials.model_validate(value)

    @model_validator(mode="after")
    def _endpoint(self) -> Self:
        if (
            isinstance(self.settings, CohereRerankingSettings)
            and self.settings.base_url is not None
        ):
            normalized = self.endpoint_policy.require_allowed(self.settings.base_url)
            object.__setattr__(
                self,
                "settings",
                CohereRerankingSettings(model=self.settings.model, base_url=normalized),
            )
        return self

    @classmethod
    def from_input(
        cls,
        *,
        provider: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
        endpoint_policy: RerankingEndpointPolicy | None = None,
    ) -> Self:
        return cls.model_validate(
            {
                "provider": provider,
                "config": {} if config is None else config,
                "secrets": {} if secrets is None else secrets,
                "endpoint_policy": endpoint_policy or RerankingEndpointPolicy(),
            }
        )

    @property
    def config(self) -> Mapping[str, JsonValue]:
        return MappingProxyType(self.settings.model_dump(exclude_none=True))

    @property
    def secrets(self) -> Mapping[str, str]:
        if isinstance(self.credentials, AwsRerankingCredentials):
            values = {
                "access_key_id": self.credentials.access_key_id,
                "secret_access_key": self.credentials.secret_access_key,
            }
            if self.credentials.session_token is not None:
                values["session_token"] = self.credentials.session_token
            return MappingProxyType(values)
        return MappingProxyType({"api_key": self.credentials.api_key})

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def base_url(self) -> str | None:
        return (
            self.settings.base_url
            if isinstance(self.settings, CohereRerankingSettings)
            else None
        )

    @property
    def endpoint(self) -> str:
        if self.provider is RerankingProviders.COHERE:
            return self.base_url or COHERE_API_URL
        if self.provider is RerankingProviders.VOYAGE:
            return VOYAGE_API_URL
        if not isinstance(self.settings, BedrockRerankingSettings):
            raise InvalidRerankingConfig("Bedrock reranking settings are missing.")
        return _bedrock_endpoint(self.settings.region)


class RerankingVerificationMetadata(_RerankingValue):
    """Observed endpoint/model identity; unrelated stored metadata stays extensible."""

    endpoint: str | None = None
    model: str | None = None
    extensions: Mapping[str, JsonValue] = Field(default_factory=dict)

    @field_validator("extensions")
    @classmethod
    def _extensions(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType(dict(value))

    @field_serializer("extensions")
    def _serialize_extensions(
        self, value: Mapping[str, JsonValue]
    ) -> dict[str, JsonValue]:
        return dict(value)

    @classmethod
    def from_record(cls, value: Mapping[str, object]) -> Self:
        return cls.model_validate(
            {
                "endpoint": value.get("endpoint"),
                "model": value.get("model"),
                "extensions": {
                    key: item
                    for key, item in value.items()
                    if key not in {"endpoint", "model"}
                },
            }
        )

    def to_record(self) -> dict[str, JsonValue]:
        return dict(self.extensions) | {"endpoint": self.endpoint, "model": self.model}


class ResolvedReranking(RerankingProviderConfig):
    """Validated identity and material detached from the provider-config session."""

    provider_config_id: UUID
    provider_config_revision: int = Field(ge=1)
    organization_id: UUID
    verification_metadata: RerankingVerificationMetadata = Field(
        default_factory=RerankingVerificationMetadata
    )
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
        endpoint_policy: RerankingEndpointPolicy | None = None,
    ) -> Self:
        try:
            effective = EffectiveProviderConfig.model_validate(provider_config)
            metadata = RerankingVerificationMetadata.from_record(
                effective.verification_metadata
            )
        except (ValidationError, InvalidProviderConfig):
            raise InvalidRerankingConfig(
                "Resolved reranking configuration is invalid."
            ) from None
        if (
            effective.provider_config_id != provider_config_id
            or effective.organization_id != organization_id
            or effective.capability is not Capability.RERANKING
        ):
            raise InvalidRerankingConfig(
                "Resolved reranking authority does not match the requested organization/config."
            )
        return cls.model_validate(
            {
                "provider_config_id": provider_config_id,
                "provider_config_revision": effective.revision,
                "organization_id": organization_id,
                "provider": effective.provider,
                "config": effective.settings,
                "secrets": effective.secrets,
                "endpoint_policy": endpoint_policy or RerankingEndpointPolicy(),
                "verification_metadata": metadata,
                "configured": effective.configured,
                "verified": effective.verified,
                "ready": effective.ready,
                "granted": effective.granted,
            }
        )


def _required_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidRerankingConfig(f"{field_name} must be a string.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(character in normalized for character in ("\x00", "\r", "\n"))
    ):
        raise InvalidRerankingConfig(
            f"{field_name} must be a non-empty single-line string of at most "
            f"{maximum} characters."
        )
    return normalized


def _normalize_http_url(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_ENDPOINT_LENGTH
    ):
        raise InvalidRerankingConfig(
            f"{field_name} must be a non-empty HTTP(S) URL of at most {MAX_ENDPOINT_LENGTH} characters."
        )
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidRerankingConfig(
            f"{field_name} must be an HTTP(S) URL without credentials, query, or fragment."
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _bedrock_endpoint(region: str) -> str:
    return f"https://bedrock-agent-runtime.{region}.amazonaws.com"
