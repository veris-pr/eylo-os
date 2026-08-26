"""Authenticated envelopes for opaque SOR cursors and transient payloads."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from uuid import UUID

from eylo.modules.provider_configs.crypto import get_secret_cipher


class SorSecretEnvelopeError(Exception):
    """An encrypted SOR value is malformed or bound to another authority."""


def encrypt_connector_client_secret(
    secret: str,
    *,
    organization_id: UUID,
    connector_id: UUID,
    config_revision: int,
) -> str:
    """Encrypt one OAuth client secret under its exact connector revision."""
    normalized = secret.strip()
    if not normalized or len(normalized.encode("utf-8")) > 4096:
        raise SorSecretEnvelopeError(
            "OAuth client secret must contain 1 to 4096 bytes."
        )
    return get_secret_cipher().encrypt_field(
        normalized,
        _context(
            "connector-client-secret",
            organization_id=organization_id,
            resource_id=connector_id,
            revision=config_revision,
        ),
    )


def decrypt_connector_client_secret(
    envelope: str,
    *,
    organization_id: UUID,
    connector_id: UUID,
    config_revision: int,
) -> str:
    """Authenticate one OAuth client secret at the adapter composition edge."""
    try:
        secret = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                "connector-client-secret",
                organization_id=organization_id,
                resource_id=connector_id,
                revision=config_revision,
            ),
        )
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR connector credentials could not be authenticated."
        ) from error
    if not secret:
        raise SorSecretEnvelopeError("SOR connector client secret is empty.")
    return secret


def encrypt_connector_webhook_signing_secret(
    secret: str,
    *,
    organization_id: UUID,
    connector_id: UUID,
    secret_revision: int,
) -> str:
    """Encrypt one app webhook secret under its connector-owned revision."""
    if not secret or len(secret.encode("utf-8")) > 4096:
        raise SorSecretEnvelopeError(
            "Webhook signing secret must contain 1 to 4096 bytes."
        )
    if secret_revision <= 0:
        raise SorSecretEnvelopeError("Webhook signing secret revision is invalid.")
    return get_secret_cipher().encrypt_field(
        secret,
        _context(
            "connector-webhook-signing-secret",
            organization_id=organization_id,
            resource_id=connector_id,
            revision=secret_revision,
        ),
    )


def decrypt_connector_webhook_signing_secret(
    envelope: str,
    *,
    organization_id: UUID,
    connector_id: UUID,
    secret_revision: int,
) -> str:
    """Authenticate the current connector-owned app webhook secret."""
    try:
        secret = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                "connector-webhook-signing-secret",
                organization_id=organization_id,
                resource_id=connector_id,
                revision=secret_revision,
            ),
        )
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR connector webhook signing secret could not be authenticated."
        ) from error
    if not secret:
        raise SorSecretEnvelopeError("SOR connector webhook signing secret is empty.")
    return secret


def encrypt_source_webhook_signing_secret(
    secret: str,
    *,
    organization_id: UUID,
    source_id: UUID,
    secret_revision: int,
) -> str:
    """Encrypt a vendor webhook secret under one source-owned revision."""
    if not secret or len(secret.encode("utf-8")) > 4096:
        raise SorSecretEnvelopeError(
            "Webhook signing secret must contain 1 to 4096 bytes."
        )
    if secret_revision <= 0:
        raise SorSecretEnvelopeError("Webhook signing secret revision is invalid.")
    return get_secret_cipher().encrypt_field(
        secret,
        _context(
            "source-webhook-signing-secret",
            organization_id=organization_id,
            resource_id=source_id,
            revision=secret_revision,
        ),
    )


def decrypt_source_webhook_signing_secret(
    envelope: str,
    *,
    organization_id: UUID,
    source_id: UUID,
    secret_revision: int,
) -> str:
    """Authenticate the current source-owned webhook signing secret."""
    try:
        secret = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                "source-webhook-signing-secret",
                organization_id=organization_id,
                resource_id=source_id,
                revision=secret_revision,
            ),
        )
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR webhook signing secret could not be authenticated."
        ) from error
    if not secret:
        raise SorSecretEnvelopeError("SOR webhook signing secret is empty.")
    return secret


def encrypt_cursor(
    cursor: str,
    *,
    organization_id: UUID,
    stream_id: UUID,
    cursor_version: int,
) -> str:
    """Bind one opaque vendor cursor to its exact tenant and stream revision."""
    if not isinstance(cursor, str) or not cursor:
        raise SorSecretEnvelopeError("SOR cursor must be a non-empty string.")
    return get_secret_cipher().encrypt_field(
        cursor,
        _context(
            "stream-cursor",
            organization_id=organization_id,
            resource_id=stream_id,
            revision=cursor_version,
        ),
    )


def decrypt_cursor(
    envelope: str | None,
    *,
    organization_id: UUID,
    stream_id: UUID,
    cursor_version: int,
) -> str | None:
    """Authenticate one stored cursor without interpreting vendor contents."""
    if envelope is None:
        return None
    try:
        value = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                "stream-cursor",
                organization_id=organization_id,
                resource_id=stream_id,
                revision=cursor_version,
            ),
        )
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR cursor could not be authenticated."
        ) from error
    if not value:
        raise SorSecretEnvelopeError("SOR cursor is empty.")
    return value


def encrypt_json_payload(
    payload: Mapping[str, object],
    *,
    organization_id: UUID,
    resource_id: UUID,
    purpose: str,
    maximum_bytes: int,
) -> str:
    """Encrypt one bounded JSON object under a purpose-specific authority."""
    encoded = _encode_json(payload, maximum_bytes=maximum_bytes)
    return get_secret_cipher().encrypt_field(
        encoded,
        _context(
            purpose,
            organization_id=organization_id,
            resource_id=resource_id,
            revision=1,
        ),
    )


def decrypt_json_payload(
    envelope: str,
    *,
    organization_id: UUID,
    resource_id: UUID,
    purpose: str,
    maximum_bytes: int,
) -> dict[str, object]:
    """Authenticate and decode one purpose-bound JSON object."""
    try:
        encoded = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                purpose,
                organization_id=organization_id,
                resource_id=resource_id,
                revision=1,
            ),
        )
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR payload could not be authenticated."
        ) from error
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise SorSecretEnvelopeError("SOR payload exceeds its size limit.")
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise SorSecretEnvelopeError("SOR payload is not valid JSON.") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SorSecretEnvelopeError("SOR payload must be a string-keyed object.")
    return value


def encrypt_bytes(
    value: bytes,
    *,
    organization_id: UUID,
    resource_id: UUID,
    purpose: str,
    maximum_bytes: int,
) -> str:
    """Encrypt bounded raw bytes without assuming a vendor character encoding."""
    if len(value) > maximum_bytes:
        raise SorSecretEnvelopeError("SOR raw payload exceeds its size limit.")
    encoded = base64.urlsafe_b64encode(value).decode("ascii")
    return get_secret_cipher().encrypt_field(
        encoded,
        _context(
            purpose,
            organization_id=organization_id,
            resource_id=resource_id,
            revision=1,
        ),
    )


def decrypt_bytes(
    envelope: str,
    *,
    organization_id: UUID,
    resource_id: UUID,
    purpose: str,
    maximum_bytes: int,
) -> bytes:
    """Authenticate raw bytes and reapply the ingress size bound."""
    try:
        encoded = get_secret_cipher().decrypt_field(
            envelope,
            _context(
                purpose,
                organization_id=organization_id,
                resource_id=resource_id,
                revision=1,
            ),
        )
        value = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except Exception as error:
        raise SorSecretEnvelopeError(
            "SOR raw payload could not be authenticated."
        ) from error
    if len(value) > maximum_bytes:
        raise SorSecretEnvelopeError("SOR raw payload exceeds its size limit.")
    return value


def _encode_json(payload: Mapping[str, object], *, maximum_bytes: int) -> str:
    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive.")
    if not isinstance(payload, Mapping) or not all(
        isinstance(key, str) for key in payload
    ):
        raise SorSecretEnvelopeError("SOR payload must be a string-keyed object.")
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise SorSecretEnvelopeError(
            "SOR payload must contain JSON-compatible values."
        ) from error
    if len(encoded.encode("utf-8")) > maximum_bytes:
        raise SorSecretEnvelopeError("SOR payload exceeds its size limit.")
    return encoded


def _context(
    purpose: str,
    *,
    organization_id: UUID,
    resource_id: UUID,
    revision: int,
) -> str:
    normalized = purpose.strip().lower().replace("_", "-")
    if not normalized or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
        for character in normalized
    ):
        raise ValueError("SOR envelope purpose must be a lowercase identifier.")
    if revision < 1:
        raise ValueError("SOR envelope revision must be positive.")
    return f"sor:{normalized}:{organization_id}:{resource_id}:v{revision}"


__all__ = [
    "SorSecretEnvelopeError",
    "decrypt_bytes",
    "decrypt_connector_client_secret",
    "decrypt_cursor",
    "decrypt_json_payload",
    "encrypt_bytes",
    "encrypt_connector_client_secret",
    "encrypt_cursor",
    "encrypt_json_payload",
]
