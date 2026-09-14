"""Compose validated platform email values into socket adapter configs."""

from __future__ import annotations

from pydantic import SecretStr, ValidationError

from eylo.modules.email_configs.catalog import SMTPSecurity
from eylo.modules.email_configs.domain import (
    EmailProviderConfig,
    InvalidEmailConfig,
    SendGridMaterial,
)
from eylo.sockets.email.schemas import EmailConfig, SMTPConfig, SendGridConfig


def build_email_runtime_config(config: EmailProviderConfig) -> EmailConfig:
    material = config.material
    try:
        if isinstance(material, SendGridMaterial):
            return SendGridConfig(
                default_from_email=material.settings.default_from_email,
                default_from_name=material.settings.default_from_name,
                timeout=material.settings.timeout,
                api_key=SecretStr(material.credentials.api_key),
            )
        return SMTPConfig(
            default_from_email=material.settings.default_from_email,
            default_from_name=material.settings.default_from_name,
            timeout=material.settings.timeout,
            smtp_host=material.settings.smtp_host,
            smtp_port=material.settings.smtp_port,
            smtp_username=material.settings.smtp_username,
            smtp_security=(
                "implicit_tls"
                if material.settings.smtp_security is SMTPSecurity.IMPLICIT_TLS
                else "starttls"
            ),
            smtp_password=SecretStr(material.credentials.smtp_password),
        )
    except ValidationError:
        raise InvalidEmailConfig(
            f"Invalid runtime config for {config.provider.value}."
        ) from None
