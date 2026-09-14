"""Jira vendor identity.

Jira Cloud is the reference case for a customer-owned origin: every
organization selects its own `https://<site>.atlassian.net`. Basic auth targets
that site; OAuth binds the site to its cloud ID at Atlassian's API gateway.

Atlassian's "API token" is not a bearer key — it is the password half of HTTP
Basic, paired with the account email. So the auth kind here is `BASIC`, and the
credential fields are `username` (the email) and `password` (the token).
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

# Atlassian's own OAuth scope names.
READ_JIRA_WORK = "read:jira-work"
WRITE_JIRA_WORK = "write:jira-work"
READ_JIRA_USER = "read:jira-user"

OAUTH_SCOPES: tuple[str, ...] = (READ_JIRA_WORK, WRITE_JIRA_WORK, READ_JIRA_USER)

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor="jira",
        display_name="Jira",
        description=(
            "Issue tracking and project management. Curated tools cover "
            "searching, reading, creating, and commenting on issues."
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
            label="Jira site URL",
            placeholder="https://your-team.atlassian.net",
            description=(
                "Your Jira Cloud site. Basic auth uses the site directly; "
                "OAuth uses this site's verified Atlassian cloud gateway."
            ),
            path_suffix="/rest/api/3",
        ),
        categories=("productivity", "developer_tools"),
        homepage_url="https://www.atlassian.com/software/jira",
    )
)

__all__ = [
    "OAUTH_SCOPES",
    "READ_JIRA_USER",
    "READ_JIRA_WORK",
    "WRITE_JIRA_WORK",
    "vendor",
]
