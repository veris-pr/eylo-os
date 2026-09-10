"""Calendly vendor identity."""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import (
    CredentialLocation,
    VendorAuthKind,
)

from ...contracts import ApiKeyPlacement, CuratedVendorSpec, VendorOAuthConfig
from ...registry import registry
from .schemas import API_ORIGIN, AUTHORIZATION_URL, TOKEN_URL, VENDOR_KEY, CalendlyScope

vendor = registry.register_vendor(
    CuratedVendorSpec(
        vendor=VENDOR_KEY,
        display_name="Calendly",
        description=(
            "Scheduling links and booked meetings. Curated tools list the "
            "booking links an account offers, show what is on the calendar, "
            "reveal who booked each meeting, and cancel with a reason."
        ),
        auth_kinds=(VendorAuthKind.OAUTH2, VendorAuthKind.API_KEY),
        base_url=API_ORIGIN,
        oauth=VendorOAuthConfig(
            authorization_url=AUTHORIZATION_URL,
            token_url=TOKEN_URL,
            scopes=(
                CalendlyScope.USERS_READ,
                CalendlyScope.EVENT_TYPES_READ,
                CalendlyScope.EVENTS_READ,
                CalendlyScope.EVENTS_WRITE,
            ),
        ),
        categories=("scheduling", "productivity"),
        homepage_url="https://calendly.com",
        api_key_placement=ApiKeyPlacement(
            location=CredentialLocation.HEADER,
            name="Authorization",
            value_prefix="Bearer ",
        ),
    )
)

__all__ = ["vendor"]
