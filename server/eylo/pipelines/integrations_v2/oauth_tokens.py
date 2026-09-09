"""OAuth token wire response shared by initial exchange and credential refresh."""

import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)


class OAuthTokenErrorCode(StrEnum):
    INVALID_RESPONSE = "invalid_response"
    MISSING_ACCESS_TOKEN = "missing_access_token"


class OAuthTokenError(Exception):
    """Token parsing failure without retaining response bodies or secret values."""

    def __init__(self, code: OAuthTokenErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class OAuthTokenResponse(BaseModel):
    """OAuth token response fields consumed by refresh; extensions are ignored."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    access_token: str = Field(min_length=1, repr=False, exclude=True)
    refresh_token: str | None = Field(default=None, repr=False, exclude=True)
    token_type: str | None = None
    scope: str | None = None
    expires_in: int | None = Field(default=None, ge=0)

    @model_validator(mode="wrap")
    @classmethod
    def _safe_response(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise OAuthTokenError(OAuthTokenErrorCode.INVALID_RESPONSE) from None

    @classmethod
    def from_body(cls, body: bytes) -> Self:
        try:
            payload = json.loads(body)
        except ValueError:
            raise OAuthTokenError(OAuthTokenErrorCode.INVALID_RESPONSE) from None
        if not isinstance(payload, dict):
            raise OAuthTokenError(OAuthTokenErrorCode.INVALID_RESPONSE)
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthTokenError(OAuthTokenErrorCode.MISSING_ACCESS_TOKEN)
        return cls.model_validate(payload)

    def expires_at(self, now: datetime) -> datetime | None:
        validated = type(self).model_validate(self)
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ValueError("Refresh clock must be timezone-aware.")
        if validated.expires_in is None:
            return None
        try:
            return now + timedelta(seconds=validated.expires_in)
        except OverflowError:
            raise OAuthTokenError(OAuthTokenErrorCode.INVALID_RESPONSE) from None
