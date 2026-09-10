"""Linear-native GraphQL response contracts shared by the SOR profile adapters."""

from enum import StrEnum
from http import HTTPStatus

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sor.runtime.http import SorJsonResponse
from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)

_ERROR_MESSAGE_LIMIT = 500


class LinearGraphQLErrorCode(StrEnum):
    """Native codes understood by Eylo; unknown vendor codes remain terminal."""

    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    RATELIMITED = "RATELIMITED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


class LinearGraphQLErrorExtensions(BaseModel):
    """Preserve unfamiliar error codes without accepting non-string codes."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)

    code: str | None = None

    @property
    def known_code(self) -> LinearGraphQLErrorCode | None:
        try:
            return LinearGraphQLErrorCode((self.code or "").upper())
        except ValueError:
            return None


class LinearGraphQLError(BaseModel):
    """The error fields consumed by both adapters, not the entire vendor schema."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)

    message: str | None = Field(default=None, repr=False)
    extensions: LinearGraphQLErrorExtensions | None = None

    @property
    def known_code(self) -> LinearGraphQLErrorCode | None:
        return self.extensions.known_code if self.extensions is not None else None


class LinearGraphQLResponse(BaseModel):
    """Validate the envelope; each operation still owns its selected data schema."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)

    data: dict[str, object] | None = Field(default=None, repr=False)
    errors: list[LinearGraphQLError] | None = None


def linear_graphql_data(
    response: SorJsonResponse,
    *,
    operation: str,
) -> dict[str, object]:
    """Reject partial results and classify Linear's HTTP-400 rate-limit envelope.

    HTTP authorization/server failures retain precedence. The first GraphQL error
    retains the adapters' existing classification policy. No retry is performed
    here: the SOR runtime owns retry timing and mutation safety.
    """
    if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_AUTHORIZATION_FAILED,
            f"Linear refused authorization while attempting to {operation}.",
            recovery=(
                SorRecoveryPolicy.REFRESH_AND_RETRY
                if response.status_code == HTTPStatus.UNAUTHORIZED
                else SorRecoveryPolicy.REAUTH_REQUIRED
            ),
        )
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Linear rate limited the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_SERVER_FAILED,
            "Linear could not complete the operation.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if not response.ok and response.status_code != HTTPStatus.BAD_REQUEST:
        raise _request_rejected(operation)
    try:
        envelope = LinearGraphQLResponse.model_validate(response.data)
    except ValidationError:
        if not response.ok:
            raise _request_rejected(operation) from None
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Linear returned an invalid GraphQL response.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from None

    first_error = envelope.errors[0] if envelope.errors else None
    rate_limit_codes = {
        LinearGraphQLErrorCode.RATELIMITED,
        LinearGraphQLErrorCode.RATE_LIMITED,
    }
    if first_error is not None and first_error.known_code in rate_limit_codes:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RATE_LIMITED,
            "Linear could not complete the operation yet.",
            recovery=SorRecoveryPolicy.RETRY,
        )
    if not response.ok:
        raise _request_rejected(operation)
    if first_error is not None:
        if first_error.known_code in {
            LinearGraphQLErrorCode.AUTHENTICATION_ERROR,
            LinearGraphQLErrorCode.UNAUTHENTICATED,
            LinearGraphQLErrorCode.FORBIDDEN,
        }:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_AUTHORIZATION_FAILED,
                "Linear authorization is no longer valid.",
                recovery=SorRecoveryPolicy.REFRESH_AND_RETRY,
            )
        if first_error.known_code == LinearGraphQLErrorCode.INTERNAL_SERVER_ERROR:
            raise SorVendorOperationError(
                SorVendorErrorCode.VENDOR_SERVER_FAILED,
                "Linear could not complete the operation yet.",
                recovery=SorRecoveryPolicy.RETRY,
            )
        message = (first_error.message or "").strip()
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
            message[:_ERROR_MESSAGE_LIMIT] or "Linear rejected the operation.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    if envelope.data is None:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Linear returned no GraphQL data.",
            recovery=SorRecoveryPolicy.TERMINAL,
        )
    return envelope.data


def _request_rejected(operation: str) -> SorVendorOperationError:
    return SorVendorOperationError(
        SorVendorErrorCode.VENDOR_REQUEST_REJECTED,
        f"Linear rejected the request while attempting to {operation}.",
        recovery=SorRecoveryPolicy.TERMINAL,
    )
