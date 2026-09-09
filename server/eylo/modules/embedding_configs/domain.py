"""Provider-owned embedding material and immutable resolved runtime authority."""

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

from eylo.modules.embedding_configs.catalog import (
    BEDROCK_EMBEDDING_DIMENSIONS,
    BEDROCK_EMBEDDING_MODELS,
    EmbeddingProviders,
)
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
MAX_MODEL_LENGTH = 255
MAX_REGION_LENGTH = 64
MAX_ACCESS_KEY_LENGTH = 512
MAX_SECRET_LENGTH = 8192
MAX_ENDPOINT_LENGTH = 2048
_AWS_REGION = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")


class InvalidEmbeddingConfig(InvalidProviderConfig):
    """Invalid embedding material; messages never include credential values."""


class _EmbeddingValue(BaseModel):
    """Revalidate copied material at boundaries and keep validation failures safe."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        validate_by_name=True,
        validate_default=True,
    )


class EmbeddingEndpointPolicy(_EmbeddingValue):
    """Deployment-owned exact custom endpoints trusted to receive org data/keys."""

    allowed_base_urls: frozenset[str] = frozenset()

    @field_validator("allowed_base_urls", mode="before")
    @classmethod
    def _urls(cls, value: object) -> frozenset[str]:
        if not isinstance(value, Collection) or isinstance(
            value, (str, bytes, Mapping)
        ):
            raise InvalidEmbeddingConfig(
                "Allowed embedding endpoints must be a collection."
            )
        return frozenset(
            _normalize_http_url(item, field_name="allowed base URL") for item in value
        )

    def require_allowed(self, value: object) -> str:
        policy = type(self).model_validate(self)
        normalized = _normalize_http_url(value, field_name="base_url")
        if normalized not in policy.allowed_base_urls:
            raise InvalidEmbeddingConfig(
                "base_url is not trusted by this deployment. Add the exact URL to EMBEDDING_BASE_URL_ALLOWLIST before storing org credentials."
            )
        return normalized


class EmbeddingModelSettings(_EmbeddingValue):
    """Model-only settings, currently used by Voyage."""

    model: str

    @field_validator("model", mode="before")
    @classmethod
    def _model(cls, value: object) -> str:
        return _required_string(value, "model", maximum=MAX_MODEL_LENGTH)


class OpenAIEmbeddingSettings(EmbeddingModelSettings):
    base_url: str | None = None


class BedrockEmbeddingSettings(EmbeddingModelSettings):
    region: str
    dimensions: int
    normalize: bool

    @field_validator("model")
    @classmethod
    def _supported_model(cls, value: str) -> str:
        if value not in BEDROCK_EMBEDDING_MODELS:
            raise InvalidEmbeddingConfig(
                "model is not a supported AWS Bedrock embedding model."
            )
        return value

    @field_validator("region", mode="before")
    @classmethod
    def _region(cls, value: object) -> str:
        region = _required_string(value, "region", maximum=MAX_REGION_LENGTH)
        if not _AWS_REGION.fullmatch(region):
            raise InvalidEmbeddingConfig("region is not a valid AWS region name.")
        return region

    @field_validator("dimensions")
    @classmethod
    def _dimensions(cls, value: int) -> int:
        if value not in BEDROCK_EMBEDDING_DIMENSIONS:
            raise InvalidEmbeddingConfig(
                "dimensions is not a supported Bedrock embedding size."
            )
        return value


class ApiKeyEmbeddingCredentials(_EmbeddingValue):
    api_key: str = Field(repr=False, exclude=True)

    @field_validator("api_key", mode="before")
    @classmethod
    def _key(cls, value: object) -> str:
        return _required_string(value, "api_key", maximum=MAX_SECRET_LENGTH)


class AwsEmbeddingCredentials(_EmbeddingValue):
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


def _embedding_settings_tag(value: object) -> str | None:
    """Tag already-parsed material; raw input is selected by its owning provider."""
    if type(value) is BedrockEmbeddingSettings:
        return EmbeddingProviders.BEDROCK.value
    if type(value) is OpenAIEmbeddingSettings:
        return EmbeddingProviders.OPENAI.value
    if type(value) is EmbeddingModelSettings:
        return EmbeddingProviders.VOYAGE.value
    return None


def _embedding_settings_json_schema(schema: dict[str, JsonValue]) -> None:
    """Wire shapes overlap without a tag field; the parent provider selects one."""
    variants = schema.pop("oneOf", None)
    if variants is not None:
        schema["anyOf"] = variants


type EmbeddingSettings = Annotated[
    Annotated[BedrockEmbeddingSettings, Tag(EmbeddingProviders.BEDROCK.value)]
    | Annotated[OpenAIEmbeddingSettings, Tag(EmbeddingProviders.OPENAI.value)]
    | Annotated[EmbeddingModelSettings, Tag(EmbeddingProviders.VOYAGE.value)],
    Discriminator(_embedding_settings_tag),
    Field(json_schema_extra=_embedding_settings_json_schema),
]


def parse_embedding_provider(value: object) -> EmbeddingProviders:
    """Normalize the existing provider vocabulary at API and domain boundaries."""
    if not isinstance(value, str):
        raise InvalidEmbeddingConfig("Embedding provider must be a string identifier.")
    try:
        return EmbeddingProviders(value.strip().lower())
    except ValueError:
        raise InvalidEmbeddingConfig("Embedding provider is not supported.") from None


def parse_embedding_settings(
    provider: EmbeddingProviders, value: object
) -> EmbeddingSettings:
    """Select by provider, not by whichever overlapping model validates first."""
    if isinstance(value, Mapping):
        value = dict(value)
    if provider is EmbeddingProviders.BEDROCK:
        return BedrockEmbeddingSettings.model_validate(value)
    if provider is EmbeddingProviders.OPENAI:
        return OpenAIEmbeddingSettings.model_validate(value)
    if provider is EmbeddingProviders.VOYAGE:
        return EmbeddingModelSettings.model_validate(value)
    raise InvalidEmbeddingConfig("Embedding provider is not supported.")


class EmbeddingProviderConfig(_EmbeddingValue):
    """Typed material with explicit mapping projections only for persistence."""

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidEmbeddingConfig(
                "Embedding configuration contains invalid fields or types."
            ) from None

    provider: EmbeddingProviders
    settings: EmbeddingSettings = Field(validation_alias="config")
    credentials: AwsEmbeddingCredentials | ApiKeyEmbeddingCredentials = Field(
        validation_alias="secrets", repr=False, exclude=True
    )
    endpoint_policy: EmbeddingEndpointPolicy = Field(
        default_factory=EmbeddingEndpointPolicy, repr=False, exclude=True
    )

    @field_validator("provider", mode="before")
    @classmethod
    def _provider(cls, value: object) -> EmbeddingProviders:
        return parse_embedding_provider(value)

    @field_validator("settings", mode="before")
    @classmethod
    def _settings(cls, value: object, info: ValidationInfo) -> EmbeddingSettings:
        provider = info.data.get("provider")
        if not isinstance(provider, EmbeddingProviders):
            raise InvalidEmbeddingConfig("Embedding provider is not supported.")
        return parse_embedding_settings(provider, value)

    @field_validator("credentials", mode="before")
    @classmethod
    def _credentials(
        cls, value: object, info: ValidationInfo
    ) -> AwsEmbeddingCredentials | ApiKeyEmbeddingCredentials:
        if isinstance(value, Mapping):
            value = dict(value)
        if info.data.get("provider") is EmbeddingProviders.BEDROCK:
            return AwsEmbeddingCredentials.model_validate(value)
        return ApiKeyEmbeddingCredentials.model_validate(value)

    @model_validator(mode="after")
    def _endpoint(self) -> Self:
        if (
            isinstance(self.settings, OpenAIEmbeddingSettings)
            and self.settings.base_url is not None
        ):
            normalized = self.endpoint_policy.require_allowed(self.settings.base_url)
            object.__setattr__(
                self,
                "settings",
                OpenAIEmbeddingSettings(model=self.settings.model, base_url=normalized),
            )
        return self

    @classmethod
    def from_input(
        cls,
        *,
        provider: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
        endpoint_policy: EmbeddingEndpointPolicy | None = None,
    ) -> Self:
        return cls.model_validate(
            {
                "provider": provider,
                "config": {} if config is None else config,
                "secrets": {} if secrets is None else secrets,
                "endpoint_policy": endpoint_policy or EmbeddingEndpointPolicy(),
            }
        )

    @property
    def config(self) -> Mapping[str, JsonValue]:
        return MappingProxyType(self.settings.model_dump(exclude_none=True))

    @property
    def secrets(self) -> Mapping[str, str]:
        if isinstance(self.credentials, AwsEmbeddingCredentials):
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
            if isinstance(self.settings, OpenAIEmbeddingSettings)
            else None
        )

    @property
    def endpoint(self) -> str:
        if self.provider is EmbeddingProviders.OPENAI:
            return self.base_url or OPENAI_API_BASE_URL
        if self.provider is EmbeddingProviders.VOYAGE:
            return VOYAGE_API_URL
        if not isinstance(self.settings, BedrockEmbeddingSettings):
            raise InvalidEmbeddingConfig("Bedrock embedding settings are missing.")
        return _bedrock_endpoint(self.settings.region)


class EmbeddingVerificationMetadata(_EmbeddingValue):
    """Known observed shape and identity; future JSON extensions remain supported."""

    dimensions: int | None = Field(default=None, ge=1)
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
                "dimensions": value.get("dimensions"),
                "endpoint": value.get("endpoint"),
                "model": value.get("model"),
                "extensions": {
                    key: item
                    for key, item in value.items()
                    if key not in {"dimensions", "endpoint", "model"}
                },
            }
        )


class ResolvedEmbedding(EmbeddingProviderConfig):
    """Validated identity and material detached from the provider-config session."""

    provider_config_id: UUID
    provider_config_revision: int = Field(ge=1)
    organization_id: UUID
    verification_metadata: EmbeddingVerificationMetadata = Field(
        default_factory=EmbeddingVerificationMetadata
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
        endpoint_policy: EmbeddingEndpointPolicy | None = None,
    ) -> Self:
        effective = EffectiveProviderConfig.model_validate(provider_config)
        if (
            effective.provider_config_id != provider_config_id
            or effective.organization_id != organization_id
            or effective.capability is not Capability.EMBEDDING
        ):
            raise InvalidEmbeddingConfig(
                "Resolved embedding authority does not match the requested organization/config."
            )
        return cls.model_validate(
            {
                "provider_config_id": provider_config_id,
                "provider_config_revision": effective.revision,
                "organization_id": organization_id,
                "provider": effective.provider,
                "config": effective.settings,
                "secrets": effective.secrets,
                "endpoint_policy": endpoint_policy or EmbeddingEndpointPolicy(),
                "verification_metadata": EmbeddingVerificationMetadata.from_record(
                    effective.verification_metadata
                ),
                "configured": effective.configured,
                "verified": effective.verified,
                "ready": effective.ready,
                "granted": effective.granted,
            }
        )

    @property
    def dimensions(self) -> int:
        if self.verification_metadata.dimensions is None:
            raise InvalidEmbeddingConfig(
                "Verified embedding config is missing its observed dimensions."
            )
        return self.verification_metadata.dimensions


def _required_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidEmbeddingConfig(f"{field_name} must be a string.")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(character in normalized for character in ("\x00", "\r", "\n"))
    ):
        raise InvalidEmbeddingConfig(
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
        raise InvalidEmbeddingConfig(
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
        raise InvalidEmbeddingConfig(
            f"{field_name} must be an HTTP(S) URL without credentials, query, or fragment."
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _bedrock_endpoint(region: str) -> str:
    return f"https://bedrock-runtime.{region}.amazonaws.com"
