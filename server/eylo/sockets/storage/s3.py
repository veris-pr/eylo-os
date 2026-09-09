"""AWS S3 adapter using explicit credentials and an SDK-derived endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from eylo.sockets.storage.base import (
    DEFAULT_LIST_LIMIT,
    DEFAULT_PRESIGNED_EXPIRY_SECONDS,
    DEFAULT_STREAM_CHUNK_BYTES,
    DIGEST_CHUNK_BYTES,
    StorageCapabilities,
    StorageFailure,
    StorageObjectTooLarge,
    StorageOperation,
    StorageOperationError,
    StorageRecovery,
    StorageVendorAdapter,
    StoredObject,
    validate_chunk_size,
    validate_content_sha256,
    validate_expiry,
    validate_key,
    validate_limit,
    validate_size_limit,
)
from eylo.sockets.storage.s3_sdk import (
    S3_GET_OPERATION,
    S3_LIST_OPERATION,
    S3_SERVICE_NAME,
    S3SdkClient,
    require_s3_client,
    require_s3_paginator,
)
from eylo.sockets.storage.s3_wire import (
    CONTENT_DIGEST_METADATA_KEY,
    S3BucketRequest,
    S3ErrorResponse,
    S3GetObjectRequest,
    S3HeadObjectResponse,
    S3ListObjectsResponse,
    S3ObjectRequest,
    S3UploadExtraArgs,
    open_s3_response,
    validated_presigned_url,
)
from eylo.sockets.storage.schemas import S3StorageConfig

logger = logging.getLogger(__name__)


class S3StorageAdapter(StorageVendorAdapter):
    """AWS S3 operations for one bucket and explicit credential set."""

    capabilities = StorageCapabilities(
        presigned_download=True,
        stable_key_put=True,
        put_reconciliation=True,
    )

    def __init__(self, config: S3StorageConfig) -> None:
        config = S3StorageConfig.model_validate(config)
        self.config = config
        self._key_prefix = validate_key(config.key_prefix)
        self._session = aioboto3.Session(
            aws_access_key_id=config.access_key_id.get_secret_value(),
            aws_secret_access_key=config.secret_access_key.get_secret_value(),
            aws_session_token=(
                config.session_token.get_secret_value()
                if config.session_token is not None
                else None
            ),
            region_name=config.region,
        )
        self._client_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "virtual"},
        )

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[S3SdkClient]:
        async with self._session.client(
            S3_SERVICE_NAME, config=self._client_config
        ) as client:
            yield require_s3_client(client)

    def _object_key(self, key: str, *, allow_empty: bool = False) -> str:
        logical_key = validate_key(key, allow_empty=allow_empty)
        if not logical_key:
            return f"{self._key_prefix}/"
        return f"{self._key_prefix}/{logical_key}"

    def _logical_key(self, object_key: str) -> str | None:
        prefix = f"{self._key_prefix}/"
        if not object_key.startswith(prefix):
            return None
        try:
            return validate_key(object_key.removeprefix(prefix))
        except StorageOperationError:
            return None

    async def upload_file(
        self,
        *,
        path: Path,
        key: str,
        content_type: str = "application/octet-stream",
        content_sha256: str | None = None,
    ) -> str:
        logical_key = validate_key(key)
        object_key = self._object_key(logical_key)
        expected_digest = validate_content_sha256(content_sha256)
        if expected_digest is not None:
            try:
                actual_digest = await asyncio.to_thread(_sha256_path, path)
            except OSError:
                raise StorageOperationError(
                    StorageFailure.UPLOAD_SOURCE_READ,
                    recovery=StorageRecovery.TERMINAL,
                ) from None
            if actual_digest != expected_digest:
                raise StorageOperationError(
                    StorageFailure.UPLOAD_CONTENT_DIGEST_MISMATCH,
                    recovery=StorageRecovery.TERMINAL,
                )
        extra_args = S3UploadExtraArgs(
            content_type=content_type,
            metadata=(
                {CONTENT_DIGEST_METADATA_KEY: expected_digest}
                if expected_digest is not None
                else None
            ),
        )
        try:
            async with self._client() as s3:
                await s3.upload_file(
                    str(path),
                    self.config.bucket,
                    object_key,
                    ExtraArgs=extra_args.to_sdk(),
                )
        except (BotoCoreError, ClientError, OSError) as error:
            raise _storage_error(error, operation=StorageOperation.UPLOAD) from None
        return self.build_object_url(logical_key)

    async def inspect_object(self, key: str) -> StoredObject | None:
        logical_key = validate_key(key)
        object_key = self._object_key(logical_key)
        try:
            async with self._client() as s3:
                response = await s3.head_object(
                    **S3ObjectRequest(
                        bucket=self.config.bucket,
                        key=object_key,
                    ).to_sdk()
                )
        except ClientError as error:
            if _is_missing(error):
                return None
            raise _storage_error(error, operation=StorageOperation.INSPECT) from None
        except BotoCoreError as error:
            raise _storage_error(error, operation=StorageOperation.INSPECT) from None
        observed = S3HeadObjectResponse.from_sdk(response)
        content_sha256 = observed.metadata.get(CONTENT_DIGEST_METADATA_KEY)
        return StoredObject(
            key=logical_key,
            size=observed.content_length,
            content_sha256=(
                validate_content_sha256(content_sha256)
                if content_sha256 is not None
                else None
            ),
        )

    async def list_objects(
        self,
        prefix: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[StoredObject]:
        logical_prefix = validate_key(prefix, allow_empty=True)
        object_prefix = self._object_key(logical_prefix, allow_empty=True)
        ceiling = validate_limit(limit)
        found: list[StoredObject] = []
        try:
            async with self._client() as s3:
                paginator = require_s3_paginator(s3.get_paginator(S3_LIST_OPERATION))
                async for page in paginator.paginate(
                    Bucket=self.config.bucket,
                    Prefix=object_prefix,
                    PaginationConfig={"MaxItems": ceiling},
                ):
                    observed = S3ListObjectsResponse.from_sdk(page)
                    for entry in observed.contents:
                        object_key = entry.key
                        if object_key.endswith("/"):
                            continue
                        key = self._logical_key(object_key)
                        if key is None:
                            continue
                        found.append(StoredObject(key=key, size=entry.size))
        except (BotoCoreError, ClientError) as error:
            raise _storage_error(error, operation=StorageOperation.LIST) from None
        return found[:ceiling]

    async def download_object(
        self,
        key: str,
        *,
        max_bytes: int | None = None,
    ) -> bytes | None:
        object_key = self._object_key(key)
        max_bytes = validate_size_limit(max_bytes)
        request = S3GetObjectRequest(
            bucket=self.config.bucket,
            key=object_key,
            byte_range=f"bytes=0-{max_bytes}" if max_bytes is not None else None,
        )
        try:
            async with self._client() as s3:
                async with open_s3_response(
                    await s3.get_object(**request.to_sdk())
                ) as response:
                    body = await response.read_bytes()
        except ClientError as error:
            if _is_missing(error):
                return None
            raise _storage_error(error, operation=StorageOperation.DOWNLOAD) from None
        except BotoCoreError as error:
            raise _storage_error(error, operation=StorageOperation.DOWNLOAD) from None
        if max_bytes is not None and len(body) > max_bytes:
            raise StorageObjectTooLarge
        return body

    async def stream_object(
        self,
        key: str,
        *,
        chunk_size: int = DEFAULT_STREAM_CHUNK_BYTES,
    ) -> AsyncIterator[bytes]:
        """Stream S3 bytes while keeping the client and response body alive."""
        chunk_size = validate_chunk_size(chunk_size)
        object_key = self._object_key(key)
        try:
            async with self._client() as s3:
                try:
                    response = await s3.get_object(
                        **S3ObjectRequest(
                            bucket=self.config.bucket,
                            key=object_key,
                        ).to_sdk()
                    )
                except ClientError as error:
                    if _is_missing(error):
                        return
                    raise _storage_error(
                        error, operation=StorageOperation.DOWNLOAD
                    ) from None
                async with open_s3_response(response) as download:
                    while chunk := await download.read_bytes(chunk_size):
                        yield chunk
        except StorageOperationError:
            raise
        except (BotoCoreError, ClientError, OSError) as error:
            raise _storage_error(error, operation=StorageOperation.DOWNLOAD) from None

    async def delete_object(self, key: str) -> bool:
        object_key = self._object_key(key)
        try:
            async with self._client() as s3:
                await s3.delete_object(
                    **S3ObjectRequest(
                        bucket=self.config.bucket,
                        key=object_key,
                    ).to_sdk()
                )
        except (BotoCoreError, ClientError) as error:
            raise _storage_error(error, operation=StorageOperation.DELETE) from None
        return True

    async def generate_presigned_url(
        self,
        key: str,
        expires_in: int = DEFAULT_PRESIGNED_EXPIRY_SECONDS,
    ) -> str:
        object_key = self._object_key(key)
        expiry = validate_expiry(expires_in)
        try:
            async with self._client() as s3:
                response = await s3.generate_presigned_url(
                    S3_GET_OPERATION,
                    Params=S3ObjectRequest(
                        bucket=self.config.bucket, key=object_key
                    ).to_sdk(),
                    ExpiresIn=expiry,
                )
                return validated_presigned_url(response)
        except (BotoCoreError, ClientError) as error:
            raise _storage_error(error, operation=StorageOperation.PRESIGN) from None

    async def head_bucket(self) -> None:
        try:
            async with self._client() as s3:
                await s3.head_bucket(
                    **S3BucketRequest(bucket=self.config.bucket).to_sdk()
                )
        except (BotoCoreError, ClientError) as error:
            raise _storage_error(error, operation=StorageOperation.VERIFY) from None

    def build_object_url(self, key: str) -> str:
        object_key = self._object_key(key)
        return (
            f"https://{self.config.bucket}.s3.{self.config.region}.amazonaws.com/"
            f"{object_key}"
        )


def _is_missing(error: ClientError) -> bool:
    return S3ErrorResponse.from_sdk(error.response).missing


def _storage_error(
    error: Exception, *, operation: StorageOperation
) -> StorageOperationError:
    recovery = (
        StorageRecovery.RETRY
        if isinstance(error, BotoCoreError)
        else StorageRecovery.TERMINAL
    )
    failure = StorageFailure.TRANSPORT
    if isinstance(error, ClientError):
        observed = S3ErrorResponse.from_sdk(error.response)
        recovery = observed.recovery
        failure = observed.failure
    logger.warning("S3 %s failed with code=%s", operation, failure)
    return StorageOperationError(failure, operation=operation, recovery=recovery)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(DIGEST_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
