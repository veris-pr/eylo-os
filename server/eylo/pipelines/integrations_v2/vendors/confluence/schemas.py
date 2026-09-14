"""Confluence v2 page/space and v1 search contracts; pagination URLs are never followed."""

import re
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn
from urllib.parse import parse_qs, urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from ...contracts import VendorResponse, VendorToolError

V2 = "/api/v2"
SEARCH = "/rest/api/search"
SPACES = V2 + "/spaces"
PAGES = V2 + "/pages"
DEFAULT_SEARCH_LIMIT = 25
MAX_SEARCH_LIMIT = 100
DEFAULT_SPACE_LIMIT = 50
MAX_SPACE_LIMIT = 250
SPACE_LOOKUP_LIMIT = 2
MAX_CURSOR_CHARS = 4_096
MAX_VERSION = 2_147_483_647
PAGE_FILTER_CQL = "type = page"
RECENT_FIRST_CQL = " ORDER BY lastmodified DESC"


class CqlField(StrEnum):
    SPACE = "space"
    TITLE = "title"
    TEXT = "text"


class CqlOperator(StrEnum):
    EQUALS = "="
    MATCHES = "~"


class ConfluenceErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SPACE_NOT_FOUND = "space_not_found"
    SPACE_AMBIGUOUS = "space_ambiguous"
    PAGE_NOT_CURRENT = "page_not_current"
    VERSION_EXHAUSTED = "page_version_exhausted"


class ContentStatus(StrEnum):
    CURRENT = "current"
    DRAFT = "draft"
    ARCHIVED = "archived"
    HISTORICAL = "historical"
    TRASHED = "trashed"
    DELETED = "deleted"


class SpaceType(StrEnum):
    GLOBAL = "global"
    COLLABORATION = "collaboration"
    KNOWLEDGE_BASE = "knowledge_base"
    PERSONAL = "personal"
    SYSTEM = "system"
    ONBOARDING = "onboarding"
    XFLOW_SAMPLE = "xflow_sample_space"


class LinkParameter(StrEnum):
    RELATION = "rel"
    NEXT = "next"
    CURSOR = "cursor"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Confluence timestamps require a timezone.")
    return value


