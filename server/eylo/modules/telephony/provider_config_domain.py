"""Strict telephony provider configuration and resolved runtime authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from ipaddress import ip_address
from types import MappingProxyType
from typing import Annotated, Literal, Self
from urllib.parse import urlparse
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from eylo.common.contracts.provider_config import Capability
from eylo.common.identifiers import normalize_uuid_like
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)

__all__ = [
    "InvalidTelephonyConfig",
    "ResolvedTelephony",
    "TelephonyOperation",
    "TelephonyProvider",
    "TelephonyProviderConfig",
    "supports_telephony_operation",
    "telephony_operation_matrix",
]


class TelephonyProvider(str, Enum):
    TWILIO = "twilio"
    PLIVO = "plivo"
    VONAGE = "vonage"
    EXOTEL = "exotel"


class TelephonyOperation(str, Enum):
    """Carrier operations exposed by the common telephony contract."""

    SEARCH_NUMBERS = "search_numbers"
    PURCHASE_NUMBER = "purchase_number"
    RELEASE_NUMBER = "release_number"
    INBOUND_CALL = "inbound_call"
    OUTBOUND_CALL = "outbound_call"
    BIDIRECTIONAL_MEDIA = "bidirectional_media"
    END_CALL = "end_call"
    TRANSFER_CALL = "transfer_call"
    RECEIVE_DTMF = "receive_dtmf"
    SEND_DTMF = "send_dtmf"
    AUTHENTICATED_STATUS_CALLBACK = "authenticated_status_callback"


_IMPLEMENTED_TELEPHONY_OPERATIONS = frozenset(TelephonyOperation) - {
    TelephonyOperation.RELEASE_NUMBER,
}
_EXOTEL_OPERATIONS = _IMPLEMENTED_TELEPHONY_OPERATIONS - {
    TelephonyOperation.TRANSFER_CALL,
    TelephonyOperation.AUTHENTICATED_STATUS_CALLBACK,
}
_PLIVO_OPERATIONS = _IMPLEMENTED_TELEPHONY_OPERATIONS - {
    TelephonyOperation.TRANSFER_CALL,
}
_OPERATIONS_BY_PROVIDER = MappingProxyType(
    {
        TelephonyProvider.TWILIO: _IMPLEMENTED_TELEPHONY_OPERATIONS,
        TelephonyProvider.PLIVO: _PLIVO_OPERATIONS,
        TelephonyProvider.VONAGE: _IMPLEMENTED_TELEPHONY_OPERATIONS,
        TelephonyProvider.EXOTEL: _EXOTEL_OPERATIONS,
    }
)


def supports_telephony_operation(
    provider: TelephonyProvider | str,
    operation: TelephonyOperation,
) -> bool:
    """Return whether one carrier implements an operation in this release."""
    return operation in _OPERATIONS_BY_PROVIDER[_provider(provider)]


def telephony_operation_matrix(
    provider: TelephonyProvider | str,
) -> dict[TelephonyOperation, bool]:
    """Return every common operation, including explicit unsupported entries."""
    supported = _OPERATIONS_BY_PROVIDER[_provider(provider)]
    return {operation: operation in supported for operation in TelephonyOperation}


class InvalidTelephonyConfig(InvalidProviderConfig):
    """Raised when a telephony provider config violates its contract."""


_HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])$"
)


MAX_APPLICATION_ID_LENGTH = 255
MAX_CREDENTIAL_LENGTH = 16_384
MAX_WEBHOOK_URL_LENGTH = 2_048
MAX_API_HOST_LENGTH = 253
EXOTEL_API_HOST = "api.exotel.com"
EXOTEL_HOST_SUFFIX = ".exotel.com"


class _TelephonyValue(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    @model_validator(mode="wrap")
    @classmethod
    def _safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidTelephonyConfig(
                "Telephony configuration contains invalid fields or types."
            ) from None


class WebhookSettings(_TelephonyValue):
    webhook_base_url: str

    @field_validator("webhook_base_url", mode="before")
    @classmethod
    def _webhook(cls, value: object) -> str:
        return _validate_https_url(value, "webhook_base_url")


class ApplicationSettings(WebhookSettings):
    application_id: str

    @field_validator("application_id", mode="before")
    @classmethod
    def _application(cls, value: object) -> str:
        return _validate_string(
            value, "application_id", maximum=MAX_APPLICATION_ID_LENGTH
        )


class ExotelAccountSettings(ApplicationSettings):
    api_host: str

    @field_validator("api_host", mode="before")
    @classmethod
    def _host(cls, value: object) -> str:
        return _validate_exotel_host(value)


class _Credentials(_TelephonyValue):
    @field_validator("*", mode="before")
    @classmethod
    def _credential(cls, value: object, info: ValidationInfo) -> str:
        return _validate_string(
            value, info.field_name or "credential", maximum=MAX_CREDENTIAL_LENGTH
        )


class TwilioCredentials(_Credentials):
    account_sid: str = Field(repr=False, exclude=True)
    auth_token: str = Field(repr=False, exclude=True)

    def secret_values(self) -> dict[str, str]:
        return {"account_sid": self.account_sid, "auth_token": self.auth_token}


class PlivoCredentials(_Credentials):
    auth_id: str = Field(repr=False, exclude=True)
    auth_token: str = Field(repr=False, exclude=True)

    def secret_values(self) -> dict[str, str]:
        return {"auth_id": self.auth_id, "auth_token": self.auth_token}


class VonageCredentials(_Credentials):
    api_key: str = Field(repr=False, exclude=True)
    api_secret: str = Field(repr=False, exclude=True)
    private_key: str = Field(repr=False, exclude=True)
    signature_secret: str = Field(repr=False, exclude=True)

    @field_validator("private_key")
    @classmethod
    def _private_key(cls, value: str) -> str:
        _validate_private_key(value)
        return value

    def secret_values(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "private_key": self.private_key,
            "signature_secret": self.signature_secret,
        }


class ExotelCredentials(_Credentials):
    api_key: str = Field(repr=False, exclude=True)
    api_token: str = Field(repr=False, exclude=True)
    account_sid: str = Field(repr=False, exclude=True)

    def secret_values(self) -> dict[str, str]:
        return {
            "api_key": self.api_key,
            "api_token": self.api_token,
            "account_sid": self.account_sid,
        }


class TwilioMaterial(_TelephonyValue):
    provider: Literal[TelephonyProvider.TWILIO] = TelephonyProvider.TWILIO
    settings: WebhookSettings
    credentials: TwilioCredentials = Field(repr=False, exclude=True)


class PlivoMaterial(_TelephonyValue):
    provider: Literal[TelephonyProvider.PLIVO] = TelephonyProvider.PLIVO
    settings: WebhookSettings
    credentials: PlivoCredentials = Field(repr=False, exclude=True)


class VonageMaterial(_TelephonyValue):
    provider: Literal[TelephonyProvider.VONAGE] = TelephonyProvider.VONAGE
    settings: ApplicationSettings
    credentials: VonageCredentials = Field(repr=False, exclude=True)


class ExotelMaterial(_TelephonyValue):
    provider: Literal[TelephonyProvider.EXOTEL] = TelephonyProvider.EXOTEL
    settings: ExotelAccountSettings
    credentials: ExotelCredentials = Field(repr=False, exclude=True)


type TelephonyMaterial = Annotated[
    TwilioMaterial | PlivoMaterial | VonageMaterial | ExotelMaterial,
    Field(discriminator="provider"),
]

_MATERIAL_TYPES = {
    TelephonyProvider.TWILIO: (WebhookSettings, TwilioCredentials),
    TelephonyProvider.PLIVO: (WebhookSettings, PlivoCredentials),
    TelephonyProvider.VONAGE: (ApplicationSettings, VonageCredentials),
    TelephonyProvider.EXOTEL: (ExotelAccountSettings, ExotelCredentials),
}


class TelephonyProviderConfig(_TelephonyValue):
    """Validated carrier material; mapping exports are explicit persistence boundaries."""

    material: TelephonyMaterial

    @model_validator(mode="after")
    def _matching_material(self) -> Self:
        """Reject foreign subclasses as well as malformed dictionary inputs."""
        expected_settings, expected_credentials = _MATERIAL_TYPES[
            self.material.provider
        ]
        if (
            type(self.material.settings) is not expected_settings
            or type(self.material.credentials) is not expected_credentials
        ):
            raise InvalidTelephonyConfig(
                "Telephony material does not match the provider."
            )
        return self

    @property
    def provider(self) -> TelephonyProvider:
        return self.material.provider

    @classmethod
    def from_payload(
        cls,
        *,
        provider: TelephonyProvider | str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> Self:
        if config is not None and not isinstance(config, Mapping):
            raise InvalidTelephonyConfig("Config must be a mapping.")
        if secrets is not None and not isinstance(secrets, Mapping):
            raise InvalidTelephonyConfig("Secrets must be a mapping.")
        return cls.model_validate(
            {
                "material": {
                    "provider": _provider(provider),
                    "settings": {} if config is None else dict(config),
                    "credentials": {} if secrets is None else dict(secrets),
                },
            }
        )

    def settings_values(self) -> dict[str, object]:
        return self.material.settings.model_dump(mode="json")

    def secret_values(self) -> dict[str, str]:
        """Export plaintext only for encrypted persistence or a resolved adapter invocation."""
        return self.material.credentials.secret_values()


class ResolvedTelephony(TelephonyProviderConfig):
    """Immutable, explicit carrier-account authority for runtime work."""

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @field_validator("provider_config_id", "organization_id", mode="before")
    @classmethod
    def _identifier(cls, value: object) -> object:
        return normalize_uuid_like(value)

    @classmethod
    def from_provider_config(
        cls,
        *,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedTelephony:
        effective = EffectiveProviderConfig.model_validate(provider_config)
        if (
            effective.capability is not Capability.TELEPHONY
            or effective.organization_id != organization_id
        ):
            raise InvalidTelephonyConfig(
                "Resolved telephony configuration authority does not match."
            )
        validated = TelephonyProviderConfig.from_payload(
            provider=effective.provider,
            config=effective.settings,
            secrets=effective.secrets,
        )
        return cls(
            material=validated.material,
            provider_config_id=effective.provider_config_id,
            provider_config_revision=effective.revision,
            organization_id=organization_id,
            configured=effective.configured,
            verified=effective.verified,
            ready=effective.ready,
            granted=effective.granted,
        )

    def as_provider_config(self) -> TelephonyProviderConfig:
        return TelephonyProviderConfig(material=self.material)


def _provider(value: TelephonyProvider | str) -> TelephonyProvider:
    if not isinstance(value, str):
        raise InvalidTelephonyConfig("Telephony provider must be a string identifier.")
    try:
        return TelephonyProvider(value.strip().lower())
    except ValueError:
        raise InvalidTelephonyConfig("Unsupported telephony provider.") from None


def _validate_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidTelephonyConfig(
            f"{field_name} must be a non-empty string of at most {maximum} characters."
        )
    return value.strip()


def _validate_https_url(value: object, field_name: str) -> str:
    text = _validate_string(value, field_name, maximum=MAX_WEBHOOK_URL_LENGTH).rstrip(
        "/"
    )
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidTelephonyConfig(
            f"{field_name} must be an HTTPS origin or path without credentials, query, or fragment."
        )
    _require_public_host(parsed.hostname, field_name)
    return text


def _validate_exotel_host(value: object) -> str:
    host = (
        _validate_string(value, "api_host", maximum=MAX_API_HOST_LENGTH)
        .lower()
        .rstrip(".")
    )
    _require_public_host(host, "api_host")
    if host != EXOTEL_API_HOST and not host.endswith(EXOTEL_HOST_SUFFIX):
        raise InvalidTelephonyConfig("api_host must be an Exotel API host.")
    return host


def _require_public_host(host: str, field_name: str) -> None:
    try:
        address = ip_address(host)
    except ValueError:
        if not _HOST_PATTERN.fullmatch(host.lower()):
            raise InvalidTelephonyConfig(
                f"{field_name} must contain a valid public host."
            ) from None
    else:
        if not address.is_global:
            raise InvalidTelephonyConfig(f"{field_name} must contain a public host.")


def _validate_private_key(value: str) -> None:
    try:
        serialization.load_pem_private_key(value.encode(), password=None)
    except (TypeError, ValueError):
        raise InvalidTelephonyConfig(
            "private_key must be an unencrypted PEM private key."
        ) from None
