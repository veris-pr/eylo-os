"""Validate Sheets HTTP envelopes and native operation results without resends."""

from pydantic import ValidationError

from ...contracts import VendorResponse, VendorToolError
from .schemas import (
    MAX_ERROR_MESSAGE_CHARS,
    SheetsEnvelope,
    SheetsErrorCode,
    SheetsModel,
)


def parse_response[ResultT: SheetsModel](
    response: VendorResponse, response_model: type[ResultT]
) -> ResultT:
    """A mutation already has its outbound receipt; parsing never repeats it."""
    try:
        envelope = SheetsEnvelope.model_validate(response.data)
    except ValidationError:
        raise VendorToolError(
            SheetsErrorCode.RESPONSE_INVALID,
            "Google Sheets returned an invalid response envelope.",
        ) from None
    if envelope.error is not None:
        raise VendorToolError(
            SheetsErrorCode.REJECTED,
            envelope.error.message[:MAX_ERROR_MESSAGE_CHARS],
        )
    if not response.ok:
        raise VendorToolError(
            SheetsErrorCode.REJECTED,
            f"Google Sheets rejected the request with HTTP {response.status_code}.",
        )
    try:
        return response_model.model_validate(response.data)
    except ValidationError:
        raise VendorToolError(
            SheetsErrorCode.RESPONSE_INVALID,
            "Google Sheets returned an invalid result for the operation.",
        ) from None
