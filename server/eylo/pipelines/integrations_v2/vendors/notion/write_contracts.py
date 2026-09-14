"""Notion 2022-06-28 page/block writes and capability-dependent acknowledgements."""

import json
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_BLOCKS = 100
MAX_RICH_TEXT_CHARS = 2000
MAX_RICH_TEXT_RUNS = 100
MAX_INPUT_CHARS = 100_000
MAX_REQUEST_BYTES = 500_000
TITLE_PROPERTY_ID = "title"


class NotionErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    INPUT_TOO_LARGE = "input_too_large"


class ParentKind(StrEnum):
    PAGE = "page"
    DATABASE = "database"


class PropertyKind(StrEnum):
    TITLE = "title"
    RICH_TEXT = "rich_text"
    NUMBER = "number"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    STATUS = "status"
    DATE = "date"
    PEOPLE = "people"
    FILES = "files"
    CHECKBOX = "checkbox"
    URL = "url"
    EMAIL = "email"
    PHONE_NUMBER = "phone_number"
    FORMULA = "formula"
    RELATION = "relation"
    ROLLUP = "rollup"
    CREATED_TIME = "created_time"
    CREATED_BY = "created_by"
    LAST_EDITED_TIME = "last_edited_time"
    LAST_EDITED_BY = "last_edited_by"
    UNIQUE_ID = "unique_id"
    VERIFICATION = "verification"
    BUTTON = "button"


class AcknowledgementExtent(StrEnum):
    IDENTITY = "identity_only"
    PAGE_METADATA = "page_metadata_verified"
    BLOCK_TEXT = "block_text_verified"


class WriteState(StrEnum):
    CREATED = "created"
    APPENDED = "appended"


def native_id(value: str) -> str:
    """Normalize native UUIDs without admitting URL/path syntax from responses."""
    if len(value) not in (32, 36):
        raise ValueError("Expected a Notion UUID.")
    return str(UUID(value))


def identifier(value: str) -> str:
    """Accept a UUID or a Notion page URL; never use arbitrary input as a path."""
    candidate = value.strip()
    if "://" in candidate:
        parsed = urlsplit(candidate)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or not (
                host in {"notion.so", "notion.site"}
                or host.endswith(".notion.so")
                or host.endswith(".notion.site")
            )
        ):
            raise ValueError("Use a Notion UUID or HTTPS Notion page URL.")
        candidate = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if len(candidate.rsplit("-", 1)[-1]) == 32:
            candidate = candidate.rsplit("-", 1)[-1]
    return native_id(candidate)


NativeId = Annotated[str, AfterValidator(native_id)]
InputId = Annotated[
    str, Field(min_length=1, max_length=4096), AfterValidator(identifier)
]


class NotionModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class NotionRequest(NotionModel):
    model_config = ConfigDict(extra="forbid")


class TextContent(NotionRequest):
    content: str = Field(max_length=MAX_RICH_TEXT_CHARS)


class TextRun(NotionRequest):
    type: Literal["text"] = "text"
    text: TextContent


class RichTextRead(NotionModel):
    type: Literal["text", "mention", "equation"]
    plain_text: str


class ParagraphContent(NotionRequest):
    rich_text: list[TextRun] = Field(max_length=MAX_RICH_TEXT_RUNS)


class ParagraphWrite(NotionRequest):
    object: Literal["block"] = "block"
    type: Literal["paragraph"] = "paragraph"
    paragraph: ParagraphContent


class PageParent(NotionModel):
    type: Literal["page_id"] = "page_id"
    page_id: NativeId


class DatabaseParent(NotionModel):
    type: Literal["database_id"] = "database_id"
    database_id: NativeId


class BlockParent(NotionModel):
    type: Literal["block_id"] = "block_id"
    block_id: NativeId


WriteParent = Annotated[PageParent | DatabaseParent, Field(discriminator="type")]
BlockOwner = Annotated[PageParent | BlockParent, Field(discriminator="type")]


class TitleWrite(NotionRequest):
    title: list[TextRun] = Field(min_length=1, max_length=MAX_RICH_TEXT_RUNS)


class CreateRequest(NotionRequest):
    parent: WriteParent
    properties: dict[str, TitleWrite]
    children: list[ParagraphWrite] = Field(default_factory=list, max_length=MAX_BLOCKS)


class AppendRequest(NotionRequest):
    children: list[ParagraphWrite] = Field(min_length=1, max_length=MAX_BLOCKS)


class TitleRead(NotionModel):
    """Only title values are consumed by the page-write acknowledgement."""

    type: Annotated[
        PropertyKind,
        BeforeValidator(
            lambda value: PropertyKind(value) if isinstance(value, str) else value
        ),
    ]
    title: list[RichTextRead] | None = None

    @model_validator(mode="after")
    def title_present(self) -> Self:
        if self.type == PropertyKind.TITLE and self.title is None:
            raise ValueError("A title property must contain its rich text value.")
        return self


