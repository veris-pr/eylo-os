"""Google Sheets v4 wire contracts for curated tools, not platform entities.

Validate consumed response fields without rejecting vendor additions. Requests
reject unknown fields; scalar cells preserve their JSON types and null skips.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    Strict,
    StringConstraints,
)

MAX_ROWS = 500
DEFAULT_ROW_LIMIT = 100
MAX_ERROR_MESSAGE_CHARS = 500
SPREADSHEET_FIELDS = "properties.title,sheets.properties"


class SheetsToolName(StrEnum):
    LIST_SHEETS = "list_sheets"
    READ_ROWS = "read_rows"
    APPEND_ROW = "append_row"
    UPDATE_CELLS = "update_cells"
    CREATE_SPREADSHEET = "create_spreadsheet"
    ADD_SHEET = "add_sheet"


class SheetsErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    ROW_MISSING = "row_missing"
    HEADERS_MISSING = "headers_missing"
    COLUMN_NOT_FOUND = "column_not_found"
    SHEET_MISSING = "sheet_missing"


class SheetsDimension(StrEnum):
    ROWS = "ROWS"


class SheetsValueInputOption(StrEnum):
    USER_ENTERED = "USER_ENTERED"


class SheetsInsertDataOption(StrEnum):
    INSERT_ROWS = "INSERT_ROWS"


SheetsCell = (
    Annotated[str, Strict()]
    | Annotated[bool, Strict()]
    | Annotated[int, Strict()]
    | Annotated[FiniteFloat, Strict()]
    | None
)
SheetsIdentifier = Annotated[str, StringConstraints(min_length=1)]


class SheetsModel(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class SheetsGridProperties(SheetsModel):
    row_count: int | None = Field(default=None, alias="rowCount", ge=0)
    column_count: int | None = Field(default=None, alias="columnCount", ge=0)


class SheetsProperties(SheetsModel):
    sheet_id: int = Field(alias="sheetId", ge=0)
    title: SheetsIdentifier
    # Object sheets have no grid; absence must not become an invented size.
    grid_properties: SheetsGridProperties | None = Field(
        default=None, alias="gridProperties"
    )


class SheetsSheet(SheetsModel):
    properties: SheetsProperties


class SheetsSpreadsheetProperties(SheetsModel):
    title: str


class SheetsSpreadsheet(SheetsModel):
    properties: SheetsSpreadsheetProperties
    sheets: list[SheetsSheet] = Field(default_factory=list)


class SheetsCreatedSpreadsheet(SheetsSpreadsheet):
    spreadsheet_id: SheetsIdentifier = Field(alias="spreadsheetId")


class SheetsValues(SheetsModel):
    range: str
    # Google omits values for an empty range; malformed rows are not empty data.
    values: list[list[SheetsCell]] = Field(default_factory=list, repr=False)


class SheetsUpdatedValues(SheetsModel):
    spreadsheet_id: SheetsIdentifier = Field(alias="spreadsheetId")
    # No-op writes may omit counters. Preserve unknown rather than invent zero.
    updated_range: str | None = Field(default=None, alias="updatedRange")
    updated_rows: int | None = Field(default=None, alias="updatedRows", ge=0)
    updated_cells: int | None = Field(default=None, alias="updatedCells", ge=0)


class SheetsAppendedValues(SheetsModel):
    spreadsheet_id: SheetsIdentifier = Field(alias="spreadsheetId")
    updates: SheetsUpdatedValues


class SheetsAddSheetReply(SheetsModel):
    add_sheet: SheetsSheet = Field(alias="addSheet")


class SheetsAddedSheet(SheetsModel):
    """This tool sends exactly one addSheet request, which owns one reply."""

    spreadsheet_id: SheetsIdentifier = Field(alias="spreadsheetId")
    replies: list[SheetsAddSheetReply] = Field(min_length=1, max_length=1)


class SheetsError(SheetsModel):
    message: str = Field(repr=False)


class SheetsEnvelope(SheetsModel):
    error: SheetsError | None = Field(default=None, repr=False)


class SheetsRequest(SheetsModel):
    model_config = ConfigDict(extra="forbid")


class SheetsWriteValues(SheetsRequest):
    values: list[list[SheetsCell]] = Field(repr=False)


class SheetsTitle(SheetsRequest):
    title: str


class SheetsNewSheet(SheetsRequest):
    properties: SheetsTitle


class SheetsCreateSpreadsheet(SheetsRequest):
    properties: SheetsTitle
    sheets: list[SheetsNewSheet] | None = None


class SheetsAddSheetRequest(SheetsRequest):
    add_sheet: SheetsNewSheet = Field(alias="addSheet")


class SheetsBatchUpdate(SheetsRequest):
    requests: list[SheetsAddSheetRequest] = Field(min_length=1, max_length=1)


class SheetsReadQuery(SheetsRequest):
    major_dimension: SheetsDimension = Field(alias="majorDimension")


class SheetsUpdateQuery(SheetsRequest):
    value_input_option: SheetsValueInputOption = Field(alias="valueInputOption")


class SheetsAppendQuery(SheetsUpdateQuery):
    insert_data_option: SheetsInsertDataOption = Field(alias="insertDataOption")
    include_values_in_response: bool = Field(alias="includeValuesInResponse")
