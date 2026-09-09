"""Typed refresh receipts, private token material and bounded failure metadata."""

from enum import StrEnum
from typing import Literal, Self, TypedDict
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)

from eylo.modules.connections.schemas.external import ExternalConnectionInDb

_REFRESH_GRANT_TYPE = "refresh_token"
_MIN_HTTP_STATUS = 100
_MAX_HTTP_STATUS = 599


class RefreshErrorCode(StrEnum):
    INSTALLATION_REMOVED = "installation_removed"
    VENDOR_NO_LONGER_CARRIED = "vendor_no_longer_carried"
    OAUTH_APP_MISSING = "oauth_app_missing"
    CREDENTIALS_UNAVAILABLE = "credentials_unavailable"
    CREDENTIALS_UNREADABLE = "credentials_unreadable"
    REFRESH_TOKEN_UNAVAILABLE = "refresh_token_unavailable"
    OAUTH_APP_UNREADABLE = "oauth_app_unreadable"
    NO_ACCESS_TOKEN_RETURNED = "no_access_token_returned"
    TOKEN_ENDPOINT_UNREACHABLE = "token_endpoint_unreachable"
    REFRESH_TOKEN_REJECTED = "refresh_token_rejected"
    TOKEN_ENDPOINT_HTTP = "token_endpoint_http"
    TOKEN_RESPONSE_UNREADABLE = "token_response_unreadable"
    TOKEN_REQUEST_INVALID = "token_request_invalid"


class RefreshDisposition(StrEnum):
    RETRY = "retry"
    REAUTHORIZE = "reauthorize"


class RefreshFailure(BaseModel):
    """Value-free diagnostic; HTTP status is separate from the finite code."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    code: RefreshErrorCode
    disposition: RefreshDisposition = RefreshDisposition.RETRY
    vendor: str | None = None
    installation_id: UUID | None = None
    http_status: int | None = Field(
        default=None, ge=_MIN_HTTP_STATUS, le=_MAX_HTTP_STATUS
    )

    @model_validator(mode="after")
    def _http_status_agrees(self) -> Self:
        if (self.code is RefreshErrorCode.TOKEN_ENDPOINT_HTTP) != (
            self.http_status is not None
        ):
            raise ValueError("HTTP refresh failures require an HTTP status only.")
        return self

    @property
    def persisted_code(self) -> str:
        """Keep existing DB diagnostic spelling without arbitrary error codes."""
        if self.http_status is not None:
            return f"{self.code.value}_{self.http_status}"
        return self.code.value


class RefreshError(Exception):
    """A validated failure that contains no token response or credential values."""

    def __init__(
        self,
        code: RefreshErrorCode,
        *,
        disposition: RefreshDisposition = RefreshDisposition.RETRY,
        vendor: str | None = None,
        installation_id: UUID | None = None,
        http_status: int | None = None,
    ) -> None:
        self.failure = RefreshFailure(
            code=code,
            disposition=disposition,
            vendor=vendor,
            installation_id=installation_id,
            http_status=http_status,
        )
        super().__init__(self.failure.persisted_code)


class RefreshOutcome(BaseModel):
    """Connection IDs renewed, failed, or superseded during one cycle."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    refreshed: tuple[UUID, ...]
    failed: tuple[UUID, ...]
    skipped: tuple[UUID, ...] = ()

    @property
    def considered(self) -> int:
        return len(self.refreshed) + len(self.failed) + len(self.skipped)


class RefreshTaskStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class RefreshTaskSucceeded(TypedDict):
    """Existing scheduled-task JSON projection of a completed refresh cycle."""

    status: Literal[RefreshTaskStatus.SUCCESS]
    refreshed_count: int
    failed_count: int
    skipped_count: int


class RefreshTaskFailed(TypedDict):
    """Value-free scheduled-task failure; the next periodic tick can retry."""

    status: Literal[RefreshTaskStatus.ERROR]
    error: str


type RefreshTaskResult = RefreshTaskSucceeded | RefreshTaskFailed


class RenewedCredential(BaseModel):
    """Detached connection receipt; plaintext credentials never enter snapshots."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    connection: ExternalConnectionInDb
    credentials: dict[str, JsonValue] = Field(repr=False, exclude=True)
    expires_at: AwareDatetime | None

    @model_validator(mode="wrap")
    @classmethod
    def _safe_receipt(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise RefreshError(RefreshErrorCode.TOKEN_RESPONSE_UNREADABLE) from None


class RefreshTokenRequest(BaseModel):
    """Private form input; serialization is explicit at the egress boundary."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1, repr=False, exclude=True)
    refresh_token: str = Field(min_length=1, repr=False, exclude=True)

    @model_validator(mode="wrap")
    @classmethod
    def _safe_request(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise RefreshError(RefreshErrorCode.TOKEN_REQUEST_INVALID) from None

    def to_form(self) -> dict[str, str]:
        validated = type(self).model_validate(self)
        return {
            "grant_type": _REFRESH_GRANT_TYPE,
            "refresh_token": validated.refresh_token,
            "client_id": validated.client_id,
            "client_secret": validated.client_secret,
        }
