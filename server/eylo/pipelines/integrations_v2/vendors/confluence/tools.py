"""Typed Confluence reads and version-checked page mutations."""

import html
import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import READ_PAGE, READ_SPACE, SEARCH_CONTENT, WRITE_PAGE, vendor
from .schemas import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SPACE_LIMIT,
    MAX_SEARCH_LIMIT,
    MAX_SPACE_LIMIT,
    MAX_VERSION,
    PAGES,
    PAGE_FILTER_CQL,
    PAGE_RESPONSE,
    RECENT_FIRST_CQL,
    SEARCH,
    SEARCH_RESPONSE,
    SPACES,
    SPACES_RESPONSE,
    SPACE_LOOKUP_LIMIT,
    ConfluenceErrorCode,
    ContentStatus,
    CqlField,
    CqlOperator,
    CreatePageRequest,
    Cursor,
    Identifier,
    NonEmpty,
    Page,
    PageQuery,
    PageResult,
    SearchQuery,
    SearchResult,
    SearchResults,
    SpacesQuery,
    SpacesResult,
    StorageBody,
    UpdatePageRequest,
    Version,
    invalid_response,
    next_cursor,
    parse_response,
)

_TAG = re.compile(r"<[^>]+>")


class ConfluenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SearchPagesInput(ConfluenceInput):
    text: str | None = Field(
        default=None, description="Free text matched against page title and body."
    )
    space_key: str | None = Field(
        default=None, description="Restrict to an exact space key."
    )
    title: str | None = Field(default=None, description="Exact page title.")
    cql: str | None = Field(
        default=None, description="Raw CQL selecting pages. Overrides simple filters."
    )
    limit: StrictInt = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)
    cursor: Cursor | None = Field(
        default=None, description="Use next_cursor with unchanged search filters."
    )

    @model_validator(mode="after")
    def require_search(self) -> Self:
        if not any(
            value and value.strip()
            for value in (self.cql, self.text, self.title, self.space_key)
        ):
            raise ValueError("Supply CQL or at least one search filter.")
        return self


class GetPageInput(ConfluenceInput):
    page_id: Identifier = Field(description="Numeric page ID.")


class CreatePageInput(ConfluenceInput):
    space_key: NonEmpty = Field(description="Exact space key such as ENG.")
    title: NonEmpty = Field(description="Page title.")
    body: str = Field(default="", description="Page body as plain text.")
    parent_page_id: Identifier | None = Field(
        default=None, description="Create as a child of this page."
    )


class UpdatePageInput(GetPageInput):
    body: NonEmpty = Field(description="Replacement body as plain text.")
    title: NonEmpty | None = Field(
        default=None, description="New title, if changing it."
    )


class ListSpacesInput(ConfluenceInput):
    query: str | None = Field(
        default=None, description="Filter space name/key within each returned page."
    )
    limit: StrictInt = Field(default=DEFAULT_SPACE_LIMIT, ge=1, le=MAX_SPACE_LIMIT)
    cursor: Cursor | None = Field(
        default=None,
        description="Use next_cursor to continue, even after zero matches.",
    )


