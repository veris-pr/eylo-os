"""Salesforce REST envelopes and keyset values, separate from canonical CRM data."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum, StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue

MAX_PAGE_SIZE = 200
MAX_RESPONSE_ITEMS = 20_000
MAX_TEXT_CHARS = 1_000_000
SCHEMA_IDENTIFIER_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,255}$"
RECORD_ID_PATTERN = r"^[A-Za-z0-9]{15,18}$"


def optional_text(value: object) -> str | None:
    """Preserve the adapter's optional scalar-text normalization at ingress."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    normalized = str(value).strip()
    return normalized[:MAX_TEXT_CHARS] if normalized else None


OptionalText = Annotated[str | None, BeforeValidator(optional_text)]
RecordId = Annotated[
    str, Field(pattern=RECORD_ID_PATTERN), BeforeValidator(optional_text)
]
SchemaIdentifier = Annotated[str, Field(pattern=SCHEMA_IDENTIFIER_PATTERN)]


class SalesforceResponse(BaseModel):
    """Consumed fields are strict; unrelated vendor additions remain compatible."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class SalesforceObjectInfo(SalesforceResponse):
    name: OptionalText = None
    queryable: bool | None = None
    custom: bool | None = None
    deprecatedAndHidden: bool | None = None


class SalesforceCatalog(SalesforceResponse):
    sobjects: list[SalesforceObjectInfo] = Field(max_length=MAX_RESPONSE_ITEMS)


class SalesforcePicklistValue(SalesforceResponse):
    value: OptionalText = None
    active: bool | None = None


class SalesforceField(SalesforceResponse):
    name: SchemaIdentifier
    label: OptionalText = None
    type: OptionalText = None
    nillable: bool | None = None
    createable: bool | None = None
    updateable: bool | None = None
    inlineHelpText: OptionalText = None
    compoundFieldName: OptionalText = None
    picklistValues: list[SalesforcePicklistValue] | None = Field(
        default=None, max_length=MAX_RESPONSE_ITEMS
    )


class SalesforceDescribe(SalesforceResponse):
    fields: list[SalesforceField] = Field(max_length=MAX_RESPONSE_ITEMS)
    labelPlural: OptionalText = None
    label: OptionalText = None


class SalesforceFieldType(StrEnum):
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    CURRENCY = "currency"
    DOUBLE = "double"
    INTEGER = "int"
    LONG = "long"
    PERCENT = "percent"
    MULTIPICKLIST = "multipicklist"
    COMBOBOX = "combobox"
    PICKLIST = "picklist"
    EMAIL = "email"
    ENCRYPTED_STRING = "encryptedstring"
    ID = "id"
    PHONE = "phone"
    REFERENCE = "reference"
    STRING = "string"
    TEXTAREA = "textarea"
    TIME = "time"
    URL = "url"


class SalesforceSystemField(StrEnum):
    ID = "Id"
    CREATED_DATE = "CreatedDate"
    LAST_MODIFIED_DATE = "LastModifiedDate"
    SYSTEM_MODSTAMP = "SystemModstamp"


class SalesforceRecord(SalesforceResponse):
    """Stable row metadata plus finite custom fields defined by the source."""

    Id: RecordId
    CreatedDate: OptionalText = None
    LastModifiedDate: OptionalText = None
    SystemModstamp: OptionalText = None
    custom_fields: dict[str, SorJsonValue] = Field(repr=False)

    @model_validator(mode="before")
    @classmethod
    def separate_custom_fields(cls, value: object) -> object:
        """Retain every non-system field without inventing a fixed custom schema."""
        if not isinstance(value, dict):
            return value
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Salesforce record field names must be strings.")
        return {
            **{
                key: item for key, item in value.items() if key in SalesforceSystemField
            },
            "custom_fields": {
                key: item
                for key, item in value.items()
                if key not in SalesforceSystemField
            },
        }

    def field_value(self, key: str) -> SorJsonValue:
        """Only the published mapping chooses dynamic field names to expose."""
        if key == SalesforceSystemField.ID:
            return self.Id
        if key == SalesforceSystemField.CREATED_DATE:
            return self.CreatedDate
        if key == SalesforceSystemField.LAST_MODIFIED_DATE:
            return self.LastModifiedDate
        if key == SalesforceSystemField.SYSTEM_MODSTAMP:
            return self.SystemModstamp
        return self.custom_fields.get(key)


class SalesforceQueryResult(SalesforceResponse):
    records: list[SalesforceRecord] = Field(max_length=MAX_RESPONSE_ITEMS)
    done: bool


class SalesforceCreateResult(SalesforceResponse):
    id: RecordId


class SalesforceRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )


class SalesforceQueryRequest(SalesforceRequest):
    q: str = Field(min_length=1, repr=False)


class SalesforceFieldsRequest(SalesforceRequest):
    fields: str = Field(min_length=1)


class SalesforceWrite(RootModel[dict[str, SorJsonValue]]):
    """The writable mapping owns field names; the boundary owns JSON validity."""

    model_config = ConfigDict(frozen=True, strict=True, hide_input_in_errors=True)

    def __repr_args__(self) -> tuple[tuple[str, object], ...]:
        """Do not render writable customer data in diagnostic representations."""
        return ()


class SalesforceCursorVersion(IntEnum):
    KEYSET_V1 = 1


class SalesforceCheckpoint(SalesforceRequest):
    """Typed checkpoint retains the existing id/stamp/v durable representation."""

    id: RecordId
    stamp: AwareDatetime
    v: SalesforceCursorVersion

    @field_validator("stamp")
    @classmethod
    def normalize_stamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @field_validator("v", mode="before")
    @classmethod
    def validate_version(cls, value: object) -> SalesforceCursorVersion:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Invalid Salesforce cursor version.")
        return SalesforceCursorVersion(value)


def parse_response[T: SalesforceResponse](model: type[T], value: object) -> T:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Salesforce returned an invalid response.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from None
