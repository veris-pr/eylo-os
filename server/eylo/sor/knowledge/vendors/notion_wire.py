"""Consumed Notion 2026-03-11 contracts; source snapshots retain unmapped JSON."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import require_json_value

PAGE_LIMIT = 100
DOCUMENT_PAGE_LIMIT = 25
EMPTY_SCAN_LIMIT = 25
RESPONSE_BODY_LIMIT = 8_388_608
CURSOR_LENGTH_LIMIT = 4_096


class ObjectKind(StrEnum):
    PAGE = "page"
    DATA_SOURCE = "data_source"
    BLOCK = "block"
    USER = "user"
    LIST = "list"
    PAGE_MARKDOWN = "page_markdown"
    COMMENT = "comment"


class ParentType(StrEnum):
    PAGE = "page_id"
    DATA_SOURCE = "data_source_id"
    BLOCK = "block_id"


type SearchObjectKind = Literal[ObjectKind.PAGE, ObjectKind.DATA_SOURCE]


class PropertyType(StrEnum):
    TITLE = "title"
    SELECT = "select"
    STATUS = "status"
    MULTI_SELECT = "multi_select"
    RELATION = "relation"
    ROLLUP = "rollup"
    FILES = "files"


class RichTextType(StrEnum):
    TEXT = "text"
    EQUATION = "equation"


class FileType(StrEnum):
    FILE = "file"
    EXTERNAL = "external"


class RollupType(StrEnum):
    ARRAY = "array"


class BlockType(StrEnum):
    AUDIO = "audio"
    BOOKMARK = "bookmark"
    BREADCRUMB = "breadcrumb"
    BULLETED_LIST_ITEM = "bulleted_list_item"
    CALLOUT = "callout"
    CHILD_DATA_SOURCE = "child_data_source"
    CHILD_PAGE = "child_page"
    CODE = "code"
    COLUMN = "column"
    COLUMN_LIST = "column_list"
    DIVIDER = "divider"
    EMBED = "embed"
    EQUATION = "equation"
    FILE = "file"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    HEADING_4 = "heading_4"
    IMAGE = "image"
    LINK_PREVIEW = "link_preview"
    LINK_TO_PAGE = "link_to_page"
    MEETING_NOTES = "meeting_notes"
    NUMBERED_LIST_ITEM = "numbered_list_item"
    PARAGRAPH = "paragraph"
    PDF = "pdf"
    QUOTE = "quote"
    SYNCED_BLOCK = "synced_block"
    TAB = "tab"
    TABLE = "table"
    TABLE_OF_CONTENTS = "table_of_contents"
    TABLE_ROW = "table_row"
    TEMPLATE = "template"
    TO_DO = "to_do"
    TOGGLE = "toggle"
    VIDEO = "video"


class Response(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class Snapshot(Response):
    """Keep unknown source fields, explicit nulls and omissions unchanged for audit/hash."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def require_json_snapshot(cls, value: object) -> object:
        if isinstance(value, cls):
            return value
        require_json_value(value)
        return value

    def to_snapshot(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_unset=True)


class Reference(Snapshot):
    id: str | None = None


class Parent(Snapshot):
    type: str | None = None
    page_id: str | None = None
    data_source_id: str | None = None
    block_id: str | None = None


class TextContent(Snapshot):
    content: str | None = None
    expression: str | None = None


class RichText(Snapshot):
    plain_text: str | None = None
    type: str | None = None
    text: TextContent | None = None
    equation: TextContent | None = None


class FileLocation(Snapshot):
    url: str | None = None
    expiry_time: str | None = None


class File(Snapshot):
    name: str | None = None
    type: str | None = None
    file: FileLocation | None = None
    external: FileLocation | None = None
    caption: list[RichText] | None = None

    def location(self) -> FileLocation | None:
        if self.type == FileType.FILE:
            return self.file
        if self.type == FileType.EXTERNAL:
            return self.external
        return None


class Rollup(Snapshot):
    type: str | None = None


class Property(Snapshot):
    """Consumed property variants; other vendor/custom values remain source JSON."""

    id: str
    type: str | None = None
    title: list[RichText] | None = None
    select: Reference | None = None
    status: Reference | None = None
    multi_select: list[Reference] | None = None
    has_more: bool | None = None
    rollup: Rollup | None = None
    files: list[File] | None = None


class PropertySchema(Snapshot):
    type: str | None = None


class Record(Snapshot):
    id: str
    created_time: str | None = None
    last_edited_time: str | None = None
    url: str | None = None


class PageIdentity(Record):
    """Page scans only need identity; content is fetched separately."""

    object: Literal[ObjectKind.PAGE] = ObjectKind.PAGE


class Page(PageIdentity):
    properties: dict[str, Property]
    parent: Parent | None = None
    last_edited_by: Reference | None = None
    in_trash: bool | None = None


