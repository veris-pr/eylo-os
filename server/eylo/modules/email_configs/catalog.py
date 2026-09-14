"""Email config catalog."""

from __future__ import annotations

from enum import Enum

__all__ = ["EmailProviders", "SMTPSecurity"]


class EmailProviders(str, Enum):
    SMTP = "smtp"
    SENDGRID = "sendgrid"


class SMTPSecurity(str, Enum):
    """Operator-selected authenticated SMTP transport security."""

    IMPLICIT_TLS = "implicit_tls"
    STARTTLS = "starttls"
