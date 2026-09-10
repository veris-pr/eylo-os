"""Version-pinned database query filters, inline property values and pagination."""

import math
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, JsonValue, TypeAdapter, model_validator

from ...contracts import VendorToolError
from .write_contracts import (
    DatabaseParent,
    InputId,
    NativeId,
    NotionModel,
    NotionRequest,
    PropertyKind,
    RichTextRead,
)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_CURSOR_CHARS = 4096


class QueryErrorCode(StrEnum):
    FILTER_INVALID = "filter_invalid"
    FILTER_UNSUPPORTED = "filter_unsupported"
    PROPERTY_NOT_FOUND = "property_not_found"
    IDENTITY_MISMATCH = "vendor_identity_mismatch"
    PAGINATION_INVALID = "vendor_pagination_invalid"


class PropertyExtent(StrEnum):
    INLINE = "inline_values"
    INCOMPLETE = "incomplete"
    REFERENCE_LIMIT = "reference_limit_possible"
    UNSUPPORTED = "unsupported"


NativePropertyKind = Annotated[
    PropertyKind,
    BeforeValidator(
        lambda value: PropertyKind(value) if isinstance(value, str) else value
    ),
]
Cursor = Annotated[str, Field(min_length=1, max_length=MAX_CURSOR_CHARS)]


class QueryInput(NotionRequest):
    database_id: InputId
    property_name: str | None = Field(default=None, min_length=1, max_length=2000)
    equals: str | None = Field(default=None, max_length=2000)
    contains: str | None = Field(default=None, max_length=2000)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    start_cursor: Cursor | None = None

    @model_validator(mode="after")
    def coherent_filter(self) -> Self:
        operators = int(self.equals is not None) + int(self.contains is not None)
        if operators != int(self.property_name is not None):
            raise ValueError(
                "Provide property_name with exactly one of equals or contains."
            )
        return self


class PropertyDefinition(NotionModel):
    id: str = Field(min_length=1)
    type: NativePropertyKind


class DatabaseSchema(NotionModel):
    object: Literal["database"]
    id: NativeId
    properties: dict[str, PropertyDefinition]


class TextCondition(NotionRequest):
    equals: str | None = None
    contains: str | None = None

    @model_validator(mode="after")
    def one_operator(self) -> Self:
        if (self.equals is None) == (self.contains is None):
            raise ValueError("Exactly one text operator is required.")
        return self


class EqualChoice(NotionRequest):
    equals: str


class ContainsChoice(NotionRequest):
    contains: str


class CheckboxCondition(NotionRequest):
    equals: bool


class NumberCondition(NotionRequest):
    equals: float = Field(allow_inf_nan=False)


class PropertyFilter(NotionRequest):
    property: str
    title: TextCondition | None = None
    rich_text: TextCondition | None = None
    url: TextCondition | None = None
    email: TextCondition | None = None
    phone_number: TextCondition | None = None
    select: EqualChoice | None = None
    status: EqualChoice | None = None
    multi_select: ContainsChoice | None = None
    checkbox: CheckboxCondition | None = None
    number: NumberCondition | None = None

    @model_validator(mode="after")
    def one_property_type(self) -> Self:
        populated = self.model_dump(exclude_none=True)
        if len(populated) != 2:
            raise ValueError("A property filter requires exactly one typed condition.")
        return self


