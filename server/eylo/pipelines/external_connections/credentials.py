"""Encrypt external account credentials with tenant and revision binding."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue

from eylo.modules.provider_configs.crypto import EncryptionContext, get_secret_cipher

_CAPABILITY = "external_connection"


def encrypt_connection_credentials(
    credentials: Mapping[str, object],
    *,
    organization_id: UUID,
    connection_id: UUID,
    revision: int,
) -> str:
    """Encrypt credentials so they cannot move across orgs, rows, or revisions."""
    return get_secret_cipher().encrypt(
        credentials,
        _context(organization_id, connection_id, revision),
    )


def decrypt_connection_credentials(
    envelope: str,
    *,
    organization_id: UUID,
    connection_id: UUID,
    revision: int,
) -> dict[str, JsonValue]:
    """Authenticate and decrypt credentials only at an adapter composition edge."""
    return get_secret_cipher().decrypt(
        envelope,
        _context(organization_id, connection_id, revision),
    )


def _context(
    organization_id: UUID,
    connection_id: UUID,
    revision: int,
) -> EncryptionContext:
    return EncryptionContext(
        organization_id=organization_id,
        config_id=connection_id,
        capability=_CAPABILITY,
        revision=revision,
    )


__all__ = [
    "decrypt_connection_credentials",
    "encrypt_connection_credentials",
]
