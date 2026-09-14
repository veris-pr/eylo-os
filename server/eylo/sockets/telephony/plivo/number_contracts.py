"""Plivo PhoneNumber API search and confirmed-purchase wire values."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eylo.common.outbound import OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH

NUMBER_ORIGIN = "https://api.plivo.com"
SEARCH_LIMIT = 20
SEARCH_TIMEOUT_SECONDS = 15
PURCHASE_TIMEOUT_SECONDS = 20


class NumberType(StrEnum):
    LOCAL = "local"
    TOLL_FREE = "tollfree"
    MOBILE = "mobile"


class Feature(StrEnum):
    VOICE = "voice"
    SMS = "sms"
    MMS = "mms"


class LegacyFeatureState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class PurchaseStatus(StrEnum):
    FULFILLED = "fulfilled"
    NUMBER_SUCCESS = "Success"


class SearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    country_iso: str
    type: NumberType
    limit: int = Field(ge=1, le=SEARCH_LIMIT)
    pattern: str | None = None


class _Response(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class AvailableNumber(_Response):
    number: str = Field(min_length=1, repr=False)
    city: str | None = None
    region: str | None = None
    country: str | None = None
    voice_enabled: bool | None = None
    sms_enabled: bool | None = None
    mms_enabled: bool | None = None
    # Preserve the adapter's prior explicit legacy spelling; native flags are above.
    voice: LegacyFeatureState | None = None
    sms: LegacyFeatureState | None = None
    mms: LegacyFeatureState | None = None

    @property
    def enabled_capabilities(self) -> dict[str, bool]:
        flags = {
            Feature.VOICE: self.voice_enabled is True
            or self.voice is LegacyFeatureState.ENABLED,
            Feature.SMS: self.sms_enabled is True
            or self.sms is LegacyFeatureState.ENABLED,
            Feature.MMS: self.mms_enabled is True
            or self.mms is LegacyFeatureState.ENABLED,
        }
        return {feature.value: True for feature, enabled in flags.items() if enabled}


class SearchResponse(_Response):
    objects: list[AvailableNumber] = Field(default_factory=list)


class PurchasedNumber(_Response):
    number: str = Field(min_length=1, repr=False)
    status: Literal[PurchaseStatus.NUMBER_SUCCESS]


class ConfirmedPurchase(_Response):
    """Only fulfilled, single-number acceptance can activate the local resource."""

    api_id: str = Field(
        min_length=1, max_length=OUTBOUND_PROVIDER_REFERENCE_MAX_LENGTH, pattern=r"\S"
    )
    numbers: list[PurchasedNumber] = Field(min_length=1, max_length=1)
    status: Literal[PurchaseStatus.FULFILLED]