@curated_tool(
    vendor=vendor.vendor,
    name="list_spaces",
    display_name="List Confluence Spaces",
    description=(
        "List one page of spaces with IDs, keys, names and types. Optional query filters "
        "the current page only. Pass next_cursor as cursor to continue even when count "
        "is zero; no next_cursor means the vendor collection ended."
    ),
    input_model=ListSpacesInput,
    effect=ToolEffect.READ,
    scopes=(READ_SPACE,),
)
async def list_spaces(
    payload: ListSpacesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    request = SpacesQuery(limit=payload.limit, cursor=payload.cursor)
    response = await ctx.read(SPACES, query=request.model_dump(exclude_none=True))
    page = parse_response(response, SPACES_RESPONSE)
    _identities([space.id for space in page.results], payload.limit)
    cursor = next_cursor(response, page.links, path=SPACES, previous=payload.cursor)
    needle = (payload.query or "").strip().casefold()
    spaces = [
        space
        for space in page.results
        if not needle
        or needle in space.name.casefold()
        or needle in space.key.casefold()
    ]
    return SpacesResult(
        spaces=spaces, count=len(spaces), next_cursor=cursor
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="search_pages",
    display_name="Search Confluence Pages",
    description=(
        "Search one page of Confluence pages using free text, a space key or exact title. "
        "Raw CQL overrides simple filters and must select pages, not other content kinds. "
        "Results include IDs, titles, spaces, excerpts and source links. Pass next_cursor "
        "as cursor with unchanged filters to continue."
    ),
    input_model=SearchPagesInput,
    effect=ToolEffect.READ,
    scopes=(SEARCH_CONTENT,),
)
async def search_pages(
    payload: SearchPagesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    cql = (
        payload.cql.strip()
        if payload.cql and payload.cql.strip()
        else _build_cql(payload)
    )
    request = SearchQuery(cql=cql, limit=payload.limit, cursor=payload.cursor)
    response = await ctx.read(SEARCH, query=request.model_dump(exclude_none=True))
    page = parse_response(response, SEARCH_RESPONSE)
    _identities([entry.content.id for entry in page.results], payload.limit)
    cursor = next_cursor(response, page.links, path=SEARCH, previous=payload.cursor)
    pages = [
        SearchResult(
            id=entry.content.id,
            title=entry.title or entry.content.title,
            space=entry.container.title if entry.container else None,
            excerpt=_plain_text(entry.excerpt),
            last_modified=entry.last_modified,
            link=entry.url,
        )
        for entry in page.results
    ]
    return SearchResults(
        cql=cql, pages=pages, count=len(pages), next_cursor=cursor
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_page",
    display_name="Get Confluence Page",
    description=(
        "Read one page by ID. Its storage markup is flattened to plain text for reading; "
        "macros, attachments and layout are not rendered or fetched. An empty body differs "
        "from a missing requested body, which is an error."
    ),
    input_model=GetPageInput,
    effect=ToolEffect.READ,
    scopes=(READ_PAGE,),
)
async def get_page(
    payload: GetPageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    page = await _read_page(payload.page_id, ctx)
    if page.body is None or page.body.storage is None:
        invalid_response()
    return _page_view(page).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_page",
    display_name="Create Confluence Page",
    description=(
        "Create a published Confluence page in the exact space key, optionally under a "
        "parent page. Plain text is escaped into storage markup. The space is resolved "
        "first; ambiguous matches are refused. The returned page must match the requested "
        "space, title and explicit parent."
    ),
    input_model=CreatePageInput,
    effect=ToolEffect.MUTATION,
    scopes=(WRITE_PAGE, READ_SPACE),
)
async def create_page(
    payload: CreatePageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    space_id = await _resolve_space_id(ctx, payload.space_key)
    request = CreatePageRequest(
        space_id=space_id,
        title=payload.title,
        body=_text_to_storage(payload.body),
        parent_id=payload.parent_page_id,
    )
    page = parse_response(
        await ctx.mutate(
            PAGES,
            method="POST",
            json=request.model_dump(mode="json", by_alias=True, exclude_none=True),
        ),
        PAGE_RESPONSE,
    )
    if (
        page.space_id != space_id
        or page.title != payload.title
        or page.status is not ContentStatus.CURRENT
        or (
            payload.parent_page_id is not None
            and page.parent_id != payload.parent_page_id
        )
    ):
        invalid_response()
    return _page_view(page).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="update_page",
    display_name="Update Confluence Page",
    description=(
        "Replace the body of a currently published page with plain text, optionally changing "
        "its title. Read and increment the current version; concurrent edits are not "
        "overwritten by a blind retry. Draft, archived or deleted pages are refused, not "
        "silently published/restored. The acknowledgement must match identity and version."
    ),
    input_model=UpdatePageInput,
    effect=ToolEffect.MUTATION,
    scopes=(WRITE_PAGE, READ_PAGE),
)
async def update_page(
    payload: UpdatePageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    current = await _read_page(payload.page_id, ctx)
    if current.status is not ContentStatus.CURRENT:
        raise VendorToolError(
            ConfluenceErrorCode.PAGE_NOT_CURRENT,
            "Only a currently published page can be edited by this tool.",
        )
    if current.version.number == MAX_VERSION:
        raise VendorToolError(
            ConfluenceErrorCode.VERSION_EXHAUSTED,
            "The page version cannot be incremented.",
        )
    title = payload.title if payload.title is not None else current.title
    request = UpdatePageRequest(
        id=payload.page_id,
        title=title,
        body=_text_to_storage(payload.body),
        version=Version(number=current.version.number + 1),
    )
    page = parse_response(
        await ctx.mutate(
            f"{PAGES}/{payload.page_id}",
            method="PUT",
            json=request.model_dump(mode="json", by_alias=True),
        ),
        PAGE_RESPONSE,
    )
    if (
        page.id != payload.page_id
        or page.space_id != current.space_id
        or page.status is not ContentStatus.CURRENT
        or page.title != title
        or page.version.number != request.version.number
    ):
        invalid_response()
    return _page_view(page).model_dump(mode="json")


async def _read_page(page_id: str, ctx: VendorToolContext) -> Page:
    response = await ctx.read(
        f"{PAGES}/{page_id}", query=PageQuery().model_dump(by_alias=True)
    )
    page = parse_response(response, PAGE_RESPONSE)
    if page.id != page_id:
        invalid_response()
    return page


async def _resolve_space_id(ctx: VendorToolContext, space_key: str) -> str:
    wanted = space_key.strip()
    request = SpacesQuery(keys=wanted, limit=SPACE_LOOKUP_LIMIT)
    response = await ctx.read(SPACES, query=request.model_dump(exclude_none=True))
    page = parse_response(response, SPACES_RESPONSE)
    _identities([space.id for space in page.results], SPACE_LOOKUP_LIMIT)
    continuation = next_cursor(response, page.links, path=SPACES, previous=None)
    matches = [space for space in page.results if space.key == wanted]
    if continuation is not None or len(matches) > 1:
        raise VendorToolError(
            ConfluenceErrorCode.SPACE_AMBIGUOUS,
            "The space key did not resolve uniquely.",
        )
    if not matches:
        raise VendorToolError(
            ConfluenceErrorCode.SPACE_NOT_FOUND,
            "No accessible Confluence space matches this key.",
        )
    return matches[0].id


def _identities(ids: list[str], limit: int) -> None:
    if len(ids) > limit or len(ids) != len(set(ids)):
        invalid_response()


def _build_cql(payload: SearchPagesInput) -> str:
    clauses = [PAGE_FILTER_CQL]
    for name, operator, value in [
        (CqlField.SPACE, CqlOperator.EQUALS, payload.space_key),
        (CqlField.TITLE, CqlOperator.EQUALS, payload.title),
        (CqlField.TEXT, CqlOperator.MATCHES, payload.text),
    ]:
        if value and value.strip():
            clauses.append(f'{name} {operator} "{_cql_quote(value.strip())}"')
    return " AND ".join(clauses) + RECENT_FIRST_CQL


def _cql_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _page_view(page: Page) -> PageResult:
    return PageResult(
        id=page.id,
        title=page.title,
        space_id=page.space_id,
        status=page.status,
        version=page.version.number,
        body=_plain_text(page.body.storage.value)
        if page.body and page.body.storage
        else None,
        link=page.links.webui,
    )


def _text_to_storage(text: str) -> StorageBody:
    paragraphs = [
        f"<p>{html.escape(line)}</p>" if line.strip() else "<p />"
        for line in text.split("\n")
    ]
    return StorageBody(value="".join(paragraphs) or "<p />")


def _plain_text(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", markup))).strip()


__all__ = ["create_page", "get_page", "list_spaces", "search_pages", "update_page"]