def property_filter(
    payload: QueryInput, definition: PropertyDefinition
) -> PropertyFilter:
    """Do not reinterpret operators that the vendor cannot apply to this type."""
    common = {"property": definition.id}
    match definition.type:
        case (
            PropertyKind.TITLE
            | PropertyKind.RICH_TEXT
            | PropertyKind.URL
            | PropertyKind.EMAIL
            | PropertyKind.PHONE_NUMBER
        ):
            condition = TextCondition(equals=payload.equals, contains=payload.contains)
            # The enum selects a declared native field, not an untyped JSON body.
            return PropertyFilter.model_validate({**common, definition.type: condition})
        case PropertyKind.MULTI_SELECT:
            if payload.contains is not None:
                return PropertyFilter(
                    property=definition.id,
                    multi_select=ContainsChoice(contains=payload.contains),
                )
        case PropertyKind.SELECT | PropertyKind.STATUS:
            if payload.equals is not None:
                choice = EqualChoice(equals=payload.equals)
                return PropertyFilter.model_validate(
                    {**common, definition.type: choice}
                )
        case PropertyKind.CHECKBOX:
            if payload.equals is not None:
                value = payload.equals.strip().casefold()
                if value not in {"true", "false"}:
                    raise VendorToolError(
                        QueryErrorCode.FILTER_INVALID,
                        "Checkbox equals must be true or false.",
                    )
                return PropertyFilter(
                    property=definition.id,
                    checkbox=CheckboxCondition(equals=value == "true"),
                )
        case PropertyKind.NUMBER:
            if payload.equals is not None:
                try:
                    number = float(payload.equals)
                except ValueError:
                    number = math.nan
                if not math.isfinite(number):
                    raise VendorToolError(
                        QueryErrorCode.FILTER_INVALID,
                        "Number equals must be finite numeric text.",
                    )
                return PropertyFilter(
                    property=definition.id, number=NumberCondition(equals=number)
                )
    raise VendorToolError(
        QueryErrorCode.FILTER_UNSUPPORTED,
        f"This tool does not support that operator for {definition.type.value} properties.",
    )


class QueryRequest(NotionRequest):
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)
    start_cursor: Cursor | None = None
    filter: PropertyFilter | None = None


class DateValue(NotionModel):
    start: str
    end: str | None
    time_zone: str | None = None


class ChoiceValue(NotionModel):
    id: str
    name: str


class UserValue(NotionModel):
    object: Literal["user"]
    id: NativeId
    name: str | None = None


class RelationValue(NotionModel):
    id: NativeId


class FormulaValue(NotionModel):
    type: Literal["string", "number", "boolean", "date"]
    string: str | None = None
    number: float | None = Field(default=None, allow_inf_nan=False)
    boolean: bool | None = None
    date: DateValue | None = None

    @model_validator(mode="after")
    def present_value(self) -> Self:
        if self.type not in self.model_fields_set:
            raise ValueError(
                "The formula must include its typed value, including null."
            )
        return self


SUPPORTED_VALUES = frozenset(
    {
        PropertyKind.TITLE,
        PropertyKind.RICH_TEXT,
        PropertyKind.NUMBER,
        PropertyKind.SELECT,
        PropertyKind.STATUS,
        PropertyKind.MULTI_SELECT,
        PropertyKind.CHECKBOX,
        PropertyKind.URL,
        PropertyKind.EMAIL,
        PropertyKind.PHONE_NUMBER,
        PropertyKind.DATE,
        PropertyKind.PEOPLE,
        PropertyKind.FORMULA,
        PropertyKind.RELATION,
        PropertyKind.CREATED_TIME,
        PropertyKind.LAST_EDITED_TIME,
        PropertyKind.CREATED_BY,
        PropertyKind.LAST_EDITED_BY,
    }
)