class DataSource(Record):
    object: Literal[ObjectKind.DATA_SOURCE] = ObjectKind.DATA_SOURCE
    title: list[RichText] | None = None
    properties: dict[str, PropertySchema]


class BlockContent(File):
    """Text/file fields consumed across block kinds, not a full block-writing schema."""

    rich_text: list[RichText] | None = None
    title: str | None = None
    expression: str | None = None
    url: str | None = None
    cells: list[list[RichText]] | None = None


class Block(Record):
    object: Literal[ObjectKind.BLOCK] = ObjectKind.BLOCK
    type: str
    parent: Parent | None = None
    has_children: bool | None = None

    def content(self) -> BlockContent:
        # Notion names this member after its open-ended block discriminator.
        # Preserve the full original block, then validate only consumed content.
        payload = (self.model_extra or {}).get(self.type, {})
        return parse_response(BlockContent, payload)


class Person(Snapshot):
    email: str | None = None


class Bot(Snapshot):
    workspace_id: str | None = None
    workspace_name: str | None = None


class User(Snapshot):
    id: str
    object: Literal[ObjectKind.USER] = ObjectKind.USER
    name: str | None = None
    type: str | None = None
    avatar_url: str | None = None
    person: Person | None = None
    bot: Bot | None = None


class Markdown(Snapshot):
    object: Literal[ObjectKind.PAGE_MARKDOWN]
    id: str
    markdown: str
    truncated: bool
    unknown_block_ids: list[str]


class Pagination(Response):
    has_more: bool
    next_cursor: str | None = None


class SearchResult(Snapshot):
    object: Literal[ObjectKind.PAGE, ObjectKind.DATA_SOURCE]


class ListResponse[T](Pagination):
    results: list[T]


class PropertyResult(Snapshot):
    object: str


class PropertyItems(PropertyResult, Pagination):
    results: list[Snapshot]


class PageResult(Response):
    """Create acknowledgement consumes identity, revision and source link only."""

    id: str
    last_edited_time: str | None = None
    url: str | None = None


class CommentResult(Response):
    id: str


class Request(Response):
    model_config = ConfigDict(extra="forbid")

    def to_wire(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class ListQuery(Request):
    page_size: int = Field(ge=1, le=PAGE_LIMIT)
    start_cursor: str | None = None


class SearchProperty(StrEnum):
    OBJECT = "object"


class SortDirection(StrEnum):
    ASCENDING = "ascending"


class SortTimestamp(StrEnum):
    LAST_EDITED_TIME = "last_edited_time"


class SearchFilter(Request):
    property: Literal[SearchProperty.OBJECT] = SearchProperty.OBJECT
    value: SearchObjectKind


class SearchSort(Request):
    direction: Literal[SortDirection.ASCENDING] = SortDirection.ASCENDING
    timestamp: Literal[SortTimestamp.LAST_EDITED_TIME] = SortTimestamp.LAST_EDITED_TIME


class SearchRequest(ListQuery):
    filter: SearchFilter
    sort: SearchSort = Field(default_factory=SearchSort)


class MarkdownQuery(Request):
    include_transcript: bool = False


class PageParent(Request):
    type: Literal[ParentType.PAGE] = ParentType.PAGE
    page_id: str


class DataSourceParent(Request):
    type: Literal[ParentType.DATA_SOURCE] = ParentType.DATA_SOURCE
    data_source_id: str


class WriteText(Request):
    content: str


class WriteRichText(Request):
    type: Literal[RichTextType.TEXT] = RichTextType.TEXT
    text: WriteText


class WriteTitle(Request):
    type: Literal[PropertyType.TITLE] = PropertyType.TITLE
    title: list[WriteRichText]


class UpdateTitle(Request):
    properties: dict[str, WriteTitle]


class CreatePage(UpdateTitle):
    parent: PageParent | DataSourceParent
    markdown: str | None = None


class MarkdownOperation(StrEnum):
    REPLACE_CONTENT = "replace_content"
    INSERT_CONTENT = "insert_content"


class PositionType(StrEnum):
    END = "end"


class EndPosition(Request):
    type: Literal[PositionType.END] = PositionType.END


class Replacement(Request):
    new_str: str


class ReplaceMarkdown(Request):
    type: Literal[MarkdownOperation.REPLACE_CONTENT] = MarkdownOperation.REPLACE_CONTENT
    replace_content: Replacement


class Insertion(Request):
    content: str
    position: EndPosition = Field(default_factory=EndPosition)


class InsertMarkdown(Request):
    type: Literal[MarkdownOperation.INSERT_CONTENT] = MarkdownOperation.INSERT_CONTENT
    insert_content: Insertion


class CommentParent(Request):
    page_id: str


class CreateComment(Request):
    parent: CommentParent
    markdown: str


def parse_response[T: Response](model: type[T], value: object) -> T:
    """Never expose vendor content through validation diagnostics."""
    try:
        return model.model_validate(value)
    except (ValidationError, ValueError) as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Notion returned invalid operation data.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
