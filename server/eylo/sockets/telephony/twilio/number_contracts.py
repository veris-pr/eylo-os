"""Consumed Twilio phone-number search and provisioning wire contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

NUMBER_SEARCH_TIMEOUT_SECONDS = 15
NUMBER_PURCHASE_TIMEOUT_SECONDS = 20
NUMBER_SEARCH_DEFAULT_LIMIT = 20
NUMBER_SEARCH_MAX_LIMIT = 30


class NumberType(StrEnum):
    LOCAL = "Local"
    TOLL_FREE = "TollFree"
    MOBILE = "Mobile"


class NumberFailureCode(StrEnum):
    RESPONSE_INVALID = "number_purchase_response_invalid"
    IDENTITY_MISMATCH = "number_purchase_identity_mismatch"


class NumberSearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    page_size: int = Field(
        serialization_alias="PageSize", ge=1, le=NUMBER_SEARCH_MAX_LIMIT
    )
    area_code: str | None = Field(default=None, serialization_alias="AreaCode")
    contains: str | None = Field(default=None, serialization_alias="Contains")


class NumberPurchaseRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    phone_number: str = Field(serialization_alias="PhoneNumber", repr=False)


class _Response(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class AvailableNumber(_Response):
    phone_number: str = Field(min_length=1, repr=False)
    friendly_name: str = ""
    locality: str | None = None
    region: str | None = None
    iso_country: str | None = None
    # Vendor capability names are returned verbatim; values are native predicates.
    capabilities: dict[str, bool] | None = None


class AvailableNumbersResponse(_Response):
    available_phone_numbers: list[AvailableNumber] = Field(default_factory=list)


class PurchasedNumber(_Response):
    """A provisioning receipt must identify the created IncomingPhoneNumber."""

    sid: str = Field(min_length=1, pattern=r"\S")
    phone_number: str | None = Field(default=None, repr=False)
