"""Consumed aioboto3 client surface; generated SDK values are narrowed locally."""

from collections.abc import AsyncIterable
from typing import Protocol, runtime_checkable

from eylo.sockets.storage.base import (
    StorageFailure,
    StorageOperationError,
    StorageRecovery,
)

S3_SERVICE_NAME = "s3"
S3_LIST_OPERATION = "list_objects_v2"
S3_GET_OPERATION = "get_object"


@runtime_checkable
class S3Paginator(Protocol):
    def paginate(
        self, *, Bucket: str, Prefix: str, PaginationConfig: dict[str, int]
    ) -> AsyncIterable[object]: ...


@runtime_checkable
class S3SdkClient(Protocol):
    """Only generated/injected methods currently invoked by the S3 adapter."""

    async def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        *,
        ExtraArgs: dict[str, str | dict[str, str]],
    ) -> object: ...

    async def head_object(self, **kwargs: str) -> object: ...

    async def get_object(self, **kwargs: str) -> object: ...

    async def delete_object(self, **kwargs: str) -> object: ...

    async def head_bucket(self, **kwargs: str) -> object: ...

    def get_paginator(self, operation_name: str) -> object: ...

    async def generate_presigned_url(
        self, ClientMethod: str, *, Params: dict[str, str], ExpiresIn: int
    ) -> object: ...


def require_s3_client(value: object) -> S3SdkClient:
    if not isinstance(value, S3SdkClient) or not all(
        callable(method)
        for method in (
            value.upload_file,
            value.head_object,
            value.get_object,
            value.delete_object,
            value.head_bucket,
            value.get_paginator,
            value.generate_presigned_url,
        )
    ):
        raise StorageOperationError(
            StorageFailure.INVALID_CLIENT, recovery=StorageRecovery.TERMINAL
        )
    return value


def require_s3_paginator(value: object) -> S3Paginator:
    if not isinstance(value, S3Paginator) or not callable(value.paginate):
        raise StorageOperationError(
            StorageFailure.INVALID_CLIENT, recovery=StorageRecovery.TERMINAL
        )
    return value
