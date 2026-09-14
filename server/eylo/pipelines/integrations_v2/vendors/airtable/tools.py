"""Curated Airtable operations with native validation and bounded page continuation."""

import re
from typing import Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    BASES_RESPONSE,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    RECORDS_RESPONSE,
    RECORD_RESPONSE,
    TABLES_RESPONSE,
    AirtableErrorCode,
    BaseId,
    BasesQuery,
    BasesResult,
    Cursor,
    Name,
    RecordId,
    RecordsQuery,
    RecordsResult,
    Table,
    TablesResult,
    WriteRecord,
    invalid_response,
    parse_response,
)

_TABLE_ID = re.compile(r"^tbl[A-Za-z0-9]+$")


class AirtableInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, hide_input_in_errors=True
    )


class ListBasesInput(AirtableInput):
    offset: Cursor | None = Field(
        default=None, description="Use next_offset to continue."
    )


class ListTablesInput(AirtableInput):
    base_id: BaseId = Field(description="Base ID from list_bases.")


class TableInput(ListTablesInput):
    table: Name = Field(
        description="Exact table name or ID. Prefer the ID from list_tables."
    )


class ListRecordsInput(TableInput):
    where_field: Name | None = Field(
        default=None, description="Field name or ID to filter on."
    )
    equals: str | None = Field(default=None, description="Value it must equal.")
    contains: str | None = Field(
        default=None, description="Case-insensitive text it must contain."
    )
    view: Name | None = Field(
        default=None, description="Restrict to a view name or ID."
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: Cursor | None = Field(
        default=None, description="Use next_offset with the same filter/view."
    )

    @model_validator(mode="after")
    def validate_filter(self) -> Self:
        values = (self.equals is not None) + (self.contains is not None)
        if (self.where_field is None and values) or (
            self.where_field is not None and values != 1
        ):
            raise ValueError(
                "A filter requires where_field and exactly one of equals or contains."
            )
        return self


class CreateRecordInput(TableInput):
    fields: dict[Name, JsonValue] = Field(
        description="Cell values keyed by exact field name or ID."
    )


class UpdateRecordInput(CreateRecordInput):
    record_id: RecordId = Field(
        description="Record ID from list_records; never a custom field named id."
    )


@curated_tool(
    vendor=vendor.vendor,
    name="list_bases",
    display_name="List Airtable Bases",
    description=(
        "List one page of bases this token can reach, with IDs, names and permissions. "
        "Pass next_offset back as offset to continue. Other tools need the base ID."
    ),
    input_model=ListBasesInput,
    effect=ToolEffect.READ,
)
async def list_bases(
    payload: ListBasesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = BasesQuery(offset=payload.offset)
    page = parse_response(
        await ctx.read("/meta/bases", query=query.model_dump(exclude_none=True)),
        BASES_RESPONSE,
    )
    _page_identity([base.id for base in page.bases], page.offset, payload.offset)
    return BasesResult(
        bases=page.bases, count=len(page.bases), next_offset=page.offset
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_tables",
    display_name="List Airtable Tables",
    description=(
        "List a base's tables with field IDs, names and types, plus view IDs and names. "
        "Use these exact identifiers to filter or write. Requires schema.bases:read on the token."
    ),
    input_model=ListTablesInput,
    effect=ToolEffect.READ,
)
async def list_tables(
    payload: ListTablesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    tables = await _tables(payload.base_id, ctx)
    return TablesResult(
        base_id=payload.base_id, tables=tables, count=len(tables)
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_records",
    display_name="List Airtable Records",
    description=(
        "Read one page of records, optionally filtered by one field and exactly one of "
        "equals or contains. Pass next_offset as offset, keeping the filter/view unchanged, "
        "to continue. Each record keeps its stable id beside a fields object containing "
        "the user-defined cell values. Prefer table and field IDs from list_tables."
    ),
    input_model=ListRecordsInput,
    effect=ToolEffect.READ,
)
async def list_records(
    payload: ListRecordsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    field = payload.where_field
    tables = None
    if _needs_table_lookup(payload.table) or (
        field is not None and any(c in field for c in "\\{}")
    ):
        tables = await _tables(payload.base_id, ctx)
    table_path = _table_path(payload.table, tables)
    if field is not None and any(c in field for c in "\\{}"):
        table = _find_table(payload.table, tables or [])
        candidates = [
            item for item in table.fields if item.name == field or item.id == field
        ]
        if len(candidates) != 1:
            code = (
                AirtableErrorCode.FIELD_NOT_FOUND
                if not candidates
                else AirtableErrorCode.FIELD_AMBIGUOUS
            )
            raise VendorToolError(code, "Use an exact field ID from list_tables.")
        field = candidates[0].id
    formula = (
        _formula(field, equals=payload.equals, contains=payload.contains)
        if field is not None
        else None
    )
    query = RecordsQuery(
        page_size=payload.limit,
        offset=payload.offset,
        view=payload.view,
        formula=formula,
    )
    page = parse_response(
        await ctx.read(
            f"/{payload.base_id}/{table_path}",
            query=query.model_dump(by_alias=True, exclude_none=True),
        ),
        RECORDS_RESPONSE,
    )
    _page_identity([record.id for record in page.records], page.offset, payload.offset)
    if len(page.records) > payload.limit:
        invalid_response()
    return RecordsResult(
        base_id=payload.base_id,
        table=payload.table,
        records=page.records,
        count=len(page.records),
        filter=formula,
        next_offset=page.offset,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_record",
    display_name="Create Airtable Record",
    description=(
        "Add one record using cell values keyed by exact field name or ID. "
        "Airtable's best-effort type conversion is enabled. The result keeps record "
        "identity separate from fields; details reports partial attachment upload outcomes. "
        "Use table IDs from list_tables, especially for names with path separators."
    ),
    input_model=CreateRecordInput,
    effect=ToolEffect.MUTATION,
)
async def create_record(
    payload: CreateRecordInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    path = await _write_path(payload, ctx)
    request = WriteRecord(fields=payload.fields)
    record = parse_response(
        await ctx.mutate(path, json=request.model_dump(mode="json")), RECORD_RESPONSE
    )
    return record.model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="update_record",
    display_name="Update Airtable Record",
    description=(
        "Change only the supplied fields of the specified record. Other fields remain "
        "unchanged. Airtable's best-effort type conversion is enabled. The returned "
        "record must match record_id; details reports partial attachment upload outcomes."
    ),
    input_model=UpdateRecordInput,
    effect=ToolEffect.MUTATION,
)
async def update_record(
    payload: UpdateRecordInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if not payload.fields:
        raise VendorToolError(
            AirtableErrorCode.NO_CHANGE, "Give at least one field to change."
        )
    path = await _write_path(payload, ctx)
    request = WriteRecord(fields=payload.fields)
    record = parse_response(
        await ctx.mutate(
            f"{path}/{payload.record_id}",
            method="PATCH",
            json=request.model_dump(mode="json"),
        ),
        RECORD_RESPONSE,
    )
    if record.id != payload.record_id:
        invalid_response()
    return record.model_dump(mode="json")


async def _tables(base_id: str, ctx: VendorToolContext) -> list[Table]:
    page = parse_response(
        await ctx.read(f"/meta/bases/{base_id}/tables"), TABLES_RESPONSE
    )
    _page_identity([table.id for table in page.tables], None, None)
    for table in page.tables:
        _page_identity([field.id for field in table.fields], None, None)
        _page_identity([view.id for view in table.views], None, None)
    return page.tables


def _page_identity(
    ids: list[str], next_offset: str | None, previous: str | None
) -> None:
    if len(set(ids)) != len(ids) or (
        next_offset is not None and (next_offset == previous or not ids)
    ):
        invalid_response()


def _needs_table_lookup(name: str) -> bool:
    return "/" in name or "\\" in name or name in {".", ".."}


def _find_table(name: str, tables: list[Table]) -> Table:
    matches = (
        [table for table in tables if table.id == name]
        if _TABLE_ID.fullmatch(name)
        else [table for table in tables if table.name == name]
    )
    if len(matches) != 1:
        code = (
            AirtableErrorCode.TABLE_NOT_FOUND
            if not matches
            else AirtableErrorCode.TABLE_AMBIGUOUS
        )
        raise VendorToolError(code, "Use an exact table ID from list_tables.")
    return matches[0]


def _table_path(name: str, tables: list[Table] | None) -> str:
    # Do not relax the shared encoded-separator policy to accommodate a vendor name.
    if _needs_table_lookup(name):
        return _find_table(name, tables or []).id
    return quote(name, safe="")


async def _write_path(payload: TableInput, ctx: VendorToolContext) -> str:
    tables = (
        await _tables(payload.base_id, ctx)
        if _needs_table_lookup(payload.table)
        else None
    )
    return f"/{payload.base_id}/{_table_path(payload.table, tables)}"


def _formula(field: str, *, equals: str | None, contains: str | None) -> str:
    if equals is not None:
        return f'{{{field}}}="{_quote(equals)}"'
    if contains is None:
        raise ValueError("A filter requires equals or contains.")
    return f'FIND(LOWER("{_quote(contains)}"), LOWER({{{field}}}))'


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


__all__ = [
    "create_record",
    "list_bases",
    "list_records",
    "list_tables",
    "update_record",
]