Identifier = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]
Cursor = Annotated[
    str,
    Field(min_length=1, max_length=MAX_CURSOR_CHARS, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
Timestamp = Annotated[str, AfterValidator(timestamp)]
NativeStatus = Annotated[
    ContentStatus,
    BeforeValidator(lambda v: ContentStatus(v) if isinstance(v, str) else v),
]
NativeSpaceType = Annotated[
    SpaceType, BeforeValidator(lambda v: SpaceType(v) if isinstance(v, str) else v)
]


class ConfluenceModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        populate_by_name=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class Links(ConfluenceModel):
    next: NonEmpty | None = None
    webui: NonEmpty | None = None


class Version(ConfluenceModel):
    number: int = Field(ge=1, le=MAX_VERSION)


class StorageBody(ConfluenceModel):
    representation: Literal["storage"] = "storage"
    value: str


class PageBody(ConfluenceModel):
    storage: StorageBody | None = None


class Page(ConfluenceModel):
    id: Identifier
    title: str
    space_id: Identifier = Field(alias="spaceId")
    parent_id: Identifier | None = Field(default=None, alias="parentId")
    status: NativeStatus
    version: Version
    body: PageBody | None = None
    links: Links = Field(default_factory=Links, alias="_links")


class Space(ConfluenceModel):
    id: Identifier
    key: NonEmpty
    name: NonEmpty
    type: NativeSpaceType


class SpacesPage(ConfluenceModel):
    results: list[Space]
    links: Links = Field(default_factory=Links, alias="_links")


class SearchContent(ConfluenceModel):
    id: Identifier
    type: Literal["page"]
    title: str


class Container(ConfluenceModel):
    title: str


class SearchEntry(ConfluenceModel):
    content: SearchContent
    title: str
    url: NonEmpty
    excerpt: str
    last_modified: Timestamp = Field(alias="lastModified")
    container: Container | None = Field(default=None, alias="resultGlobalContainer")


class SearchPage(ConfluenceModel):
    results: list[SearchEntry]
    links: Links = Field(alias="_links")


class SpacesQuery(ConfluenceModel):
    limit: int = Field(ge=1, le=MAX_SPACE_LIMIT)
    cursor: Cursor | None = None
    keys: str | None = None


class SearchQuery(ConfluenceModel):
    cql: NonEmpty
    limit: int = Field(ge=1, le=MAX_SEARCH_LIMIT)
    cursor: Cursor | None = None


class PageQuery(ConfluenceModel):
    body_format: Literal["storage"] = Field(
        default="storage", serialization_alias="body-format"
    )


class CreatePageRequest(ConfluenceModel):
    space_id: Identifier = Field(serialization_alias="spaceId")
    status: Literal[ContentStatus.CURRENT] = ContentStatus.CURRENT
    title: NonEmpty
    body: StorageBody
    parent_id: Identifier | None = Field(default=None, serialization_alias="parentId")


class UpdatePageRequest(ConfluenceModel):
    id: Identifier
    status: Literal[ContentStatus.CURRENT] = ContentStatus.CURRENT
    title: NonEmpty
    body: StorageBody
    version: Version


class PageResult(ConfluenceModel):
    id: Identifier
    title: str
    space_id: Identifier
    status: ContentStatus
    version: int
    body: str | None
    link: str | None


class SpacesResult(ConfluenceModel):
    spaces: list[Space]
    count: int
    next_cursor: Cursor | None


class SearchResult(ConfluenceModel):
    id: Identifier
    title: str
    space: str | None
    excerpt: str | None
    last_modified: str
    link: str


class SearchResults(ConfluenceModel):
    cql: str
    pages: list[SearchResult]
    count: int
    next_cursor: Cursor | None


PAGE_RESPONSE = TypeAdapter(Page)
SPACES_RESPONSE = TypeAdapter(SpacesPage)
SEARCH_RESPONSE = TypeAdapter(SearchPage)
CURSOR_VALUE = TypeAdapter(Cursor)
_LINK = re.compile(r'<([^<>]+)>((?:\s*;\s*[A-Za-z_-]+\s*=\s*(?:"[^"]*"|[^;,\s]+))*)\s*')
_PARAMETER = re.compile(r';\s*([A-Za-z_-]+)\s*=\s*(?:"([^"]*)"|([^;,\s]+))')


def invalid_response() -> NoReturn:
    raise VendorToolError(
        ConfluenceErrorCode.RESPONSE_INVALID,
        "Confluence returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            ConfluenceErrorCode.REJECTED, "Confluence rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def next_cursor(
    response: VendorResponse, links: Links, *, path: str, previous: str | None
) -> str | None:
    """Retain only the opaque token; subsequent calls rebuild the known vendor path/query."""
    targets = [links.next] if links.next is not None else []
    header_next = None
    for header in response.link_headers:
        for part in re.split(r",\s*(?=<)", header):
            match = _LINK.fullmatch(part.strip())
            if match is None:
                raise VendorToolError(
                    ConfluenceErrorCode.RESPONSE_INVALID,
                    "Confluence returned malformed pagination metadata.",
                )
            parameters: dict[str, str] = {}
            for item in _PARAMETER.finditer(match.group(2)):
                name = item.group(1).lower()
                if name in parameters:
                    invalid_response()
                parameters[name] = (
                    item.group(2) if item.group(2) is not None else item.group(3)
                )
            if (
                LinkParameter.NEXT
                not in parameters.get(LinkParameter.RELATION, "").split()
            ):
                continue
            if header_next is not None:
                invalid_response()
            header_next = match.group(1)
    if header_next is not None:
        targets.append(header_next)
    tokens: set[str] = set()
    for target in targets:
        try:
            parsed = urlsplit(target)
            if (
                parsed.scheme not in {"", "https"}
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {path, "/wiki" + path}
            ):
                invalid_response()
            values = parse_qs(parsed.query).get(LinkParameter.CURSOR, [])
            if len(values) != 1:
                invalid_response()
            tokens.add(CURSOR_VALUE.validate_python(values[0], strict=True))
        except (ValueError, ValidationError):
            invalid_response()
    if len(tokens) > 1:
        invalid_response()
    result = next(iter(tokens), None)
    if result is not None and result == previous:
        invalid_response()
    return result
