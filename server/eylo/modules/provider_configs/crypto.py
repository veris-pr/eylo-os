"""Credential encryption for the `provider_configs` domain."""

import base64
import binascii
import json
import os
from collections.abc import Mapping
from typing import Self
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    TypeAdapter,
    ValidationError,
    model_validator,
)

_ENVELOPE_VERSION = "v1"
_KEY_HEX_LENGTH = 64
_KEY_BYTE_LENGTH = 32
_NONCE_LENGTH = 12
_CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]*$"
_AUTHENTICATION_TAG_LENGTH = 16
_BASE64_BLOCK_LENGTH = 4
_ENVELOPE_PART_COUNT = 3
_ASSOCIATED_DATA_PREFIX = "provider-config"
_JSON_OBJECT = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


class SecretCipherError(Exception):
    """Base error for provider-config encryption failures."""


class InvalidEncryptionKey(SecretCipherError):
    """Raised when ENCRYPTION_KEY does not satisfy the key contract."""


class InvalidEncryptionContext(SecretCipherError):
    """Raised when associated-data context is invalid."""


class SecretEncryptionError(SecretCipherError):
    """Raised when a secret mapping cannot be encrypted."""


class SecretDecryptionError(SecretCipherError):
    """Raised when a ciphertext envelope cannot be authenticated or decoded."""


class EncryptionContext(BaseModel):
    """Authenticated owner and revision, preserving the existing AAD encoding.

    The purpose label belongs to the caller. MCP and external connections reuse
    this cipher without becoming provider capabilities.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    config_id: UUID
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    revision: int = Field(ge=1)

    @model_validator(mode="wrap")
    @classmethod
    def _validate_context(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise InvalidEncryptionContext(
                "Encryption context contains invalid owner, purpose or revision."
            ) from None

    def associated_data(self) -> bytes:
        validated = type(self).model_validate(self)
        return (
            f"{_ASSOCIATED_DATA_PREFIX}:"
            f"{validated.organization_id}:{validated.config_id}:{validated.capability}:"
            f"{validated.revision}"
        ).encode("utf-8")


def get_secret_cipher() -> "SecretCipher":
    """Build the provider secret cipher from validated application settings."""
    from eylo.common.config import settings

    return SecretCipher(settings.ENCRYPTION_KEY)


class SecretCipher:
    """Encrypt and decrypt provider secret mappings with a versioned envelope."""

    def __init__(self, key_hex: str) -> None:
        self._cipher = AESGCM(_decode_key(key_hex))

    def encrypt(
        self,
        secrets: Mapping[str, object],
        context: EncryptionContext,
    ) -> str:
        plaintext = _serialize_secrets(secrets)
        nonce = os.urandom(_NONCE_LENGTH)

        try:
            ciphertext = self._cipher.encrypt(
                nonce,
                plaintext,
                context.associated_data(),
            )
        except InvalidEncryptionContext:
            raise
        except (OverflowError, ValueError) as error:
            raise SecretEncryptionError("Secret payload encryption failed.") from error

        return ".".join(
            (
                _ENVELOPE_VERSION,
                _base64url_encode(nonce),
                _base64url_encode(ciphertext),
            )
        )

    def decrypt(
        self,
        envelope: str,
        context: EncryptionContext,
    ) -> dict[str, JsonValue]:
        nonce, ciphertext = _decode_envelope(envelope)

        try:
            plaintext = self._cipher.decrypt(
                nonce,
                ciphertext,
                context.associated_data(),
            )
        except InvalidEncryptionContext:
            raise
        except (
            InvalidTag,
            UnicodeDecodeError,
            ValueError,
        ) as error:
            raise SecretDecryptionError(
                "Secret payload could not be decrypted."
            ) from error

        try:
            return _JSON_OBJECT.validate_python(json.loads(plaintext.decode("utf-8")))
        except ValueError:
            raise SecretDecryptionError(
                "Decrypted secret payload has an invalid shape."
            ) from None

    def encrypt_field(self, value: str, context_label: str = "") -> str:
        """Encrypt a single string value and return a versioned envelope."""
        if not isinstance(value, str) or not isinstance(context_label, str):
            raise SecretEncryptionError("Field and encryption context must be text.")
        nonce = os.urandom(_NONCE_LENGTH)
        try:
            aad = context_label.encode("utf-8")
            ciphertext = self._cipher.encrypt(nonce, value.encode("utf-8"), aad)
        except (OverflowError, ValueError):
            raise SecretEncryptionError("Field encryption failed.") from None
        return ".".join(
            (_ENVELOPE_VERSION, _base64url_encode(nonce), _base64url_encode(ciphertext))
        )

    def decrypt_field(self, envelope: str, context_label: str = "") -> str:
        """Decrypt a single string value from a versioned envelope."""
        if not isinstance(context_label, str):
            raise SecretDecryptionError("Decryption context must be text.")
        nonce, ciphertext = _decode_envelope(envelope)
        try:
            aad = context_label.encode("utf-8")
            plaintext = self._cipher.decrypt(nonce, ciphertext, aad)
            return plaintext.decode("utf-8")
        except (InvalidTag, ValueError):
            raise SecretDecryptionError("Field could not be decrypted.") from None


def _decode_key(key_hex: str) -> bytes:
    if not isinstance(key_hex, str) or len(key_hex) != _KEY_HEX_LENGTH:
        raise InvalidEncryptionKey(
            "ENCRYPTION_KEY must be exactly 64 hexadecimal characters."
        )

    try:
        key = bytes.fromhex(key_hex)
    except ValueError as error:
        raise InvalidEncryptionKey(
            "ENCRYPTION_KEY must be exactly 64 hexadecimal characters."
        ) from error

    if len(key) != _KEY_BYTE_LENGTH:
        raise InvalidEncryptionKey("ENCRYPTION_KEY must decode to a 256-bit AES key.")
    return key


def _serialize_secrets(secrets: Mapping[str, object]) -> bytes:
    if not isinstance(secrets, Mapping) or not all(
        isinstance(key, str) for key in secrets
    ):
        raise SecretEncryptionError("Secret payload must be a string-keyed mapping.")

    try:
        validated = _JSON_OBJECT.validate_python(dict(secrets))
        return json.dumps(
            validated,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise SecretEncryptionError(
            "Secret payload must contain JSON-serializable values."
        ) from None


def _decode_envelope(envelope: str) -> tuple[bytes, bytes]:
    if not isinstance(envelope, str):
        raise SecretDecryptionError("Ciphertext envelope is malformed.")

    parts = envelope.split(".")
    if len(parts) != _ENVELOPE_PART_COUNT or parts[0] != _ENVELOPE_VERSION:
        raise SecretDecryptionError("Ciphertext envelope version is unsupported.")

    try:
        nonce = _base64url_decode(parts[1])
        ciphertext = _base64url_decode(parts[2])
    except (binascii.Error, ValueError) as error:
        raise SecretDecryptionError("Ciphertext envelope is malformed.") from error

    if len(nonce) != _NONCE_LENGTH or len(ciphertext) < _AUTHENTICATION_TAG_LENGTH:
        raise SecretDecryptionError("Ciphertext envelope is malformed.")
    return nonce, ciphertext


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % _BASE64_BLOCK_LENGTH)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)
