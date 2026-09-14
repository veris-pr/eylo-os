"""Slack workspace bot identity and documented OAuth scopes."""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import VendorAuthKind

from ...contracts import (
    CuratedVendorSpec,
    VendorOAuthConfig,
)
from ...registry import registry

# Slack's own scope names. Bot scopes, not user scopes.
CHANNELS_READ = "channels:read"
CHANNELS_HISTORY = "channels:history"
CHAT_WRITE = "chat:write"
USERS_READ = "users:read"
USERS_READ_EMAIL = "users:read.email"

OAUTH_SCOPES: tuple[str, ...] = (
    CHANNELS_READ,
    CHANNELS_HISTORY,
    CHAT_WRITE,
    USERS_READ,
    USERS_READ_EMAIL,
)

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor="slack",
        display_name="Slack",
        description=(
            "Team messaging. Curated tools cover posting messages, reading "
            "channel history, and looking people up by email."
        ),
        auth_kinds=(VendorAuthKind.OAUTH2,),
        base_url="https://slack.com/api",
        oauth=VendorOAuthConfig(
            authorization_url="https://slack.com/oauth/v2/authorize",
            token_url="https://slack.com/api/oauth.v2.access",
            scopes=OAUTH_SCOPES,
            scope_delimiter=",",
        ),
        categories=("communication",),
        homepage_url="https://slack.com",
    )
)


__all__ = [
    "CHANNELS_HISTORY",
    "CHANNELS_READ",
    "CHAT_WRITE",
    "OAUTH_SCOPES",
    "USERS_READ",
    "USERS_READ_EMAIL",
    "vendor",
]
