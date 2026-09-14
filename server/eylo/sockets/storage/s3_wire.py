"""Consumed S3 SDK response fields; AWS pagination and unused metadata stay native."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from http import HTTPStatus

from aiobotocore.response import StreamingBody
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sockets.storage.base import (
    StorageFailure,
    StorageOperation,
    StorageOperationError,
    StorageRecovery,
    validate_download_bytes,
)

CONTENT_DIGEST_METADATA_KEY = "eylo-sha256"
HTTP_STATUS_EXCLUSIVE_UPPER_BOUND = 600
logger = logging.getLogger(__name__)


class S3BucketRequest(BaseModel):
    """SDK arguments are serialized only after explicit namespace resolution."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    bucket: str = Field(min_length=1, serialization_alias="Bucket", repr=False)

    def to_sdk(self) -> dict[str, str]:
        return (
            type(self).model_validate(self).model_dump(by_alias=True, exclude_none=True)
        )


class S3ObjectRequest(S3BucketRequest):
    key: str = Field(min_length=1, serialization_alias="Key", repr=False)


class S3GetObjectRequest(S3ObjectRequest):
    byte_range: str | None = Field(
        default=None,
        pattern=r"^bytes=0-\d+$",
        serialization_alias="Range",
    )


class S3GetObjectResponse(BaseModel):
    """SDK body stays local and is closed by the response context manager."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        validate_by_name=True,
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    body: StreamingBody = Field(alias="Body", repr=False, exclude=True)

    @classmethod
    def from_sdk(cls, value: object) -> S3GetObjectResponse:
        try:
            return cls.model_validate(value)
        except ValidationError:
            raise StorageOperationError(
                StorageFailure.INVALID_DOWNLOAD_RESPONSE,
                recovery=StorageRecovery.TERMINAL,
            ) from None

    async def read_bytes(self, amount: int | None = None) -> bytes:
        try:
            value: object = await self.body.read(amount)
        except (TypeError, ValueError):
            raise StorageOperationError(
                StorageFailure.INVALID_DOWNLOAD_RESPONSE,
                recovery=StorageRecovery.TERMINAL,
            ) from None
        return validate_download_bytes(value)

    async def close(self) -> None:
        try:
            result: object = self.body.close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            raise StorageOperationError(
                StorageFailure.CLEANUP_FAILED,
                operation=StorageOperation.DOWNLOAD,
                recovery=StorageRecovery.TERMINAL,
            ) from None


@asynccontextmanager
async def open_s3_response(value: object) -> AsyncIterator[S3GetObjectResponse]:
    response = S3GetObjectResponse.from_sdk(value)
    try:
        yield response
    except BaseException:
        try:
            await response.close()
        except StorageOperationError:
            logger.warning("S3 response cleanup failed while unwinding the read.")
        raise
    else:
        await response.close()


def validated_presigned_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise StorageOperationError(
            StorageFailure.INVALID_PRESIGN_RESPONSE, recovery=StorageRecovery.TERMINAL
        )
    return value


class S3UploadExtraArgs(BaseModel):
    """Only the upload options used by Eylo's stable-key object writer."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    content_type: str = Field(serialization_alias="ContentType")
    metadata: dict[str, str] | None = Field(
        default=None, serialization_alias="Metadata", repr=False
    )

    def to_sdk(self) -> dict[str, str | dict[str, str]]:
        return (
            type(self)
            .model_validate(self)
            .model_dump(mode="python", by_alias=True, exclude_none=True)
        )


class S3ObjectSummary(BaseModel):
    """Key and byte size required to screen an object without downloading it."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
        validate_by_name=True,
    )

    key: str = Field(alias="Key", repr=False)
    size: int = Field(alias="Size", ge=0)


class S3ListObjectsResponse(BaseModel):
    """An empty listing may omit Contents; malformed entries invalidate the page."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
        validate_by_name=True,
    )

    contents: list[S3ObjectSummary] = Field(
        default_factory=list, alias="Contents", repr=False
    )

    @classmethod
    def from_sdk(cls, value: object) -> S3ListObjectsResponse:
        try:
            return cls.model_validate(value)
        except ValidationError:
            raise StorageOperationError(
                StorageFailure.INVALID_LIST_RESPONSE, recovery=StorageRecovery.TERMINAL
            ) from None


