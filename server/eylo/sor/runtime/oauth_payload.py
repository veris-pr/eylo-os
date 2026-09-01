"""Pure vendor-declared encoding for OAuth token endpoint requests."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from urllib.parse import urlencode

from eylo.sor.shared.contracts import (
    SorOAuthClientAuthMethod,
    SorOAuthSpec,
    SorOAuthTokenRequestFormat,
)


def apply_oauth_client_auth(
    oauth: SorOAuthSpec,
    values: Mapping[str, str],
    *,
    client_id: str,
    client_secret: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Place client credentials only where the vendor contract requires them."""
    authenticated_values = dict(values)
    if oauth.token_client_auth_method is SorOAuthClientAuthMethod.BODY:
        authenticated_values["client_id"] = client_id
        authenticated_values["client_secret"] = client_secret
        return authenticated_values, {}
    if oauth.token_client_auth_method is SorOAuthClientAuthMethod.BASIC:
        encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        return authenticated_values, {"Authorization": f"Basic {encoded}"}
    raise ValueError("Unsupported SOR OAuth client authentication method.")


def encode_oauth_token_request(
    oauth: SorOAuthSpec,
    values: Mapping[str, str],
) -> tuple[str, bytes]:
    """Encode secrets only in the body format declared by the adapter manifest."""
    if oauth.token_request_format is SorOAuthTokenRequestFormat.JSON:
        return (
            "application/json",
            json.dumps(dict(values), separators=(",", ":")).encode("utf-8"),
        )
    return "application/x-www-form-urlencoded", urlencode(values).encode("utf-8")


__all__ = ["apply_oauth_client_auth", "encode_oauth_token_request"]
