"""Vonage Numbers API requests, search records and explicit purchase acceptance."""

from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

NUMBER_ORIGIN = "https://rest.nexmo.com"
SEARCH_DEFAULT_LIMIT = 20
SEARCH_MAX_LIMIT = 100
SEARCH_TIMEOUT_SECONDS = 15
PURCHASE_TIMEOUT_SECONDS = 20


class NumberType(StrEnum):
    LANDLINE = "landline"
    TOLL_FREE = "landline-toll-free"
    MOBILE = "mobile-lvn"


class Feature(StrEnum):
    VOICE = "VOICE"
    SMS = "SMS"
    MMS = "MMS"


class PatternMatch(IntEnum):
    CONTAINS = 1


class PurchaseCode(StrEnum):
    SUCCESS = "200"
    # Existing Eylo compatibility; current Numbers documentation specifies 200.
    LEGACY_SUCCESS = "0"


class _Request(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )


class SearchRequest(_Request):
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    country: str
    type: NumberType
    features: Feature = Feature.VOICE
    size: int = Field(ge=1, le=SEARCH_MAX_LIMIT)
    pattern: str | None = None
    search_pattern: PatternMatch | None = None


class PurchaseRequest(_Request):
    api_key: str = Field(repr=False)
    api_secret: str = Field(repr=False)
    country: str
    msisdn: str = Field(repr=False)


class _Response(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class AvailableNumber(_Response):
    msisdn: str = Field(min_length=1, repr=False)
    country: str | None = None
    features: list[Feature] | None = None

    @property
    def enabled_capabilities(self) -> dict[str, bool]:
        return {feature.value.lower(): True for feature in self.features or []}


class SearchResponse(_Response):
    numbers: list[AvailableNumber] = Field(default_factory=list)


class PurchaseResponse(_Response):
    # Keep unknown vendor codes as text so the adapter can classify a refusal.
    error_code: str = Field(alias="error-code", min_length=1)