class PropertyValue(NotionModel):
    """Typed inline values; unprojected types are explicitly reported, not invented."""

    id: str = Field(min_length=1)
    type: NativePropertyKind
    title: list[RichTextRead] | None = None
    rich_text: list[RichTextRead] | None = None
    number: float | None = Field(default=None, allow_inf_nan=False)
    select: ChoiceValue | None = None
    status: ChoiceValue | None = None
    multi_select: list[ChoiceValue] | None = None
    checkbox: bool | None = None
    url: str | None = None
    email: str | None = None
    phone_number: str | None = None
    date: DateValue | None = None
    people: list[UserValue] | None = None
    formula: FormulaValue | None = None
    relation: list[RelationValue] | None = None
    has_more: bool | None = None
    created_time: str | None = None
    last_edited_time: str | None = None
    created_by: UserValue | None = None
    last_edited_by: UserValue | None = None

    @model_validator(mode="after")
    def present_value(self) -> Self:
        if self.type in SUPPORTED_VALUES and self.type not in self.model_fields_set:
            raise ValueError(
                "The property must include its typed value, including null."
            )
        required = {
            PropertyKind.TITLE,
            PropertyKind.RICH_TEXT,
            PropertyKind.MULTI_SELECT,
            PropertyKind.CHECKBOX,
            PropertyKind.PEOPLE,
            PropertyKind.FORMULA,
            PropertyKind.RELATION,
            PropertyKind.CREATED_TIME,
            PropertyKind.LAST_EDITED_TIME,
            PropertyKind.CREATED_BY,
            PropertyKind.LAST_EDITED_BY,
        }
        if self.type in required and getattr(self, self.type.value) is None:
            raise ValueError("This property type cannot have a null value.")
        if self.type == PropertyKind.RELATION and self.has_more is None:
            raise ValueError("Relations must indicate whether more references exist.")
        return self

    def projection(self) -> tuple[JsonValue, PropertyExtent]:
        if self.type not in SUPPORTED_VALUES:
            return None, PropertyExtent.UNSUPPORTED
        extent = PropertyExtent.INLINE
        if self.type == PropertyKind.RELATION and self.has_more:
            extent = PropertyExtent.INCOMPLETE
        if self.type in {
            PropertyKind.TITLE,
            PropertyKind.RICH_TEXT,
            PropertyKind.PEOPLE,
            PropertyKind.FORMULA,
        }:
            # Page responses are not the paginated property-item endpoint.
            extent = PropertyExtent.REFERENCE_LIMIT
        match self.type:
            case PropertyKind.TITLE:
                return "".join(run.plain_text for run in self.title or []), extent
            case PropertyKind.RICH_TEXT:
                return "".join(run.plain_text for run in self.rich_text or []), extent
            case PropertyKind.SELECT:
                return self.select.name if self.select is not None else None, extent
            case PropertyKind.STATUS:
                return self.status.name if self.status is not None else None, extent
            case PropertyKind.MULTI_SELECT:
                return [item.name for item in self.multi_select or []], extent
            case PropertyKind.PEOPLE:
                return [
                    item.model_dump(mode="json") for item in self.people or []
                ], extent
            case PropertyKind.DATE:
                return self.date.model_dump(mode="json") if self.date else None, extent
            case PropertyKind.FORMULA:
                return self.formula.model_dump(
                    mode="json", exclude_unset=True
                ) if self.formula else None, extent
            case PropertyKind.RELATION:
                return [item.id for item in self.relation or []], extent
            case _:
                # These are declared scalar/user fields, serialized through the
                # model before the JSON result boundary.
                value = self.model_dump(mode="json")[self.type.value]
                return JSON_VALUE.validate_python(value, strict=True), extent


class QueryRow(NotionModel):
    object: Literal["page"]
    id: NativeId
    url: str
    parent: DatabaseParent
    properties: dict[str, PropertyValue]


class QueryPage(NotionModel):
    object: Literal["list"]
    results: list[QueryRow]
    has_more: bool
    next_cursor: Cursor | None

    @model_validator(mode="after")
    def continuation(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("Pagination flag and cursor disagree.")
        if len({row.id for row in self.results}) != len(self.results):
            raise ValueError("A result page contains duplicate page identities.")
        return self


class RowView(NotionModel):
    page_id: str
    web_link: str
    properties: dict[str, JsonValue]
    property_extents: dict[str, PropertyExtent]


class QueryView(NotionModel):
    database_id: str
    rows: list[RowView]
    count: int
    next_cursor: str | None


DATABASE = TypeAdapter(DatabaseSchema)
QUERY_PAGE = TypeAdapter(QueryPage)
JSON_VALUE = TypeAdapter(JsonValue)
