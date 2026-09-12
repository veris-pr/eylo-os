"""Provider webhook authenticity helpers for telephony public endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import time

from pydantic import ValidationError

from eylo.common.config import settings
from eylo.modules.telephony.provider_config_domain import TelephonyProvider
from eylo.modules.telephony.schemas import CallDirection
from eylo.modules.telephony.stream_claims import MediaStreamClaims

logger = logging.getLogger(__name__)

_MEDIA_STREAM_TOKEN_TTL_SECONDS = 15 * 60


def is_ip_allowlisted(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        client_addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    for entry in getattr(settings, "TELEPHONY_WEBHOOK_ALLOWLIST", []) or []:
        try:
            if client_addr in ipaddress.ip_network(str(entry).strip(), strict=False):
                return True
        except ValueError:
            logger.warning("Ignoring invalid telephony allowlist entry: %s", entry)
    return False


def _compare_digest(expected: str, actual: str | None) -> bool:
    if not expected or not actual or not expected.isascii() or not actual.isascii():
        return False
    return hmac.compare_digest(expected.strip(), actual.strip())


def _media_stream_secret() -> str:
    return str(settings.AUTH_SECRET_KEY)


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode())


def create_media_stream_token(
    *,
    provider: str,
    call_id: str,
    organization_id: str,
    agent_id: str,
    agent_revision: int,
    provider_config_id: str,
    provider_config_revision: int,
    direction: str,
    call_sid: str | None = None,
    initial_message: str | None = None,
) -> str:
    """Create a signed token binding a provider media stream to call metadata."""
    claims = MediaStreamClaims(
        provider=TelephonyProvider(provider.lower()),
        call_id=call_id,
        organization_id=organization_id,
        agent_id=agent_id,
        agent_revision=agent_revision,
        provider_config_id=provider_config_id,
        provider_config_revision=provider_config_revision,
        direction=CallDirection(direction.lower()),
        call_sid=call_sid or "",
        initial_message=initial_message or "",
        exp=int(time.time()) + _MEDIA_STREAM_TOKEN_TTL_SECONDS,
    )
    payload_bytes = json.dumps(
        claims.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    encoded_payload = _base64url_encode(payload_bytes)
    signature = _base64url_encode(
        hmac.new(
            _media_stream_secret().encode(), payload_bytes, hashlib.sha256
        ).digest()
    )
    return f"{encoded_payload}.{signature}"


def verify_media_stream_token(
    token: str | None,
    *,
    provider: str,
    call_id: str | None,
    organization_id: str | None,
    agent_id: str | None,
    agent_revision: int | None,
    provider_config_id: str | None,
    provider_config_revision: int | None,
    direction: str,
    call_sid: str | None = None,
    initial_message: str | None = None,
) -> bool:
    """Verify a provider media stream token against extracted call metadata."""
    if not token or "." not in token:
        return False
    encoded_payload, signature = token.split(".", 1)
    try:
        payload_bytes = _base64url_decode(encoded_payload)
        expected_signature = _base64url_encode(
            hmac.new(
                _media_stream_secret().encode(),
                payload_bytes,
                hashlib.sha256,
            ).digest()
        )
        if not _compare_digest(expected_signature, signature):
            return False
        claims = MediaStreamClaims.model_validate_json(payload_bytes)
        expected_provider = TelephonyProvider(provider.lower())
        expected_direction = CallDirection(direction.lower())
    except (ValueError, ValidationError):
        return False

    if claims.exp < int(time.time()):
        return False

    if (
        claims.provider is not expected_provider
        or claims.direction is not expected_direction
        or claims.call_id != (call_id or "")
        or claims.organization_id != (organization_id or "")
        or claims.agent_id != (agent_id or "")
        or claims.agent_revision != agent_revision
        or claims.provider_config_id != (provider_config_id or "")
        or claims.provider_config_revision != provider_config_revision
    ):
        return False
    if claims.call_sid and claims.call_sid != (call_sid or ""):
        return False
    if claims.initial_message != (initial_message or ""):
        return False
    return True
