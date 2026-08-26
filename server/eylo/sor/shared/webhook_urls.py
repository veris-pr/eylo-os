"""Public URL policy shared by managed and connector-owned SOR webhooks."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from eylo.common.config import settings
from eylo.sor.shared.services import SorConfigurationError


def public_webhook_api_base_url() -> str:
    """Return the public HTTPS API base accepted by external webhooks."""
    value = settings.API_BASE_URL
    if not isinstance(value, str) or not value.strip():
        raise SorConfigurationError(
            "API_BASE_URL must be configured before webhooks are enabled."
        )
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise SorConfigurationError(
            "API_BASE_URL must be a public HTTPS API base for webhooks."
        )
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SorConfigurationError(
            "API_BASE_URL must be publicly reachable for webhooks."
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return normalized
    if not address.is_global:
        raise SorConfigurationError(
            "API_BASE_URL must be publicly reachable for webhooks."
        )
    return normalized


__all__ = ["public_webhook_api_base_url"]
