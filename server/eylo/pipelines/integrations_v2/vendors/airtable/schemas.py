"""Airtable native envelopes and collision-free tool results; cells remain user-defined JSON."""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from ...contracts import VendorResponse, VendorToolError

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_CURSOR_CHARS = 2_048


class AirtableErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    TABLE_NOT_FOUND = "table_not_found"
    TABLE_AMBIGUOUS = "table_ambiguous"
    FIELD_NOT_FOUND = "field_not_found"
    FIELD_AMBIGUOUS = "field_ambiguous"
    NO_CHANGE = "no_change_requested"


class PermissionLevel(StrEnum):
    NONE = "none"
    READ = "read"
    COMMENT = "comment"
    EDIT = "edit"
    CREATE = "create"
    INTERFACE_ONLY = "interfaceOnly"


class FieldType(StrEnum):
    AI_TEXT = "aiText"
    ATTACHMENTS = "multipleAttachments"
    AUTO_NUMBER = "autoNumber"
    BARCODE = "barcode"
    BUTTON = "button"
    CHECKBOX = "checkbox"
    COLLABORATOR = "singleCollaborator"
    COUNT = "count"
    CREATED_BY = "createdBy"
    CREATED_TIME = "createdTime"
    CURRENCY = "currency"
    DATE = "date"
    DATE_TIME = "dateTime"
    DURATION = "duration"
    EMAIL = "email"
    FORMULA = "formula"
    LAST_MODIFIED_BY = "lastModifiedBy"
    LAST_MODIFIED_TIME = "lastModifiedTime"
    RECORD_LINKS = "multipleRecordLinks"
    MULTILINE_TEXT = "multilineText"
    LOOKUP = "multipleLookupValues"
    COLLABORATORS = "multipleCollaborators"
    MULTIPLE_SELECTS = "multipleSelects"
    NUMBER = "number"
    PERCENT = "percent"
    PHONE = "phoneNumber"
    RATING = "rating"
    RICH_TEXT = "richText"
    ROLLUP = "rollup"
    SINGLE_LINE_TEXT = "singleLineText"
    SINGLE_SELECT = "singleSelect"
    SYNC_SOURCE = "externalSyncSource"
    URL = "url"


class PartialSuccessReason(StrEnum):
    ATTACHMENTS_FAILED = "attachmentsFailedUploading"
    ATTACHMENT_RATE_LIMIT = "attachmentUploadRateIsTooHigh"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Airtable timestamps require a timezone.")
    return value


BaseId = Annotated[str, Field(pattern=r"^app[A-Za-z0-9]+$")]
TableId = Annotated[str, Field(pattern=r"^tbl[A-Za-z0-9]+$")]
RecordId = Annotated[str, Field(pattern=r"^rec[A-Za-z0-9]+$")]
FieldId = Annotated[str, Field(pattern=r"^fld[A-Za-z0-9]+$")]
ViewId = Annotated[str, Field(pattern=r"^viw[A-Za-z0-9]+$")]
Name = Annotated[str, Field(min_length=1, pattern=r"^[^\x00-\x1f\x7f]+$")]
Cursor = Annotated[
    str,
    Field(min_length=1, max_length=MAX_CURSOR_CHARS, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
Timestamp = Annotated[str, AfterValidator(timestamp)]
NativePermission = Annotated[
    PermissionLevel,
    BeforeValidator(
        lambda value: PermissionLevel(value) if isinstance(value, str) else value
    ),
]
NativeFieldType = Annotated[
    FieldType,
    BeforeValidator(
        lambda value: FieldType(value) if isinstance(value, str) else value
    ),
]
NativePartialReason = Annotated[
    PartialSuccessReason,
    BeforeValidator(
        lambda value: PartialSuccessReason(value) if isinstance(value, str) else value
    ),
]


class AirtableModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        strict=True,
        allow_inf_nan=False,
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class Base(AirtableModel):
    id: BaseId
    name: Name
    permission: NativePermission = Field(alias="permissionLevel")


class BasesPage(AirtableModel):
    bases: list[Base]
    offset: Cursor | None = None


class TableField(AirtableModel):
    id: FieldId
    name: Name
    type: NativeFieldType


class TableView(AirtableModel):
    id: ViewId
    name: Name


class Table(AirtableModel):
    id: TableId
    name: Name
    fields: list[TableField]
    views: list[TableView]


class TablesPage(AirtableModel):
    tables: list[Table]


class PartialSuccess(AirtableModel):
    message: Literal["partialSuccess"]
    reasons: list[NativePartialReason] = Field(min_length=1)


class Record(AirtableModel):
    id: RecordId
    created_at: Timestamp = Field(alias="createdTime")
    fields: dict[Name, JsonValue]
    details: PartialSuccess | None = None


class RecordsPage(AirtableModel):
    records: list[Record]
    offset: Cursor | None = None


class BasesQuery(AirtableModel):
    offset: Cursor | None = None


class RecordsQuery(BasesQuery):
    page_size: int = Field(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)
    view: Name | None = None
    formula: str | None = Field(default=None, alias="filterByFormula")


class WriteRecord(AirtableModel):
    fields: dict[Name, JsonValue]
    # Preserve the existing best-effort conversion behavior of both write tools.
    typecast: Literal[True] = True


class BasesResult(AirtableModel):
    bases: list[Base]
    count: int
    next_offset: Cursor | None


class TablesResult(AirtableModel):
    base_id: BaseId
    tables: list[Table]
    count: int


class RecordsResult(AirtableModel):
    base_id: BaseId
    table: Name
    records: list[Record]
    count: int
    filter: str | None
    next_offset: Cursor | None


BASES_RESPONSE = TypeAdapter(BasesPage)
TABLES_RESPONSE = TypeAdapter(TablesPage)
RECORDS_RESPONSE = TypeAdapter(RecordsPage)
RECORD_RESPONSE = TypeAdapter(Record)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        AirtableErrorCode.RESPONSE_INVALID,
        "Airtable returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            AirtableErrorCode.REJECTED, "Airtable rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()