class S3HeadObjectResponse(BaseModel):
    """Consumed HEAD metadata; an actual zero-byte object is distinct from no size."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
        validate_by_name=True,
    )

    content_length: int = Field(alias="ContentLength", ge=0)
    metadata: dict[str, str] = Field(default_factory=dict, alias="Metadata", repr=False)

    @classmethod
    def from_sdk(cls, value: object) -> S3HeadObjectResponse:
        try:
            return cls.model_validate(value)
        except ValidationError:
            raise StorageOperationError(
                StorageFailure.INVALID_INSPECT_RESPONSE,
                recovery=StorageRecovery.TERMINAL,
            ) from None


class S3ServiceErrorCode(StrEnum):
    """Known AWS codes used for classification; unknown codes remain valid native data."""

    NO_SUCH_KEY = "NoSuchKey"
    NOT_FOUND = "NotFound"
    HTTP_NOT_FOUND = "404"
    ACCESS_DENIED = "AccessDenied"
    EXPIRED_TOKEN = "ExpiredToken"
    INVALID_ACCESS_KEY_ID = "InvalidAccessKeyId"
    SIGNATURE_DOES_NOT_MATCH = "SignatureDoesNotMatch"


class _S3ErrorValue(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        revalidate_instances="always",
        validate_by_name=True,
        hide_input_in_errors=True,
    )


class S3ErrorDetail(_S3ErrorValue):
    code: str = Field(default="", alias="Code", repr=False)


class S3ErrorMetadata(_S3ErrorValue):
    status: int | None = Field(
        default=None,
        alias="HTTPStatusCode",
        ge=HTTPStatus.CONTINUE,
        lt=HTTP_STATUS_EXCLUSIVE_UPPER_BOUND,
    )


class S3ErrorResponse(_S3ErrorValue):
    """Only status/code drive classification; messages and headers are discarded."""

    error: S3ErrorDetail = Field(
        default_factory=S3ErrorDetail, alias="Error", repr=False
    )
    metadata: S3ErrorMetadata = Field(
        default_factory=S3ErrorMetadata, alias="ResponseMetadata"
    )

    @classmethod
    def from_sdk(cls, value: object) -> S3ErrorResponse:
        try:
            return cls.model_validate(value)
        except ValidationError:
            raise StorageOperationError(
                StorageFailure.INVALID_ERROR_RESPONSE, recovery=StorageRecovery.TERMINAL
            ) from None

    @property
    def missing(self) -> bool:
        return (
            self.error.code
            in {
                S3ServiceErrorCode.NO_SUCH_KEY,
                S3ServiceErrorCode.NOT_FOUND,
                S3ServiceErrorCode.HTTP_NOT_FOUND,
            }
            or self.metadata.status == HTTPStatus.NOT_FOUND
        )

    @property
    def recovery(self) -> StorageRecovery:
        status = self.metadata.status
        if status == HTTPStatus.TOO_MANY_REQUESTS or (
            status is not None and status >= HTTPStatus.INTERNAL_SERVER_ERROR
        ):
            return StorageRecovery.RETRY
        return StorageRecovery.TERMINAL

    @property
    def failure(self) -> StorageFailure:
        if self.metadata.status in {
            HTTPStatus.UNAUTHORIZED,
            HTTPStatus.FORBIDDEN,
        } or self.error.code in {
            S3ServiceErrorCode.ACCESS_DENIED,
            S3ServiceErrorCode.EXPIRED_TOKEN,
            S3ServiceErrorCode.INVALID_ACCESS_KEY_ID,
            S3ServiceErrorCode.SIGNATURE_DOES_NOT_MATCH,
        }:
            return StorageFailure.AUTHENTICATION
        if self.recovery is StorageRecovery.RETRY:
            return StorageFailure.PROVIDER_UNAVAILABLE
        return StorageFailure.PROVIDER_REJECTED
