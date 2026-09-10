"""Curated Google Sheets tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, JsonValue

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .client import parse_response
from .definition import SPREADSHEETS, vendor
from .schemas import (
    DEFAULT_ROW_LIMIT,
    MAX_ROWS,
    SPREADSHEET_FIELDS,
    SheetsAddSheetRequest,
    SheetsAddedSheet,
    SheetsAppendQuery,
    SheetsAppendedValues,
    SheetsBatchUpdate,
    SheetsCell,
    SheetsCreateSpreadsheet,
    SheetsCreatedSpreadsheet,
    SheetsDimension,
    SheetsErrorCode,
    SheetsInsertDataOption,
    SheetsNewSheet,
    SheetsReadQuery,
    SheetsSpreadsheet,
    SheetsTitle,
    SheetsToolName,
    SheetsUpdateQuery,
    SheetsUpdatedValues,
    SheetsValueInputOption,
    SheetsValues,
    SheetsWriteValues,
)


class ListSheetsInput(BaseModel):
    spreadsheet_id: str = Field(
        min_length=1, description="Spreadsheet id — the long identifier in its URL."
    )


class ReadRowsInput(BaseModel):
    spreadsheet_id: str = Field(min_length=1)
    range: str = Field(
        default="",
        description=(
            "Sheet name, or A1 range such as 'Orders!A1:F50'. Omit to read the "
            "first sheet."
        ),
    )
    as_records: bool = Field(
        default=True,
        description=(
            "Treat the first row as column headers and return each later row "
            "keyed by them. Turn off to get raw positional cells."
        ),
    )
    limit: int = Field(default=DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROWS)


class AppendRowInput(BaseModel):
    spreadsheet_id: str = Field(min_length=1)
    sheet: str = Field(default="", description="Sheet name. Defaults to the first.")
    record: dict[str, SheetsCell] | None = Field(
        default=None,
        description=(
            "Values keyed by column header, e.g. {'Name': 'Ana', 'Status': "
            "'Open'}. Missing columns are left blank."
        ),
    )
    values: list[SheetsCell] | None = Field(
        default=None,
        description="Positional cell values, used instead of record when given.",
    )


class UpdateCellsInput(BaseModel):
    spreadsheet_id: str = Field(min_length=1)
    range: str = Field(min_length=1, description="A1 range such as 'Orders!B2:C3'.")
    rows: list[list[SheetsCell]] = Field(
        min_length=1, description="Rows of cell values, matching the range's shape."
    )


class CreateSpreadsheetInput(BaseModel):
    title: str = Field(min_length=1)
    sheet_names: list[str] | None = Field(
        default=None, description="Names for the initial sheets."
    )
    headers: list[str] | None = Field(
        default=None, description="Header row written into the first sheet."
    )


class AddSheetInput(BaseModel):
    spreadsheet_id: str = Field(min_length=1)
    title: str = Field(min_length=1, description="Name for the new sheet.")


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.LIST_SHEETS,
    display_name="List Sheets in a Spreadsheet",
    description=(
        "List the sheets (tabs) inside a spreadsheet with their names and "
        "sizes. Other tools accept a sheet name directly, so this is only "
        "needed to discover what exists."
    ),
    input_model=ListSheetsInput,
    effect=ToolEffect.READ,
    scopes=(SPREADSHEETS,),
)
async def list_sheets(
    payload: ListSheetsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    info = await _spreadsheet(ctx, payload.spreadsheet_id)
    sheets = info.sheets
    return {
        "spreadsheet_id": payload.spreadsheet_id,
        "title": info.properties.title,
        "sheets": [
            {
                "name": sheet.properties.title,
                "sheet_id": sheet.properties.sheet_id,
                "rows": sheet.properties.grid_properties.row_count
                if sheet.properties.grid_properties
                else None,
                "columns": sheet.properties.grid_properties.column_count
                if sheet.properties.grid_properties
                else None,
            }
            for sheet in sheets
        ],
        "count": len(sheets),
    }


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.READ_ROWS,
    display_name="Read Spreadsheet Rows",
    description=(
        "Read rows from a sheet. By default the first row is treated as column "
        "headers and every later row comes back keyed by them, so values are "
        "addressed by name instead of by position. Give a sheet name alone to "
        "read all of it, or an A1 range to read part."
    ),
    input_model=ReadRowsInput,
    effect=ToolEffect.READ,
    scopes=(SPREADSHEETS,),
)
async def read_rows(
    payload: ReadRowsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    target = payload.range.strip() or await _first_sheet_name(
        ctx, payload.spreadsheet_id
    )
    response = await ctx.read(
        f"/spreadsheets/{payload.spreadsheet_id}/values/{_quote(target)}",
        query=SheetsReadQuery(majorDimension=SheetsDimension.ROWS).model_dump(
            mode="json", by_alias=True
        ),
    )
    grid = parse_response(response, SheetsValues).values
    if not payload.as_records:
        limited = grid[: payload.limit]
        return {"range": target, "rows": limited, "count": len(limited)}

    if not grid:
        return {"range": target, "headers": [], "records": [], "count": 0}
    headers = [str(cell) for cell in grid[0]]
    body = grid[1 : payload.limit + 1]
    records: list[JsonValue] = [
        {
            header: (row[index] if index < len(row) else None)
            for index, header in enumerate(headers)
        }
        for row in body
    ]
    return {
        "range": target,
        "headers": headers,
        "records": records,
        "count": len(records),
        "more_rows_exist": len(grid) - 1 > len(records),
    }


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.APPEND_ROW,
    display_name="Append Spreadsheet Row",
    description=(
        "Add a row to the bottom of a sheet. Give the values keyed by column "
        "header and each one lands in the right column — the header row is "
        "read first, so column order never has to be known. Positional values "
        "may be given instead."
    ),
    input_model=AppendRowInput,
    effect=ToolEffect.MUTATION,
    scopes=(SPREADSHEETS,),
)
async def append_row(
    payload: AppendRowInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.record is None and payload.values is None:
        raise VendorToolError(
            SheetsErrorCode.ROW_MISSING,
            "Give either a record keyed by header, or positional values.",
        )
    sheet = payload.sheet.strip() or await _first_sheet_name(
        ctx, payload.spreadsheet_id
    )

    if payload.values is not None:
        row: list[SheetsCell] = list(payload.values)
        headers: list[str] = []
    elif payload.record is not None:
        headers = await _headers(ctx, payload.spreadsheet_id, sheet)
        if not headers:
            raise VendorToolError(
                SheetsErrorCode.HEADERS_MISSING,
                f"Sheet '{sheet}' has no header row, so a record cannot be placed. "
                "Give positional values instead.",
            )
        wanted = {key.casefold(): value for key, value in payload.record.items()}
        row = [wanted.get(header.casefold()) for header in headers]
        unknown = [
            key
            for key in payload.record
            if key.casefold() not in {header.casefold() for header in headers}
        ]
        if unknown:
            raise VendorToolError(
                SheetsErrorCode.COLUMN_NOT_FOUND,
                f"No column named {', '.join(sorted(unknown))}. "
                f"Columns are: {', '.join(headers)}.",
            )
    else:
        raise VendorToolError(SheetsErrorCode.ROW_MISSING, "No row was supplied.")

    response = await ctx.mutate(
        f"/spreadsheets/{payload.spreadsheet_id}/values/{_quote(sheet)}:append",
        json=SheetsWriteValues(values=[row]).model_dump(mode="json"),
        query=SheetsAppendQuery(
            valueInputOption=SheetsValueInputOption.USER_ENTERED,
            insertDataOption=SheetsInsertDataOption.INSERT_ROWS,
            includeValuesInResponse=True,
        ).model_dump(mode="json", by_alias=True),
    )
    result = parse_response(response, SheetsAppendedValues)
    _check_spreadsheet(result.spreadsheet_id, payload.spreadsheet_id)
    _check_spreadsheet(result.updates.spreadsheet_id, payload.spreadsheet_id)
    updates = result.updates
    return {
        "spreadsheet_id": payload.spreadsheet_id,
        "sheet": sheet,
        "updated_range": updates.updated_range,
        "cells_written": updates.updated_cells,
        "headers": headers,
    }


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.UPDATE_CELLS,
    display_name="Update Spreadsheet Cells",
    description=(
        "Overwrite a rectangular range with new values. The rows given must "
        "match the range's shape. Values are interpreted as if typed by a "
        "person, so numbers become numbers and text starting with = becomes a "
        "formula."
    ),
    input_model=UpdateCellsInput,
    effect=ToolEffect.MUTATION,
    scopes=(SPREADSHEETS,),
)
async def update_cells(
    payload: UpdateCellsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.mutate(
        f"/spreadsheets/{payload.spreadsheet_id}/values/{_quote(payload.range)}",
        method="PUT",
        json=SheetsWriteValues(values=payload.rows).model_dump(mode="json"),
        query=SheetsUpdateQuery(
            valueInputOption=SheetsValueInputOption.USER_ENTERED
        ).model_dump(mode="json", by_alias=True),
    )
    result = parse_response(response, SheetsUpdatedValues)
    _check_spreadsheet(result.spreadsheet_id, payload.spreadsheet_id)
    return {
        "spreadsheet_id": payload.spreadsheet_id,
        "updated_range": result.updated_range,
        "rows_written": result.updated_rows,
        "cells_written": result.updated_cells,
    }


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.CREATE_SPREADSHEET,
    display_name="Create Spreadsheet",
    description=(
        "Create a spreadsheet, optionally naming its sheets and writing a "
        "header row into the first one so it is immediately usable with "
        "append_row. Returns the id and its editing link."
    ),
    input_model=CreateSpreadsheetInput,
    effect=ToolEffect.MUTATION,
    scopes=(SPREADSHEETS,),
)
async def create_spreadsheet(
    payload: CreateSpreadsheetInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    body = SheetsCreateSpreadsheet(
        properties=SheetsTitle(title=payload.title),
        sheets=[
            SheetsNewSheet(properties=SheetsTitle(title=name))
            for name in payload.sheet_names
        ]
        if payload.sheet_names
        else None,
    )
    created = parse_response(
        await ctx.mutate(
            "/spreadsheets", json=body.model_dump(mode="json", exclude_none=True)
        ),
        SheetsCreatedSpreadsheet,
    )
    spreadsheet_id = created.spreadsheet_id
    sheets = created.sheets
    if payload.headers:
        if not sheets:
            raise VendorToolError(
                SheetsErrorCode.SHEET_MISSING,
                "Google created the spreadsheet without a sheet for the headers.",
            )
        first_name = sheets[0].properties.title
        response = await ctx.mutate(
            f"/spreadsheets/{spreadsheet_id}/values/{_quote(first_name)}!A1",
            method="PUT",
            json=SheetsWriteValues(values=[list(payload.headers)]).model_dump(
                mode="json"
            ),
            query=SheetsUpdateQuery(
                valueInputOption=SheetsValueInputOption.USER_ENTERED
            ).model_dump(mode="json", by_alias=True),
        )
        updated = parse_response(response, SheetsUpdatedValues)
        _check_spreadsheet(updated.spreadsheet_id, spreadsheet_id)
    return {
        "spreadsheet_id": spreadsheet_id,
        "title": created.properties.title,
        "sheets": [sheet.properties.title for sheet in sheets],
        "web_link": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
        "headers_written": bool(payload.headers),
    }


@curated_tool(
    vendor=vendor.vendor,
    name=SheetsToolName.ADD_SHEET,
    display_name="Add Sheet to Spreadsheet",
    description="Add a new sheet (tab) to an existing spreadsheet.",
    input_model=AddSheetInput,
    effect=ToolEffect.MUTATION,
    scopes=(SPREADSHEETS,),
)
async def add_sheet(
    payload: AddSheetInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    response = await ctx.mutate(
        f"/spreadsheets/{payload.spreadsheet_id}:batchUpdate",
        json=SheetsBatchUpdate(
            requests=[
                SheetsAddSheetRequest(
                    addSheet=SheetsNewSheet(properties=SheetsTitle(title=payload.title))
                )
            ]
        ).model_dump(mode="json", by_alias=True),
    )
    result = parse_response(response, SheetsAddedSheet)
    _check_spreadsheet(result.spreadsheet_id, payload.spreadsheet_id)
    properties = result.replies[0].add_sheet.properties
    return {
        "spreadsheet_id": payload.spreadsheet_id,
        "sheet": properties.title,
        "sheet_id": properties.sheet_id,
    }


async def _spreadsheet(
    ctx: VendorToolContext, spreadsheet_id: str
) -> SheetsSpreadsheet:
    response = await ctx.read(
        f"/spreadsheets/{spreadsheet_id}",
        query={"fields": SPREADSHEET_FIELDS},
    )
    return parse_response(response, SheetsSpreadsheet)


async def _first_sheet_name(ctx: VendorToolContext, spreadsheet_id: str) -> str:
    sheets = (await _spreadsheet(ctx, spreadsheet_id)).sheets
    if not sheets:
        raise VendorToolError(
            SheetsErrorCode.SHEET_MISSING, "This spreadsheet has no sheets."
        )
    return sheets[0].properties.title


async def _headers(
    ctx: VendorToolContext, spreadsheet_id: str, sheet: str
) -> list[str]:
    """The sheet's first row, which is what makes records addressable by name."""
    response = await ctx.read(
        f"/spreadsheets/{spreadsheet_id}/values/{_quote(sheet)}!1:1"
    )
    rows = parse_response(response, SheetsValues).values
    return [str(cell) for cell in rows[0]] if rows else []


def _quote(value: str) -> str:
    """A1 ranges travel in the path, so a sheet name with a space must encode."""
    return (
        value.replace("%", "%25")
        .replace(" ", "%20")
        .replace("#", "%23")
        .replace("?", "%3F")
    )


def _check_spreadsheet(actual: str, expected: str) -> None:
    """A receipt for another spreadsheet cannot prove this tool's write."""
    if actual != expected:
        raise VendorToolError(
            SheetsErrorCode.RESPONSE_INVALID,
            "Google returned a result for a different spreadsheet.",
        )


__all__ = [
    "add_sheet",
    "append_row",
    "create_spreadsheet",
    "list_sheets",
    "read_rows",
    "update_cells",
]
