"""Exotel v2_beta number search and purchase wire contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from eylo.common.outbound import OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH

SEARCH_DEFAULT_LIMIT = 20
SEARCH_TIMEOUT_SECONDS = 15
PURCHASE_TIMEOUT_SECONDS = 20


class NumberType(StrEnum):
    LANDLINE = "Landline"
    TOLL_FREE = "TollFree"
    MOBILE = "Mobile"


class SearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    region: str | None = Field(default=None, serialization_alias="InRegion")
    contains: str | None = Field(default=None, serialization_alias="Contains")


class PurchaseRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    phone_number: str = Field(
        min_length=1, pattern=r"\S", repr=False, serialization_alias="PhoneNumber"
    )


class _Response(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class Capabilities(_Response):
    voice: bool | None = None
    sms: bool | None = None


class AvailableNumber(_Response):
    phone_number: str = Field(min_length=1, repr=False)
    friendly_name: str = ""
    region: str | None = None
    country: str | None = None
    capabilities: Capabilities | None = None

    @property
    def enabled_capabilities(self) -> dict[str, bool]:
        if self.capabilities is None:
            return {}
        return {
            name: True
            for name, value in self.capabilities.model_dump().items()
            if value is True
        }


AVAILABLE_NUMBERS = TypeAdapter(list[AvailableNumber])


class PurchasedNumber(_Response):
    """A confirmed purchase must identify the allocated number and its receipt."""

    sid: str = Field(
        min_length=1, max_length=OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH, pattern=r"\S"
    )
    phone_number: str = Field(min_length=1, pattern=r"\S", repr=False)
