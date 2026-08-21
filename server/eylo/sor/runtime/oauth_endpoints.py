"""Resolve fixed or tenant-origin OAuth endpoints without widening egress."""

from __future__ import annotations

from eylo.common.http_egress import HttpEgressPolicyError, HttpOrigin
from eylo.sor.shared.contracts import SorOAuthSpec


class SorOAuthEndpointError(ValueError):
    """An executable OAuth endpoint cannot be resolved safely."""


def resolve_oauth_authorization_url(
    oauth: SorOAuthSpec,
    *,
    instance_origin: str | None,
) -> str:
    """Resolve the consent endpoint against the already validated source origin."""
    authorization_origin = _authorization_origin(
        oauth,
        instance_origin=instance_origin,
    )
    return _resolve_endpoint(
        absolute_url=oauth.authorization_url,
        relative_path=oauth.authorization_path,
        instance_origin=authorization_origin,
        label="authorization",
    )


def resolve_oauth_token_url(
    oauth: SorOAuthSpec,
    *,
    instance_origin: str | None,
) -> str:
    """Resolve the token endpoint against the already validated source origin."""
    return _resolve_endpoint(
        absolute_url=oauth.token_url,
        relative_path=oauth.token_path,
        instance_origin=instance_origin,
        label="token",
    )


def _authorization_origin(
    oauth: SorOAuthSpec,
    *,
    instance_origin: str | None,
) -> str | None:
    if not oauth.instance_origin_options or instance_origin is None:
        return instance_origin
    for option in oauth.instance_origin_options:
        if option.api_origin == instance_origin:
            return option.authorization_origin
    raise SorOAuthEndpointError(
        "SOR OAuth authorization endpoint has no consent host for this API origin."
    )


def _resolve_endpoint(
    *,
    absolute_url: str | None,
    relative_path: str | None,
    instance_origin: str | None,
    label: str,
) -> str:
    if (absolute_url is None) == (relative_path is None):
        raise SorOAuthEndpointError(
            f"SOR OAuth {label} endpoint must use exactly one URL or tenant path."
        )
    if absolute_url is not None:
        return absolute_url
    if instance_origin is None:
        raise SorOAuthEndpointError(
            f"SOR OAuth {label} endpoint requires a verified tenant origin."
        )
    try:
        origin = HttpOrigin.parse(instance_origin)
    except HttpEgressPolicyError as error:
        raise SorOAuthEndpointError(
            f"SOR OAuth {label} endpoint has an invalid tenant origin."
        ) from error
    return f"{origin}{relative_path}"


__all__ = [
    "SorOAuthEndpointError",
    "resolve_oauth_authorization_url",
    "resolve_oauth_token_url",
]
