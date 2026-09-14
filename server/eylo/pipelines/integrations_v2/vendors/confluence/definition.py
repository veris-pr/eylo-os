"""Confluence vendor identity.

Like Jira, Confluence Cloud lives at the customer's own
`https://<site>.atlassian.net`, so this vendor declares an instance URL rather
than a fixed origin. OAuth binds that site to Atlassian's cloud gateway.
An Atlassian "API token" is the password half of HTTP
Basic paired with the account email, so the auth kind is `BASIC`.

The path suffix is `/wiki` rather than `/wiki/api/v2` because Confluence still
splits across two APIs: pages and spaces are v2 (`/wiki/api/v2/...`) while CQL
search only exists on v1 (`/wiki/rest/api/search`). Pinning at `/wiki` keeps
both reachable under one origin policy.
"""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import VendorAuthKind

from ...contracts import (
    CuratedVendorSpec,
    InstanceUrlRequirement,
    OAuthTokenEncoding,
    VendorOAuthConfig,
)
from ...registry import registry
from ..atlassian_oauth import (
    AUTHORIZATION_PARAMS,
    AUTHORIZATION_URL,
    OFFLINE_SCOPE,
    TOKEN_URL,
)

# Granular scopes, including V1 search's documented granular alternative.
READ_PAGE = "read:page:confluence"
WRITE_PAGE = "write:page:confluence"
READ_SPACE = "read:space:confluence"
SEARCH_CONTENT = "read:content-details:confluence"

OAUTH_SCOPES: tuple[str, ...] = (READ_PAGE, WRITE_PAGE, READ_SPACE, SEARCH_CONTENT)

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor="confluence",
        display_name="Confluence",
        description=(
            "Team documentation and knowledge base. Curated tools cover "
            "searching, reading, creating, and editing pages."
        ),
        auth_kinds=(VendorAuthKind.BASIC, VendorAuthKind.OAUTH2),
        oauth=VendorOAuthConfig(
            authorization_url=AUTHORIZATION_URL,
            token_url=TOKEN_URL,
            scopes=(*OAUTH_SCOPES, OFFLINE_SCOPE),
            token_encoding=OAuthTokenEncoding.JSON,
            authorization_params=AUTHORIZATION_PARAMS,
        ),
        instance_url=InstanceUrlRequirement(
            label="Confluence site URL",
            placeholder="https://your-team.atlassian.net",
            description=(
                "Your Confluence Cloud site. Basic auth uses the site directly; "
                "OAuth uses this site's verified Atlassian cloud gateway."
            ),
            path_suffix="/wiki",
        ),
        categories=("productivity", "documentation"),
        homepage_url="https://www.atlassian.com/software/confluence",
    )
)

__all__ = [
    "OAUTH_SCOPES",
    "READ_PAGE",
    "READ_SPACE",
    "SEARCH_CONTENT",
    "WRITE_PAGE",
    "vendor",
]
