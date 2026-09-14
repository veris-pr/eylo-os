"""Platform validation and immutable resolved WebRTC configuration material."""

from __future__ import annotations

import re
from collections.abc import Mapping
from ipaddress import ip_address
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    ModelWrapValidatorHandler,
    Tag,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)
from eylo.modules.webrtc_configs.catalog import WebRTCProviders

API_KEY_FIELD = "api_key"
METERED_DOMAIN_SUFFIX = ".metered.live"
METERED_APP_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$")
MAX_TIMEOUT_SECONDS = 30
MAX_RETRIES = 5
MAX_RETRY_DELAY_SECONDS = 10
MAX_TTL_SECONDS = 86_400
MAX_CLIENT_CONTEXT_LENGTH = 255
MAX_REGION_LENGTH = 64


class InvalidWebRTCConfig(InvalidProviderConfig):
    """Invalid platform material; messages never contain credential values."""


class _WebRTCValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
        validate_default=True,
    )

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError as error:
            fields = {
                location
                for item in error.errors(include_input=False, include_context=False)
                if item["loc"]
                and isinstance(location := item["loc"][0], str)
                and location in cls.model_fields
            }
            label = ", ".join(sorted(fields)) or "configuration fields"
            raise InvalidWebRTCConfig(f"Invalid WebRTC {label}.") from None


class WebRTCRequestSettings(_WebRTCValue):
    """Optional operator overrides; omitted values retain socket transport defaults."""

    timeout: float | None = Field(default=None, gt=0, le=MAX_TIMEOUT_SECONDS)
    max_retries: int | None = Field(default=None, ge=0, le=MAX_RETRIES)
    retry_delay: float | None = Field(default=None, ge=0, le=MAX_RETRY_DELAY_SECONDS)


class MeteredWebRTCSettings(WebRTCRequestSettings):
    app_name: str

    @field_validator("app_name", mode="before")
    @classmethod
    def _app_name(cls, value: object) -> str:
        if isinstance(value, str):
            app_name = value.strip().lower()
            if app_name.endswith(METERED_DOMAIN_SUFFIX):
                app_name = app_name[: -len(METERED_DOMAIN_SUFFIX)]
            if METERED_APP_NAME_PATTERN.fullmatch(app_name):
                return app_name
        raise InvalidWebRTCConfig(
            "Metered domain must be the value shown in the Metered dashboard "
            "(for example, your_app.metered.live) or its app name."
        )


class TurnixWebRTCSettings(WebRTCRequestSettings):
    initiator_client: str | None = Field(
        default=None, max_length=MAX_CLIENT_CONTEXT_LENGTH
    )
    receiver_client: str | None = Field(
        default=None, max_length=MAX_CLIENT_CONTEXT_LENGTH
    )
    room: str | None = Field(default=None, max_length=MAX_CLIENT_CONTEXT_LENGTH)
    ttl: int | None = Field(default=None, gt=0, le=MAX_TTL_SECONDS)
    preferred_region: str | None = Field(default=None, max_length=MAX_REGION_LENGTH)
    fixed_region: str | None = Field(default=None, max_length=MAX_REGION_LENGTH)
    client_ip: str | None = None

    @field_validator(
        "initiator_client",
        "receiver_client",
        "room",
        "preferred_region",
        "fixed_region",
    )
    @classmethod
    def _context(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise InvalidWebRTCConfig(
                "Turnix context fields must be non-empty strings."
            )
        return value

    @field_validator("client_ip")
    @classmethod
    def _client_ip(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ip_address(value)
            except ValueError:
                raise InvalidWebRTCConfig(
                    "client_ip must be a valid IPv4 or IPv6 address."
                ) from None
        return value


class WebRTCCredentials(_WebRTCValue):
    api_key: str = Field(repr=False, exclude=True)

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not value.strip():
            raise InvalidWebRTCConfig("WebRTC requires a non-empty api_key secret.")
        return value

    def secret_values(self) -> dict[str, str]:
        """Explicit plaintext export for encrypted persistence or adapter invocation."""
        return {API_KEY_FIELD: self.api_key}


def _settings_kind(value: object) -> WebRTCProviders | None:
    """Select one settings validator before converting its errors to domain errors."""
    if isinstance(value, MeteredWebRTCSettings):
        return WebRTCProviders.METERED
    if isinstance(value, TurnixWebRTCSettings):
        return WebRTCProviders.TURNIX
    if isinstance(value, Mapping):
        return (
            WebRTCProviders.METERED if "app_name" in value else WebRTCProviders.TURNIX
        )
    return None


type WebRTCSettings = Annotated[
    Annotated[MeteredWebRTCSettings, Tag(WebRTCProviders.METERED)]
    | Annotated[TurnixWebRTCSettings, Tag(WebRTCProviders.TURNIX)],
    Discriminator(_settings_kind),
]


class WebRTCProviderConfig(_WebRTCValue):
    """Validated platform material; vendor SDK types never cross into the module."""

    provider: WebRTCProviders
    config: WebRTCSettings
    credentials: WebRTCCredentials = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def _matching_settings(self) -> Self:
        matches = (
            self.provider is WebRTCProviders.METERED
            and isinstance(self.config, MeteredWebRTCSettings)
        ) or (
            self.provider is WebRTCProviders.TURNIX
            and isinstance(self.config, TurnixWebRTCSettings)
        )
        if not matches:
            raise InvalidWebRTCConfig("WebRTC provider and settings do not match.")
        return self

    @classmethod
    def from_payload(
        cls,
        *,
        provider: str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> WebRTCProviderConfig:
        if not isinstance(provider, str):
            raise InvalidWebRTCConfig("Unknown WebRTC provider.")
        try:
            selected = WebRTCProviders(provider.strip().lower())
        except ValueError:
            raise InvalidWebRTCConfig("Unknown WebRTC provider.") from None
        values = {} if config is None else dict(config)
        settings = (
            MeteredWebRTCSettings.model_validate(values)
            if selected is WebRTCProviders.METERED
            else TurnixWebRTCSettings.model_validate(values)
        )
        return WebRTCProviderConfig(
            provider=selected,
            config=settings,
            credentials=WebRTCCredentials.model_validate(
                {} if secrets is None else dict(secrets)
            ),
        )

    def settings_values(self) -> dict[str, object]:
        """Preserve omission when persisting; transport defaults are not new settings."""
        return self.config.model_dump(mode="json", exclude_unset=True)

    @property
    def secret(self) -> str:
        return self.credentials.api_key


class ResolvedWebRTC(WebRTCProviderConfig):
    """Pinned org authority plus validated material; credentials do not serialize."""

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
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
    ) -> ResolvedWebRTC:
        effective = EffectiveProviderConfig.model_validate(provider_config)
        if (
            effective.capability is not Capability.WEBRTC
            or effective.organization_id != organization_id
            or effective.provider_config_id != provider_config_id
        ):
            raise InvalidWebRTCConfig(
                "Resolved WebRTC configuration authority does not match."
            )
        validated = WebRTCProviderConfig.from_payload(
            provider=effective.provider,
            config=effective.settings,
            secrets=effective.secrets,
        )
        return cls(
            provider_config_id=provider_config_id,
            provider_config_revision=effective.revision,
            organization_id=organization_id,
            provider=validated.provider,
            config=validated.config,
            credentials=validated.credentials,
            configured=effective.configured,
            verified=effective.verified,
            ready=effective.ready,
            granted=effective.granted,
        )
