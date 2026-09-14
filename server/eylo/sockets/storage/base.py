"""Provider-neutral object-storage protocol and typed operation failures."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from eylo.common.contracts.storage_objects import StoredObject as StoredObject

_CONTENT_SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_STREAM_CHUNK_BYTES = 64 * 1024
MAX_STREAM_CHUNK_BYTES = 8 * 1024 * 1024
DEFAULT_LIST_LIMIT = 1000
MAX_LIST_LIMIT = 5000
DEFAULT_PRESIGNED_EXPIRY_SECONDS = 3600
MAX_PRESIGNED_EXPIRY_SECONDS = 604800
DIGEST_CHUNK_BYTES = 1024 * 1024


class StorageOperation(StrEnum):
    UPLOAD = "upload"
    INSPECT = "inspect"
    LIST = "list"
    DOWNLOAD = "download"
    DELETE = "delete"
    PRESIGN = "presign"
    VERIFY = "verify"
    PRESIGNED_DOWNLOAD = "presigned_download"


class StorageFailure(StrEnum):
    """Normalized storage failures, never native provider messages or codes."""

    INVALID_KEY = "invalid_key"
    INVALID_LIMIT = "invalid_limit"
    INVALID_EXPIRY = "invalid_expiry"
    INVALID_CHUNK_SIZE = "invalid_chunk_size"
    INVALID_SIZE_LIMIT = "invalid_size_limit"
    INVALID_CONTENT_DIGEST = "invalid_content_digest"
    INVALID_LIST_RESPONSE = "invalid_list_response"
    INVALID_INSPECT_RESPONSE = "invalid_inspect_response"
    INVALID_ERROR_RESPONSE = "invalid_error_response"
    INVALID_CLIENT = "invalid_client"
    INVALID_DOWNLOAD_RESPONSE = "invalid_download_response"
    INVALID_PRESIGN_RESPONSE = "invalid_presign_response"
    CLEANUP_FAILED = "cleanup_failed"
    OBJECT_TOO_LARGE = "object_too_large"
    UPLOAD_SOURCE_READ = "upload_source_read"
    UPLOAD_CONTENT_DIGEST_MISMATCH = "upload_content_digest_mismatch"
    UNSUPPORTED = "unsupported"
    FILESYSTEM = "filesystem"
    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"


class StorageRecovery(StrEnum):
    """Recovery classification, not an instruction to replay a side effect."""

    TERMINAL = "terminal"
    RETRY = "retry"


class StorageOperationError(Exception):
    """One storage operation failed with a stable machine-readable outcome."""

    def __init__(
        self,
        failure: StorageFailure,
        *,
        recovery: StorageRecovery,
        operation: StorageOperation | None = None,
    ) -> None:
        if not isinstance(failure, StorageFailure):
            raise TypeError("Storage failure must be a StorageFailure.")
        if not isinstance(recovery, StorageRecovery):
            raise TypeError("Storage recovery must be a StorageRecovery.")
        if operation is not None and not isinstance(operation, StorageOperation):
            raise TypeError("Storage operation must be a StorageOperation.")
        self.failure = failure
        self.recovery = recovery
        self.operation = operation
        super().__init__(self.code)

    @property
    def code(self) -> str:
        """Stable legacy diagnostic derived only from named contract values."""
        if self.operation is None:
            return self.failure.value
        if self.failure is StorageFailure.UNSUPPORTED:
            return f"{self.failure.value}_{self.operation.value}"
        return f"{self.operation.value}_{self.failure.value}"

    @property
    def retryable(self) -> bool:
        """Read-only predicate for consumers that decide whether replay is safe."""
        return self.recovery is StorageRecovery.RETRY


class UnsupportedStorageOperation(StorageOperationError):
    def __init__(self, operation: StorageOperation) -> None:
        super().__init__(
            StorageFailure.UNSUPPORTED,
            operation=operation,
            recovery=StorageRecovery.TERMINAL,
        )


class StorageObjectTooLarge(StorageOperationError):
    def __init__(self) -> None:
        super().__init__(
            StorageFailure.OBJECT_TOO_LARGE, recovery=StorageRecovery.TERMINAL
        )


class StorageCapabilities(BaseModel):
    """Strict intrinsic support predicates declared by each adapter."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )
    upload: bool = True
    list: bool = True
    download: bool = True
    delete: bool = True
    presigned_download: bool = False
    stable_key_put: bool = False
    put_reconciliation: bool = False


