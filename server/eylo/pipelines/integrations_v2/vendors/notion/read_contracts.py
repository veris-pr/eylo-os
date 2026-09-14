"""Notion search/page metadata and bounded, explicit block-tree projections."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BeforeValidator, Field, TypeAdapter, model_validator

from .query_contracts import Cursor
from .write_contracts import (
    BlockOwner,
    InputId,
    NativeId,
    NotionModel,
    NotionRequest,
    PropertyKind,
    RichTextRead,
    TitleRead,
)

MAX_TEXT_CHARS = 20_000
MAX_BLOCK_PAGE_SIZE = 100
MAX_TREE_REQUESTS = 20
MAX_TREE_DEPTH = 3
MAX_ANCESTOR_REQUESTS = 32
DEFAULT_SEARCH_SIZE = 20
MAX_SEARCH_SIZE = 50


class SearchKind(StrEnum):
    PAGE = "page"
    DATABASE = "database"


class ReadState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class OmissionReason(StrEnum):
    REQUEST_LIMIT = "request_limit"
    DEPTH_LIMIT = "depth_limit"
    UNSUPPORTED = "unsupported_block"
    METADATA_UNAVAILABLE = "metadata_unavailable"


class ReadErrorCode(StrEnum):
    TARGET_INVALID = "read_target_invalid"
    CYCLE = "vendor_tree_cycle"


class SearchInput(NotionRequest):
    query: str | None = Field(default=None, max_length=2000)
    only: (
        Annotated[
            SearchKind,
            BeforeValidator(
                lambda value: SearchKind(value.strip().casefold())
                if isinstance(value, str)
                else value
            ),
        ]
        | None
    ) = None
    limit: int = Field(default=DEFAULT_SEARCH_SIZE, ge=1, le=MAX_SEARCH_SIZE)
    start_cursor: Cursor | None = None


class SearchFilter(NotionRequest):
    property: Literal["object"] = "object"
    value: SearchKind


class SearchRequest(NotionRequest):
    query: str | None = None
    filter: SearchFilter | None = None
    page_size: int = Field(ge=1, le=MAX_SEARCH_SIZE)
    start_cursor: Cursor | None = None


class Metadata(NotionModel):
    object: Literal["page", "database"]
    id: NativeId
    properties: dict[str, TitleRead] | None = None
    title: list[RichTextRead] | None = None
    url: str | None = None
    last_edited_time: str | None = None

    @model_validator(mode="after")
    def coherent_title(self) -> Self:
        if "properties" in self.model_fields_set and self.properties is None:
            raise ValueError("Properties cannot be null.")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("Title cannot be null.")
        if self.object == SearchKind.PAGE and self.properties is not None:
            if (
                sum(
                    value.type == PropertyKind.TITLE
                    for value in self.properties.values()
                )
                != 1
            ):
                raise ValueError("Page metadata requires exactly one title property.")
        return self

    def title_text(self) -> str | None:
        runs = self.title
        if self.object == SearchKind.PAGE:
            runs = None
            if self.properties is not None:
                runs = next(
                    value.title
                    for value in self.properties.values()
                    if value.type == PropertyKind.TITLE
                )
        return "".join(run.plain_text for run in runs) if runs is not None else None


class CursorPage[T](NotionModel):
    object: Literal["list"]
    results: list[T]
    has_more: bool
    next_cursor: Cursor | None

    @model_validator(mode="after")
    def continuation(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("Pagination flag and cursor disagree.")
        return self


class SearchEntry(NotionModel):
    id: str
    object: SearchKind
    title: str | None
    web_link: str | None
    last_edited: str | None
    metadata_state: ReadState


class SearchView(NotionModel):
    results: list[SearchEntry]
    count: int
    next_cursor: str | None


class ReadPageInput(NotionRequest):
    page_id: InputId
    block_id: InputId | None = Field(
        default=None,
        description="Read children of this descendant block; omission reads the page root.",
    )
    start_cursor: Cursor | None = None
    text_offset: int = Field(default=0, ge=0)


class ChildrenQuery(NotionRequest):
    page_size: int = MAX_BLOCK_PAGE_SIZE
    start_cursor: Cursor | None = None


class BlockKind(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    BULLETED_LIST_ITEM = "bulleted_list_item"
    NUMBERED_LIST_ITEM = "numbered_list_item"
    QUOTE = "quote"
    CALLOUT = "callout"
    TOGGLE = "toggle"
    CODE = "code"
    TO_DO = "to_do"
    TEMPLATE = "template"
    SYNCED_BLOCK = "synced_block"
    CHILD_PAGE = "child_page"
    CHILD_DATABASE = "child_database"
    EQUATION = "equation"
    DIVIDER = "divider"
    BREADCRUMB = "breadcrumb"
    TABLE_OF_CONTENTS = "table_of_contents"
    COLUMN_LIST = "column_list"
    COLUMN = "column"
    LINK_TO_PAGE = "link_to_page"
    TABLE = "table"
    TABLE_ROW = "table_row"
    EMBED = "embed"
    BOOKMARK = "bookmark"
    IMAGE = "image"
    VIDEO = "video"
    PDF = "pdf"
    FILE = "file"
    AUDIO = "audio"
    LINK_PREVIEW = "link_preview"
    UNSUPPORTED = "unsupported"


class TextBlock(NotionModel):
    rich_text: list[RichTextRead]


class TodoBlock(TextBlock):
    checked: bool


class CodeBlock(TextBlock):
    language: str


class NamedChild(NotionModel):
    title: str


class TableRow(NotionModel):
    cells: list[list[RichTextRead]]


class EquationBlock(NotionModel):
    expression: str


class SyncedFrom(NotionModel):
    block_id: NativeId


class SyncedContent(NotionModel):
    synced_from: SyncedFrom | None


BLOCK_PREFIX = {
    BlockKind.PARAGRAPH: "",
    BlockKind.HEADING_1: "# ",
    BlockKind.HEADING_2: "## ",
    BlockKind.HEADING_3: "### ",
    BlockKind.BULLETED_LIST_ITEM: "- ",
    BlockKind.NUMBERED_LIST_ITEM: "1. ",
    BlockKind.QUOTE: "> ",
    BlockKind.CALLOUT: "> ",
    BlockKind.TOGGLE: "",
    BlockKind.TEMPLATE: "",
}
STRUCTURAL_BLOCKS = frozenset(
    {
        BlockKind.SYNCED_BLOCK,
        BlockKind.COLUMN,
        BlockKind.COLUMN_LIST,
        BlockKind.TABLE,
        BlockKind.TABLE_OF_CONTENTS,
        BlockKind.BREADCRUMB,
    }
)
TEXT_BLOCKS = frozenset(BLOCK_PREFIX) | {BlockKind.CODE, BlockKind.TO_DO}


class Block(NotionModel):
    object: Literal["block"]
    id: NativeId
    type: (
        Annotated[
            BlockKind,
            BeforeValidator(
                lambda value: BlockKind(value) if isinstance(value, str) else value
            ),
        ]
        | None
    ) = None
    parent: BlockOwner | None = None
    has_children: bool | None = None
    paragraph: TextBlock | None = None
    heading_1: TextBlock | None = None
    heading_2: TextBlock | None = None
    heading_3: TextBlock | None = None
    bulleted_list_item: TextBlock | None = None
    numbered_list_item: TextBlock | None = None
    quote: TextBlock | None = None
    callout: TextBlock | None = None
    toggle: TextBlock | None = None
    template: TextBlock | None = None
    code: CodeBlock | None = None
    to_do: TodoBlock | None = None
    child_page: NamedChild | None = None
    child_database: NamedChild | None = None
    table_row: TableRow | None = None
    equation: EquationBlock | None = None
    synced_block: SyncedContent | None = None

    @model_validator(mode="after")
    def full_or_partial(self) -> Self:
        if self.type is None:
            if self.model_fields_set - {"object", "id"}:
                raise ValueError("A partial block contains only its identity.")
            return self
        if self.has_children is None or self.parent is None:
            raise ValueError("A full block requires parent and has_children.")
        rendered = TEXT_BLOCKS | {
            BlockKind.CHILD_PAGE,
            BlockKind.CHILD_DATABASE,
            BlockKind.TABLE_ROW,
            BlockKind.EQUATION,
            BlockKind.SYNCED_BLOCK,
        }
        if self.type in rendered and getattr(self, self.type.value) is None:
            raise ValueError("A rendered block must include its typed content.")
        return self

    def text(self) -> str | None:
        if self.type is None:
            return None
        if self.type in BLOCK_PREFIX:
            content: TextBlock = getattr(self, self.type.value)
            return BLOCK_PREFIX[self.type] + "".join(
                run.plain_text for run in content.rich_text
            )
        if self.to_do is not None and self.type == BlockKind.TO_DO:
            return ("- [x] " if self.to_do.checked else "- [ ] ") + "".join(
                run.plain_text for run in self.to_do.rich_text
            )
        if self.code is not None and self.type == BlockKind.CODE:
            # Indented Markdown cannot be closed by fences embedded in vendor text.
            return "\n".join(
                "    " + line
                for line in "".join(
                    run.plain_text for run in self.code.rich_text
                ).split("\n")
            )
        if self.child_page is not None and self.type == BlockKind.CHILD_PAGE:
            return self.child_page.title
        if self.child_database is not None and self.type == BlockKind.CHILD_DATABASE:
            return self.child_database.title
        if self.table_row is not None and self.type == BlockKind.TABLE_ROW:
            return " | ".join(
                "".join(run.plain_text for run in cell).replace("|", "\\|")
                for cell in self.table_row.cells
            )
        if self.equation is not None and self.type == BlockKind.EQUATION:
            return self.equation.expression
        if self.type == BlockKind.DIVIDER:
            return "---"
        if self.type in STRUCTURAL_BLOCKS:
            return ""
        return None


class OmittedBlock(NotionModel):
    block_id: str
    start_cursor: str | None = None
    reason: OmissionReason
    block_type: BlockKind | None = None


class PageView(NotionModel):
    page_id: str
    block_id: str
    title: str | None
    text: str
    text_offset: int
    next_text_offset: int | None
    state: ReadState
    omitted: list[OmittedBlock]
    web_link: str | None
    last_edited: str | None


class ReadWindow(NotionModel):
    """Invocation-local counters; retained text is bounded independently of traversal."""

    model_config = {"frozen": False}
    offset: int
    total: int = 0
    requests: int = 0
    parts: list[str] = Field(default_factory=list)
    omitted: list[OmittedBlock] = Field(default_factory=list)

    def add(self, text: str) -> None:
        piece = text + "\n"
        begin = max(0, self.offset - self.total)
        end = min(len(piece), self.offset + MAX_TEXT_CHARS - self.total)
        if end > begin:
            self.parts.append(piece[begin:end])
        self.total += len(piece)


METADATA = TypeAdapter(Metadata)
SEARCH_PAGE = TypeAdapter(CursorPage[Metadata])
BLOCK = TypeAdapter(Block)
BLOCK_PAGE = TypeAdapter(CursorPage[Block])
