"""Fixed Graph origin, tenant-templated OAuth with PKCE, and text body preference."""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import VendorAuthKind

from ...contracts import CuratedVendorSpec, VendorOAuthConfig
from ...registry import registry
from .schemas import API_PREFIX, BODY_PREFERENCE, GRAPH_ORIGIN

AUTHORIZATION_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

# Microsoft's own scope names.
MAIL_READ = "https://graph.microsoft.com/Mail.Read"
MAIL_SEND = "https://graph.microsoft.com/Mail.Send"
OFFLINE_ACCESS = "offline_access"

OAUTH_SCOPES: tuple[str, ...] = (MAIL_READ, MAIL_SEND, OFFLINE_ACCESS)

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor="outlook",
        display_name="Outlook",
        description=(
            "Microsoft 365 mail. Curated tools cover searching, reading, "
            "sending, and replying to messages."
        ),
        auth_kinds=(VendorAuthKind.OAUTH2,),
        base_url=GRAPH_ORIGIN + API_PREFIX,
        static_headers=(("Prefer", BODY_PREFERENCE),),
        oauth=VendorOAuthConfig(
            authorization_url=AUTHORIZATION_URL,
            token_url=TOKEN_URL,
            scopes=OAUTH_SCOPES,
            pkce=True,
        ),
        categories=("communication", "productivity"),
        homepage_url="https://outlook.com",
    )
)

__all__ = [
    "AUTHORIZATION_URL",
    "MAIL_READ",
    "MAIL_SEND",
    "OAUTH_SCOPES",
    "OFFLINE_ACCESS",
    "TOKEN_URL",
    "vendor",
]