class PageAcknowledgement(NotionModel):
    """Insert-only integrations can receive a partial page containing just its ID."""

    object: Literal["page"]
    id: NativeId
    parent: WriteParent | None = None
    properties: dict[str, TitleRead] | None = None
    url: str | None = None

    @model_validator(mode="after")
    def full_or_partial(self) -> Self:
        if ("parent" in self.model_fields_set and self.parent is None) or (
            "properties" in self.model_fields_set and self.properties is None
        ):
            raise ValueError("Full page fields cannot be null.")
        if (self.parent is None) != (self.properties is None):
            raise ValueError("A full page must include both parent and properties.")
        return self

    def title_text(self) -> str | None:
        if self.properties is None:
            return None
        titles = [
            value.title
            for value in self.properties.values()
            if value.type == PropertyKind.TITLE
        ]
        if len(titles) != 1:
            invalid_response()
        runs = titles[0]
        if runs is not None:
            return "".join(run.plain_text for run in runs)
        invalid_response()


class ParagraphRead(NotionModel):
    rich_text: list[RichTextRead]


class BlockAcknowledgement(NotionModel):
    object: Literal["block"]
    id: NativeId
    type: Literal["paragraph"] | None = None
    paragraph: ParagraphRead | None = None
    parent: BlockOwner | None = None

    @model_validator(mode="after")
    def full_or_partial(self) -> Self:
        if ("type" in self.model_fields_set and self.type is None) or (
            "paragraph" in self.model_fields_set and self.paragraph is None
        ):
            raise ValueError("Full block fields cannot be null.")
        if (self.type is None) != (self.paragraph is None):
            raise ValueError("A paragraph acknowledgement must contain its text.")
        return self


class AppendAcknowledgement(NotionModel):
    object: Literal["list"]
    results: list[BlockAcknowledgement]
    has_more: bool
    next_cursor: None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.has_more:
            raise ValueError("Append acknowledgement must include all inserted blocks.")
        return self


class CreateInput(NotionRequest):
    title: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)
    parent_id: InputId
    parent_kind: (
        Annotated[
            ParentKind,
            BeforeValidator(
                lambda value: ParentKind(value) if isinstance(value, str) else value
            ),
        ]
        | None
    ) = None
    parent_is_database: bool | None = Field(default=None, deprecated=True)
    body: str | None = Field(default=None, max_length=MAX_INPUT_CHARS)

    @model_validator(mode="after")
    def parent_mode(self) -> Self:
        if self.parent_kind is not None and self.parent_is_database is not None:
            raise ValueError("Use parent_kind, not both parent selectors.")
        return self

    @property
    def selected_parent(self) -> ParentKind:
        if self.parent_kind is not None:
            return self.parent_kind
        return ParentKind.DATABASE if self.parent_is_database else ParentKind.PAGE


class AppendInput(NotionRequest):
    page_id: InputId
    text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)


class CreateView(NotionModel):
    page_id: str
    title: str | None
    requested_title: str
    web_link: str | None
    state: WriteState = WriteState.CREATED
    acknowledgement: AcknowledgementExtent
    body_blocks_submitted: int


class AppendView(NotionModel):
    page_id: str
    block_ids: list[str]
    blocks_added: int
    state: WriteState = WriteState.APPENDED
    acknowledgement: AcknowledgementExtent


PAGE_ACK = TypeAdapter(PageAcknowledgement)
APPEND_ACK = TypeAdapter(AppendAcknowledgement)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        NotionErrorCode.RESPONSE_INVALID,
        "Notion returned an invalid response for this operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(NotionErrorCode.REJECTED, "Notion rejected the request.")
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def text_runs(text: str) -> list[TextRun]:
    return [
        TextRun(text=TextContent(content=text[offset : offset + MAX_RICH_TEXT_CHARS]))
        for offset in range(0, len(text), MAX_RICH_TEXT_CHARS)
    ]


def write_payload(body: CreateRequest | AppendRequest) -> dict[str, object]:
    """Apply the vendor byte limit using the guarded client's JSON encoding."""
    payload = body.model_dump(mode="json")
    if (
        len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
        > MAX_REQUEST_BYTES
    ):
        raise VendorToolError(
            NotionErrorCode.INPUT_TOO_LARGE,
            "The Notion write exceeds 500 KB. Split the content before retrying.",
        )
    return payload


def paragraphs(text: str) -> list[ParagraphWrite]:
    """Refuse oversize writes before any mutation; never silently discard lines."""
    lines = text.split("\n")
    if len(lines) > MAX_BLOCKS:
        raise VendorToolError(
            NotionErrorCode.INPUT_TOO_LARGE,
            "Notion accepts at most 100 paragraph lines per write. Split the text.",
        )
    return [
        ParagraphWrite(paragraph=ParagraphContent(rich_text=text_runs(line)))
        for line in lines
    ]
