"""PagerDuty REST v2 identity for the existing read-only tool catalog.

An acting-user configuration for incident mutations is not part of this
connection contract. This catalog does not infer one or expose writes.
"""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import (
    CredentialLocation,
    VendorAuthKind,
)

from ...contracts import ApiKeyPlacement, CuratedVendorSpec
from ...registry import registry
from .schemas import API_ACCEPT

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor="pagerduty",
        display_name="PagerDuty",
        description=(
            "Incidents and on-call schedules, read-only. Curated tools report "
            "what is currently firing, who is on call for a service right now, "
            "and the notes people have left on an incident."
        ),
        auth_kinds=(VendorAuthKind.API_KEY,),
        base_url="https://api.pagerduty.com",
        accept_media_type=API_ACCEPT,
        categories=("operations", "monitoring"),
        homepage_url="https://www.pagerduty.com",
        # PagerDuty's REST keys use their own scheme word, not Bearer.
        api_key_placement=ApiKeyPlacement(
            location=CredentialLocation.HEADER,
            name="Authorization",
            value_prefix="Token token=",
        ),
    )
)

__all__ = ["vendor"]