class StorageVendorAdapter(ABC):
    """Operations implemented by one explicit storage authority."""

    capabilities = StorageCapabilities()

    @abstractmethod
    async def upload_file(
        self,
        *,
        path: Path,
        key: str,
        content_type: str = "application/octet-stream",
        content_sha256: str | None = None,
    ) -> str:
        """Put a local file at one stable key, or raise a typed failure."""

    @abstractmethod
    async def inspect_object(self, key: str) -> StoredObject | None:
        """Observe exact size/digest, or None only when the key does not exist."""

    @abstractmethod
    async def generate_presigned_url(
        self,
        key: str,
        expires_in: int = DEFAULT_PRESIGNED_EXPIRY_SECONDS,
    ) -> str:
        """Return a bearer download URL, or raise unsupported/failure."""

    @abstractmethod
    async def list_objects(
        self,
        prefix: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[StoredObject]:
        """Return at most ``limit`` objects under a prefix."""

    @abstractmethod
    async def download_object(
        self,
        key: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes | None:
        """Return bytes or None only when the object does not exist."""

    async def stream_object(
        self,
        key: str,
        *,
        chunk_size: int = DEFAULT_STREAM_CHUNK_BYTES,
    ) -> AsyncIterator[bytes]:
        """Stream one object; adapters may override to avoid buffering it."""
        chunk_size = validate_chunk_size(chunk_size)
        content = await self.download_object(key)
        if content is None:
            return
        content = validate_download_bytes(content)
        for start in range(0, len(content), chunk_size):
            yield content[start : start + chunk_size]

    @abstractmethod
    async def delete_object(self, key: str) -> bool:
        """Delete one object idempotently, or raise a typed failure."""


def validate_key(key: str, *, allow_empty: bool = False) -> str:
    if not isinstance(key, str):
        raise StorageOperationError(
            StorageFailure.INVALID_KEY, recovery=StorageRecovery.TERMINAL
        )
    normalized = key.strip().replace("\\", "/")
    parts = normalized.split("/")
    if (
        (not allow_empty and not normalized)
        or normalized.startswith("/")
        or "\x00" in normalized
        or any(part in {".", ".."} for part in parts)
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_KEY, recovery=StorageRecovery.TERMINAL
        )
    return normalized


def validate_limit(limit: int) -> int:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_LIST_LIMIT
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_LIMIT, recovery=StorageRecovery.TERMINAL
        )
    return limit


def validate_expiry(expires_in: int) -> int:
    if (
        isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or not 1 <= expires_in <= MAX_PRESIGNED_EXPIRY_SECONDS
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_EXPIRY, recovery=StorageRecovery.TERMINAL
        )
    return expires_in


def validate_content_sha256(content_sha256: str | None) -> str | None:
    if content_sha256 is not None and (
        not isinstance(content_sha256, str)
        or not _CONTENT_SHA256.fullmatch(content_sha256)
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_CONTENT_DIGEST, recovery=StorageRecovery.TERMINAL
        )
    return content_sha256


def validate_chunk_size(chunk_size: int) -> int:
    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or not 1 <= chunk_size <= MAX_STREAM_CHUNK_BYTES
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_CHUNK_SIZE, recovery=StorageRecovery.TERMINAL
        )
    return chunk_size


def validate_size_limit(max_bytes: int | None) -> int | None:
    if max_bytes is not None and (
        isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_SIZE_LIMIT, recovery=StorageRecovery.TERMINAL
        )
    return max_bytes


def validate_download_bytes(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise StorageOperationError(
            StorageFailure.INVALID_DOWNLOAD_RESPONSE, recovery=StorageRecovery.TERMINAL
        )
    return value
