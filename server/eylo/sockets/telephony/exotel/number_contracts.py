"""Documented Exotel v2_beta available-number request and response values."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SEARCH_DEFAULT_LIMIT = 20
SEARCH_TIMEOUT_SECONDS = 15


class NumberType(StrEnum):
    LANDLINE = "Landline"
    TOLL_FREE = "TollFree"
    MOBILE = "Mobile"


class SearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    region: str | None = Field(default=None, serialization_alias="InRegion")
    contains: str | None = Field(default=None, serialization_alias="Contains")


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
