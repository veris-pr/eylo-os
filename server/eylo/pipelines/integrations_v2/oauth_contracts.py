"""Private authorization inputs, completion receipts and owned failure codes."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)

from eylo.modules.integrations_v2.domain.errors import IntegrationsV2Error

AUTHORIZATION_CODE_GRANT = "authorization_code"


class CuratedOAuthCode(StrEnum):
    STATE_INVALID = "oauth_state_invalid"
    STATE_EXPIRED = "oauth_state_expired"
    APP_MISSING = "oauth_app_missing"
    TENANT_INVALID = "oauth_tenant_invalid"
    ENDPOINT_UNREACHABLE = "oauth_endpoint_unreachable"
    EXCHANGE_REJECTED = "oauth_exchange_rejected"
    TOKEN_INVALID = "oauth_token_invalid"
    REQUEST_INVALID = "oauth_request_invalid"
    CALLBACK_NOT_CONFIGURED = "oauth_callback_not_configured"
    INSTALLATION_REMOVED = "installation_removed"
    VENDOR_NOT_REGISTERED = "vendor_not_registered"
    VENDOR_OAUTH_UNSUPPORTED = "vendor_oauth_unsupported"


class AuthorizationRejection(StrEnum):
    """Provider callback outcomes with platform-owned, credential-safe copy."""

    DECLINED = "declined"
    CODE_MISSING = "code_missing"

    @property
    def message(self) -> str:
        if self is AuthorizationRejection.DECLINED:
            return "Authorization was declined at the provider."
        return "The provider returned no authorization code."


class CuratedOAuthError(IntegrationsV2Error):
    """Authorization failure with a finite code, never a vendor response body."""

    def __init__(self, code: CuratedOAuthCode, message: str) -> None:
        if not isinstance(code, CuratedOAuthCode):
            raise TypeError("OAuth failure requires a CuratedOAuthCode.")
        super().__init__(code, message)


class AuthorizationRedirect(BaseModel):
    """Explicit consent output; state-bearing values stay out of snapshots."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    authorization_url: str = Field(min_length=1, repr=False, exclude=True)
    redirect_uri: str = Field(min_length=1)
    state: str = Field(min_length=1, repr=False, exclude=True)


class AuthorizationCompletion(BaseModel):
    """Completed account identity for the callback's public projection."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    connection_id: UUID
    vendor: str = Field(min_length=1)


class AuthorizationCodeRequest(BaseModel):
    """Private token form; serialize only into the pinned egress request."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    code: str = Field(min_length=1, repr=False, exclude=True)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1, repr=False, exclude=True)
    redirect_uri: str = Field(min_length=1)
    code_verifier: str | None = Field(default=None, repr=False, exclude=True)

    @model_validator(mode="wrap")
    @classmethod
    def _safe_request(
        cls, value: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(value)
        except ValidationError:
            raise CuratedOAuthError(
                CuratedOAuthCode.REQUEST_INVALID, "Authorization request is invalid."
            ) from None

    def to_form(self) -> dict[str, str]:
        validated = type(self).model_validate(self)
        form = {
            "grant_type": AUTHORIZATION_CODE_GRANT,
            "code": validated.code,
            "client_id": validated.client_id,
            "client_secret": validated.client_secret,
            "redirect_uri": validated.redirect_uri,
        }
        if validated.code_verifier:
            form["code_verifier"] = validated.code_verifier
        return form
