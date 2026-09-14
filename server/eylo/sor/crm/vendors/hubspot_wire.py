"""HubSpot CRM wire envelopes; custom property names remain vendor-owned JSON."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue

MAX_PAGE_SIZE = 100
MAX_RESPONSE_ITEMS = 20_000
MAX_BATCH_INPUTS = 1_000
MAX_IDENTIFIER_CHARS = 320
MAX_TEXT_CHARS = 1_000_000


def optional_text(value: object) -> str | None:
    """Preserve the adapter's string/integer text normalization at ingress."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    result = str(value).strip()
    return result[:MAX_TEXT_CHARS] if result else None


def identifier(value: object) -> str:
    result = optional_text(value)
    if (
        result is None
        or len(result) > MAX_IDENTIFIER_CHARS
        or any(character in result for character in "/?#")
    ):
        raise ValueError("Invalid HubSpot identifier.")
    return result


HubSpotId = Annotated[str, BeforeValidator(identifier)]
OptionalText = Annotated[str | None, BeforeValidator(optional_text)]


class HubSpotResponse(BaseModel):
    """Validate consumed fields; vendor additions do not invalidate a response."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class HubSpotAccount(HubSpotResponse):
    portalId: HubSpotId
    accountType: OptionalText = None


class HubSpotPropertyType(StrEnum):
    BOOLEAN = "bool"
    DATE = "date"
    DATETIME = "datetime"
    ENUMERATION = "enumeration"
    NUMBER = "number"
    PHONE_NUMBER = "phone_number"
    STRING = "string"


class HubSpotFieldType(StrEnum):
    CHECKBOX = "checkbox"
    MULTI_CHECKBOX = "multi_checkbox"


class HubSpotPropertyOption(HubSpotResponse):
    value: OptionalText = None
    hidden: bool | None = None


class HubSpotPropertyModification(HubSpotResponse):
    readOnlyValue: bool | None = None


class HubSpotProperty(HubSpotResponse):
    name: str = Field(min_length=1)
    label: OptionalText = None
    type: OptionalText = None
    fieldType: OptionalText = None
    description: OptionalText = None
    groupName: OptionalText = None
    archived: bool | None = None
    calculated: bool | None = None
    modificationMetadata: HubSpotPropertyModification | None = None
    options: list[HubSpotPropertyOption] | None = Field(
        default=None, max_length=MAX_RESPONSE_ITEMS
    )


class HubSpotProperties(HubSpotResponse):
    results: list[HubSpotProperty] = Field(max_length=MAX_RESPONSE_ITEMS)


class HubSpotNextPage(HubSpotResponse):
    after: OptionalText = None


class HubSpotPaging(HubSpotResponse):
    next: HubSpotNextPage | None = None

    @property
    def cursor(self) -> str | None:
        return self.next.after if self.next is not None else None


class HubSpotRecordIdentity(HubSpotResponse):
    id: HubSpotId
    updatedAt: OptionalText = None
    url: OptionalText = None


class HubSpotRecord(HubSpotRecordIdentity):
    properties: dict[str, SorJsonValue] | None = Field(default=None, repr=False)
    createdAt: OptionalText = None
    archivedAt: OptionalText = None
    archived: bool | None = None


class HubSpotRecords(HubSpotResponse):
    results: list[HubSpotRecord] = Field(max_length=MAX_RESPONSE_ITEMS)
    paging: HubSpotPaging | None = None


class HubSpotAssociationSource(HubSpotResponse):
    id: HubSpotId


class HubSpotAssociationTarget(HubSpotResponse):
    toObjectId: HubSpotId


class HubSpotAssociationRow(HubSpotResponse):
    source: HubSpotAssociationSource = Field(alias="from")
    to: list[HubSpotAssociationTarget] = Field(max_length=MAX_RESPONSE_ITEMS)
    paging: HubSpotPaging | None = None


class HubSpotAssociationErrorContext(HubSpotResponse):
    fromObjectId: list[HubSpotId] = Field(default_factory=list)
    fromObjectType: list[HubSpotId] = Field(default_factory=list)
    toObjectType: list[HubSpotId] = Field(default_factory=list)


class HubSpotAssociationError(HubSpotResponse):
    category: OptionalText = None
    subCategory: OptionalText = None
    context: HubSpotAssociationErrorContext | None = None


class HubSpotAssociations(HubSpotResponse):
    results: list[HubSpotAssociationRow] = Field(max_length=MAX_RESPONSE_ITEMS)
    errors: list[HubSpotAssociationError] | None = Field(
        default=None, max_length=MAX_RESPONSE_ITEMS
    )


class HubSpotAssociationErrorCategory(StrEnum):
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"


class HubSpotAssociationErrorSubcategory(StrEnum):
    NO_ASSOCIATIONS = "crm.associations.NO_ASSOCIATIONS_FOUND"


class HubSpotRequest(BaseModel):
    """Requests are code-owned; unknown fields are construction errors."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class HubSpotReadQuery(HubSpotRequest):
    archived: bool = False
    properties: str | None = None


class HubSpotPageQuery(HubSpotReadQuery):
    limit: int = Field(gt=0, le=MAX_PAGE_SIZE)
    after: str | None = None


class HubSpotAssociationInput(HubSpotRequest):
    id: HubSpotId
    after: str | None = None


class HubSpotAssociationRead(HubSpotRequest):
    inputs: list[HubSpotAssociationInput] = Field(
        min_length=1, max_length=MAX_BATCH_INPUTS
    )


class HubSpotWrite(HubSpotRequest):
    properties: dict[str, SorJsonValue] = Field(repr=False)


def parse_response[T: HubSpotResponse](model: type[T], value: object) -> T:
    """Expose a stable vendor failure without retaining raw response content."""
    try:
        return model.model_validate(value)
    except ValidationError:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "HubSpot returned an invalid response.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from None
