"""Typed email settings, private credentials and resolved provider authority."""

from __future__ import annotations

import re
from collections.abc import Mapping
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.identifiers import normalize_uuid_like
from eylo.modules.email_configs.catalog import EmailProviders, SMTPSecurity
from eylo.modules.provider_configs.constants import Capability
from eylo.modules.provider_configs.domain import (
    EffectiveProviderConfig,
    InvalidProviderConfig,
)

__all__ = [
    "EmailProviderConfig",
    "EmailSettings",
    "InvalidEmailConfig",
    "ResolvedEmail",
    "SendGridMaterial",
    "SMTPMaterial",
    "SMTPSettings",
]

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_HOST_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$"
)
_MAX_FROM_NAME_LENGTH = 255
_MAX_USERNAME_LENGTH = 320
_MAX_HOST_LENGTH = 253
_MAX_PORT = 65_535
_MAX_TIMEOUT_SECONDS = 60
_LOCAL_HOST_NAMES = frozenset({"localhost", "localhost.localdomain"})


class InvalidEmailConfig(InvalidProviderConfig):
    """Raised when an email provider config violates policy."""


class _EmailValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="wrap")
    @classmethod
    def safe_validation(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidEmailConfig(
                "Email configuration contains invalid fields or types."
            ) from None


class EmailSettings(_EmailValue):
    """Sender identity and bounded timeout shared by current email providers."""

    default_from_email: EmailStr
    default_from_name: str
    timeout: float = Field(gt=0, le=_MAX_TIMEOUT_SECONDS)

    @field_validator("default_from_email", mode="before")
    @classmethod
    def validate_sender(cls, value: object) -> EmailStr:
        if not isinstance(value, str):
            raise InvalidEmailConfig("default_from_email must be a valid email.")
        try:
            return _EMAIL_ADAPTER.validate_python(value)
        except ValidationError:
            raise InvalidEmailConfig(
                "default_from_email must be a valid email."
            ) from None

    @field_validator("default_from_name", mode="before")
    @classmethod
    def normalize_sender_name(cls, value: object) -> str:
        return _validate_string(
            value, "default_from_name", maximum=_MAX_FROM_NAME_LENGTH
        )

    @field_validator("timeout", mode="before")
    @classmethod
    def validate_timeout_type(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidEmailConfig("timeout must be a number.")
        return float(value)


class SMTPSettings(EmailSettings):
    """Public endpoint selection; DNS/IP checks at connect time remain mandatory."""

    smtp_host: str
    smtp_port: int = Field(ge=1, le=_MAX_PORT)
    smtp_username: str
    smtp_security: SMTPSecurity

    @field_validator("smtp_host", mode="before")
    @classmethod
    def normalize_host(cls, value: object) -> str:
        return _validate_smtp_host(value)

    @field_validator("smtp_username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> str:
        return _validate_string(value, "smtp_username", maximum=_MAX_USERNAME_LENGTH)

    @field_validator("smtp_security", mode="before")
    @classmethod
    def validate_security(cls, value: object) -> SMTPSecurity:
        if not isinstance(value, str):
            raise InvalidEmailConfig("smtp_security must be implicit_tls or starttls.")
        try:
            return SMTPSecurity(value)
        except ValueError:
            raise InvalidEmailConfig(
                "smtp_security must be implicit_tls or starttls."
            ) from None


class _Credentials(_EmailValue):
    @field_validator("*", mode="before")
    @classmethod
    def validate_credential(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidEmailConfig("Email credentials must be non-empty strings.")
        return value


class SendGridCredentials(_Credentials):
    api_key: str = Field(repr=False, exclude=True)

    def secret_values(self) -> dict[str, str]:
        return {"api_key": self.api_key}


class SMTPCredentials(_Credentials):
    smtp_password: str = Field(repr=False, exclude=True)

    def secret_values(self) -> dict[str, str]:
        return {"smtp_password": self.smtp_password}


class SendGridMaterial(_EmailValue):
    provider: Literal[EmailProviders.SENDGRID] = EmailProviders.SENDGRID
    settings: EmailSettings
    credentials: SendGridCredentials = Field(repr=False, exclude=True)


class SMTPMaterial(_EmailValue):
    provider: Literal[EmailProviders.SMTP] = EmailProviders.SMTP
    settings: SMTPSettings
    credentials: SMTPCredentials = Field(repr=False, exclude=True)


EmailMaterial = Annotated[
    SendGridMaterial | SMTPMaterial, Field(discriminator="provider")
]


class EmailProviderConfig(_EmailValue):
    """Typed in-process material; export mappings only at persistence boundaries."""

    material: EmailMaterial

    @model_validator(mode="after")
    def validate_material(self) -> Self:
        if isinstance(self.material, SendGridMaterial):
            valid = (
                type(self.material.settings) is EmailSettings
                and type(self.material.credentials) is SendGridCredentials
            )
        else:
            valid = (
                type(self.material.settings) is SMTPSettings
                and type(self.material.credentials) is SMTPCredentials
            )
        if not valid:
            raise InvalidEmailConfig("Email material does not match the provider.")
        return self

    @property
    def provider(self) -> EmailProviders:
        return self.material.provider

    @classmethod
    def from_payload(
        cls,
        *,
        provider: EmailProviders | str,
        config: Mapping[str, object] | None = None,
        secrets: Mapping[str, str] | None = None,
    ) -> Self:
        if not isinstance(provider, str):
            raise InvalidEmailConfig("Unsupported email provider.")
        try:
            selected_provider = EmailProviders(provider.strip().lower())
        except ValueError:
            raise InvalidEmailConfig("Unsupported email provider.") from None
        if config is not None and not isinstance(config, Mapping):
            raise InvalidEmailConfig("Config must be a mapping.")
        if secrets is not None and not isinstance(secrets, Mapping):
            raise InvalidEmailConfig("Secrets must be a mapping.")
        return cls.model_validate(
            {
                "material": {
                    "provider": selected_provider,
                    "settings": {} if config is None else dict(config),
                    "credentials": {} if secrets is None else dict(secrets),
                }
            }
        )

    def settings_values(self) -> dict[str, JsonValue]:
        return self.material.settings.model_dump(mode="json")

    def secret_values(self) -> dict[str, str]:
        """Export plaintext only for encrypted persistence or adapter invocation."""
        return self.material.credentials.secret_values()


class ResolvedEmail(EmailProviderConfig):
    """Email material pinned to one organization's exact provider revision."""

    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    organization_id: UUID
    configured: bool = True
    verified: bool = False
    ready: bool = False
    granted: bool = False

    @field_validator("provider_config_id", "organization_id", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> object:
        return normalize_uuid_like(value)

    @classmethod
    def from_provider_config(
        cls,
        *,
        provider_config_id: UUID,
        organization_id: UUID,
        provider_config: EffectiveProviderConfig,
    ) -> ResolvedEmail:
        effective = EffectiveProviderConfig.model_validate(provider_config)
        if (
            effective.capability is not Capability.EMAIL
            or effective.organization_id != organization_id
            or effective.provider_config_id != provider_config_id
        ):
            raise InvalidEmailConfig(
                "Resolved email configuration authority does not match."
            )
        validated = EmailProviderConfig.from_payload(
            provider=effective.provider,
            config=effective.settings,
            secrets=effective.secrets,
        )
        return cls(
            material=validated.material,
            provider_config_id=provider_config_id,
            provider_config_revision=effective.revision,
            organization_id=organization_id,
            configured=effective.configured,
            verified=effective.verified,
            ready=effective.ready,
            granted=effective.granted,
        )

    def as_provider_config(self) -> EmailProviderConfig:
        return EmailProviderConfig(material=self.material)


def _validate_string(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidEmailConfig(
            f"{field_name} must be a non-empty string of at most {maximum} characters."
        )
    return value.strip()


def _validate_smtp_host(value: object) -> str:
    host = (
        _validate_string(value, "smtp_host", maximum=_MAX_HOST_LENGTH)
        .lower()
        .rstrip(".")
    )
    if host in _LOCAL_HOST_NAMES:
        raise InvalidEmailConfig("smtp_host must be a public host.")
    try:
        address = ip_address(host)
    except ValueError:
        if "." not in host or not _HOST_PATTERN.fullmatch(host):
            raise InvalidEmailConfig("smtp_host must be a valid public host.") from None
    else:
        if not address.is_global:
            raise InvalidEmailConfig("smtp_host must be a public host.")
    return host
