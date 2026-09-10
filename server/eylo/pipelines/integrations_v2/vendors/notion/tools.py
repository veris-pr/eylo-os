"""Curated Notion tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .query_contracts import (
    DATABASE,
    QUERY_PAGE,
    QueryErrorCode,
    QueryRequest,
    QueryView,
    RowView,
    property_filter,
)
from .query_contracts import QueryInput as QueryDatabaseInput
from .read_contracts import (
    BLOCK,
    BLOCK_PAGE,
    MAX_ANCESTOR_REQUESTS,
    MAX_TEXT_CHARS,
    MAX_TREE_DEPTH,
    MAX_TREE_REQUESTS,
    METADATA,
    SEARCH_PAGE,
    Block,
    BlockKind,
    ChildrenQuery,
    OmissionReason,
    OmittedBlock,
    PageView,
    ReadErrorCode,
    ReadPageInput,
    ReadState,
    ReadWindow,
    SearchEntry,
    SearchFilter,
    SearchInput,
    SearchKind,
    SearchRequest,
    SearchView,
)
from .write_contracts import (
    APPEND_ACK,
    PAGE_ACK,
    TITLE_PROPERTY_ID,
    AcknowledgementExtent,
    AppendRequest,
    AppendView,
    BlockParent,
    CreateRequest,
    CreateView,
    DatabaseParent,
    PageParent,
    ParentKind,
    TitleWrite,
    invalid_response,
    paragraphs,
    parse_response,
    text_runs,
    write_payload,
)
from .write_contracts import (
    AppendInput as AppendToPageInput,
)
from .write_contracts import (
    CreateInput as CreatePageInput,
)


@curated_tool(
    vendor=vendor.vendor,
    name="search",
    display_name="Search Notion",
    description=(
        "Find pages and databases the integration can see, by title. Notion "
        "only surfaces shared content. This searches titles, not page bodies. "
        "Repeat the same query with start_cursor to continue. Partial metadata "
        "is explicitly indicated; an empty title is distinct from unavailable metadata."
    ),
    input_model=SearchInput,
    effect=ToolEffect.READ,
)
async def search(payload: SearchInput, ctx: VendorToolContext) -> dict[str, object]:
    body = SearchRequest(
        query=payload.query,
        filter=SearchFilter(value=payload.only) if payload.only is not None else None,
        page_size=payload.limit,
        start_cursor=payload.start_cursor,
    )
    page = parse_response(
        await ctx.read(
            "/search",
            method="POST",
            json=body.model_dump(mode="json", exclude_none=True),
        ),
        SEARCH_PAGE,
    )
    if page.next_cursor is not None and page.next_cursor == payload.start_cursor:
        raise VendorToolError(
            QueryErrorCode.PAGINATION_INVALID, "Notion repeated the input cursor."
        )
    if len({item.id for item in page.results}) != len(page.results):
        invalid_response()
    entries = []
    for item in page.results:
        if payload.only is not None and item.object != payload.only:
            raise VendorToolError(
                QueryErrorCode.IDENTITY_MISMATCH, "Notion ignored the object filter."
            )
        title = item.title_text()
        entries.append(
            SearchEntry(
                id=item.id,
                object=SearchKind(item.object),
                title=title,
                web_link=item.url,
                last_edited=item.last_edited_time,
                metadata_state=ReadState.COMPLETE
                if title is not None
                else ReadState.PARTIAL,
            )
        )
    return SearchView(
        results=entries, count=len(entries), next_cursor=page.next_cursor
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="read_page",
    display_name="Read Notion Page",
    description=(
        "Read a page's content as text. Notion stores it as a tree of blocks "
        "whose text is split into styled runs; this walks the tree and returns "
        "readable markdown, keeping headings, bullets, and to-do state. Nested "
        "content is followed up to three levels with a bounded request budget. "
        "Omitted subtrees expose block_id/start_cursor for a subsequent call. "
        "Use next_text_offset with the same inputs for more rendered text. "
        "Unsupported blocks are reported. Reads are live, not a versioned snapshot."
    ),
    input_model=ReadPageInput,
    effect=ToolEffect.READ,
)
async def read_page(
    payload: ReadPageInput, ctx: VendorToolContext
) -> dict[str, object]:
    page = parse_response(await ctx.read(f"/pages/{payload.page_id}"), METADATA)
    if page.id != payload.page_id or page.object != SearchKind.PAGE:
        raise VendorToolError(
            QueryErrorCode.IDENTITY_MISMATCH, "Notion returned a different page."
        )
    root = payload.block_id or payload.page_id
    expected_parent = None
    if root != payload.page_id:
        target = await _require_descendant(ctx, root, payload.page_id)
        if (
            target.synced_block is not None
            and target.synced_block.synced_from is not None
        ):
            expected_parent = target.synced_block.synced_from.block_id
    window = ReadWindow(offset=payload.text_offset)
    if page.title_text() is None:
        window.omitted.append(
            OmittedBlock(
                block_id=payload.page_id, reason=OmissionReason.METADATA_UNAVAILABLE
            )
        )
    await _walk_blocks(
        ctx,
        root,
        cursor=payload.start_cursor,
        depth=0,
        ancestors=frozenset(),
        window=window,
        expected_parent=expected_parent,
    )
    if payload.text_offset > window.total:
        raise VendorToolError(
            ReadErrorCode.TARGET_INVALID,
            "text_offset exceeds this traversal window; the page may have changed.",
        )
    next_offset = payload.text_offset + MAX_TEXT_CHARS
    has_more_text = next_offset < window.total
    return PageView(
        page_id=page.id,
        block_id=root,
        title=page.title_text(),
        text="".join(window.parts),
        text_offset=payload.text_offset,
        next_text_offset=next_offset if has_more_text else None,
        state=ReadState.PARTIAL
        if window.omitted or has_more_text
        else ReadState.COMPLETE,
        omitted=window.omitted,
        web_link=page.url,
        last_edited=page.last_edited_time,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_page",
    display_name="Create Notion Page",
    description=(
        "Create a page under an existing page or database, optionally with "
        "opening content. Notion sets a title differently depending on which "
        "kind of parent it has; supply parent_kind=page or database. At most "
        "100 paragraph lines are accepted per call; split larger content. "
        "The result distinguishes a partial identity acknowledgement from a "
        "verified returned title; body_blocks_submitted is not a body readback."
    ),
    input_model=CreatePageInput,
    effect=ToolEffect.MUTATION,
)
async def create_page(
    payload: CreatePageInput, ctx: VendorToolContext
) -> dict[str, object]:
    parent = (
        DatabaseParent(database_id=payload.parent_id)
        if payload.selected_parent == ParentKind.DATABASE
        else PageParent(page_id=payload.parent_id)
    )
    body = CreateRequest(
        parent=parent,
        # Property IDs are accepted, so the stable title ID also supports a
        # database whose user-visible title column is named differently.
        properties={TITLE_PROPERTY_ID: TitleWrite(title=text_runs(payload.title))},
        children=paragraphs(payload.body) if payload.body is not None else [],
    )
    created = parse_response(
        await ctx.mutate("/pages", json=write_payload(body)), PAGE_ACK
    )
    title = created.title_text()
    if created.parent is not None and (
        created.parent != parent or title != payload.title
    ):
        invalid_response()
    return CreateView(
        page_id=created.id,
        title=title,
        requested_title=payload.title,
        web_link=created.url,
        acknowledgement=(
            AcknowledgementExtent.PAGE_METADATA
            if created.parent is not None
            else AcknowledgementExtent.IDENTITY
        ),
        body_blocks_submitted=len(body.children),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="append_to_page",
    display_name="Append to Notion Page",
    description=(
        "Add text to the end of a page. Each line becomes its own paragraph "
        "block, which is the structure Notion stores; plain text is enough. "
        "At most 100 lines per call; split larger text. Returned block IDs "
        "acknowledge insertion; block_text_verified additionally checks returned text."
    ),
    input_model=AppendToPageInput,
    effect=ToolEffect.MUTATION,
)
async def append_to_page(
    payload: AppendToPageInput, ctx: VendorToolContext
) -> dict[str, object]:
    body = AppendRequest(children=paragraphs(payload.text))
    response = await ctx.mutate(
        f"/blocks/{payload.page_id}/children",
        method="PATCH",
        json=write_payload(body),
    )
    added = parse_response(response, APPEND_ACK)
    ids = [block.id for block in added.results]
    if len(ids) != len(body.children) or len(set(ids)) != len(ids):
        invalid_response()
    extent = AcknowledgementExtent.BLOCK_TEXT
    for expected, actual in zip(body.children, added.results, strict=True):
        if actual.parent is not None:
            owner_id = (
                actual.parent.block_id
                if isinstance(actual.parent, BlockParent)
                else actual.parent.page_id
            )
            if owner_id != payload.page_id:
                invalid_response()
        if actual.paragraph is None:
            extent = AcknowledgementExtent.IDENTITY
        elif "".join(run.plain_text for run in actual.paragraph.rich_text) != "".join(
            run.text.content for run in expected.paragraph.rich_text
        ):
            invalid_response()
    return AppendView(
        page_id=payload.page_id,
        block_ids=ids,
        blocks_added=len(ids),
        acknowledgement=extent,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="query_database",
    display_name="Query Notion Database",
    description=(
        "List rows from a database, optionally filtered on one property by "
        "exact match or by containment. Notion's filters are typed per "
        "property, so the property's type is looked up here rather than having "
        "to be known. Supply start_cursor with the same query for the next page. "
        "Unsupported operator/type combinations are refused, never reinterpreted. "
        "Rows include property_extents: inline references/formulas may require "
        "Notion property-item pagination and are not a complete property export."
    ),
    input_model=QueryDatabaseInput,
    effect=ToolEffect.READ,
)
async def query_database(
    payload: QueryDatabaseInput, ctx: VendorToolContext
) -> dict[str, object]:
    condition = None
    if payload.property_name is not None:
        schema = parse_response(
            await ctx.read(f"/databases/{payload.database_id}"), DATABASE
        )
        if schema.id != payload.database_id:
            raise VendorToolError(
                QueryErrorCode.IDENTITY_MISMATCH,
                "Notion returned a different database.",
            )
        definition = schema.properties.get(payload.property_name)
        if definition is None:
            raise VendorToolError(
                QueryErrorCode.PROPERTY_NOT_FOUND,
                "The requested property is not present in the accessible database schema.",
            )
        condition = property_filter(payload, definition)
    body = QueryRequest(
        page_size=payload.limit, start_cursor=payload.start_cursor, filter=condition
    )
    page = parse_response(
        await ctx.read(
            f"/databases/{payload.database_id}/query",
            method="POST",
            json=body.model_dump(mode="json", exclude_none=True),
        ),
        QUERY_PAGE,
    )
    if page.next_cursor is not None and page.next_cursor == payload.start_cursor:
        raise VendorToolError(
            QueryErrorCode.PAGINATION_INVALID, "Notion repeated the input cursor."
        )
    rows = []
    for row in page.results:
        if row.parent.database_id != payload.database_id:
            raise VendorToolError(
                QueryErrorCode.IDENTITY_MISMATCH,
                "A query row belongs to a different database.",
            )
        values = {name: value.projection() for name, value in row.properties.items()}
        rows.append(
            RowView(
                page_id=row.id,
                web_link=row.url,
                properties={name: value for name, (value, _) in values.items()},
                property_extents={name: extent for name, (_, extent) in values.items()},
            )
        )
    return QueryView(
        database_id=payload.database_id,
        rows=rows,
        count=len(rows),
        next_cursor=page.next_cursor,
    ).model_dump(mode="json")


async def _require_descendant(
    ctx: VendorToolContext, block_id: str, page_id: str
) -> Block:
    current = block_id
    target: Block | None = None
    visited: set[str] = set()
    for _ in range(MAX_ANCESTOR_REQUESTS):
        if current in visited:
            raise VendorToolError(
                ReadErrorCode.CYCLE, "Notion returned a cyclic ancestor chain."
            )
        visited.add(current)
        block = parse_response(await ctx.read(f"/blocks/{current}"), BLOCK)
        if target is None:
            target = block
        if block.id != current or block.parent is None:
            raise VendorToolError(
                ReadErrorCode.TARGET_INVALID,
                "Cannot establish this block's page ownership.",
            )
        if isinstance(block.parent, PageParent):
            if block.parent.page_id == page_id:
                return target
            break
        current = block.parent.block_id
    raise VendorToolError(
        ReadErrorCode.TARGET_INVALID,
        "The block is not a verified descendant of this page.",
    )


async def _walk_blocks(
    ctx: VendorToolContext,
    block_id: str,
    *,
    cursor: str | None,
    depth: int,
    ancestors: frozenset[str],
    window: ReadWindow,
    expected_parent: str | None = None,
) -> None:
    if block_id in ancestors:
        raise VendorToolError(
            ReadErrorCode.CYCLE, "Notion returned a cyclic block tree."
        )
    if depth > MAX_TREE_DEPTH:
        window.omitted.append(
            OmittedBlock(
                block_id=block_id,
                start_cursor=cursor,
                reason=OmissionReason.DEPTH_LIMIT,
            )
        )
        return
    seen_cursors: set[str] = set()
    seen_blocks: set[str] = set()
    while True:
        if window.requests >= MAX_TREE_REQUESTS:
            window.omitted.append(
                OmittedBlock(
                    block_id=block_id,
                    start_cursor=cursor,
                    reason=OmissionReason.REQUEST_LIMIT,
                )
            )
            return
        if cursor is not None:
            if cursor in seen_cursors:
                raise VendorToolError(
                    QueryErrorCode.PAGINATION_INVALID, "Notion repeated a block cursor."
                )
            seen_cursors.add(cursor)
        window.requests += 1
        query = ChildrenQuery(start_cursor=cursor)
        page = parse_response(
            await ctx.read(
                f"/blocks/{block_id}/children",
                query=query.model_dump(mode="json", exclude_none=True),
            ),
            BLOCK_PAGE,
        )
        for block in page.results:
            if block.id == block_id or block.id in ancestors:
                raise VendorToolError(
                    ReadErrorCode.CYCLE, "Notion returned a cyclic block identity."
                )
            if block.id in seen_blocks:
                invalid_response()
            seen_blocks.add(block.id)
            if block.parent is not None:
                owner = (
                    block.parent.page_id
                    if isinstance(block.parent, PageParent)
                    else block.parent.block_id
                )
                if owner not in {block_id, expected_parent}:
                    raise VendorToolError(
                        QueryErrorCode.IDENTITY_MISMATCH,
                        "A block belongs to a different parent.",
                    )
            rendered = block.text()
            if rendered is None:
                window.omitted.append(
                    OmittedBlock(
                        block_id=block.id,
                        block_type=block.type,
                        reason=OmissionReason.METADATA_UNAVAILABLE
                        if block.type is None
                        else OmissionReason.UNSUPPORTED,
                    )
                )
            elif rendered or block.type not in {
                BlockKind.COLUMN,
                BlockKind.COLUMN_LIST,
                BlockKind.TABLE,
                BlockKind.SYNCED_BLOCK,
            }:
                window.add(
                    "\n".join("  " * depth + line for line in rendered.split("\n"))
                )
            if block.has_children:
                source = (
                    block.synced_block.synced_from
                    if block.synced_block is not None
                    else None
                )
                await _walk_blocks(
                    ctx,
                    block.id,
                    cursor=None,
                    depth=depth + 1,
                    ancestors=ancestors | {block_id},
                    window=window,
                    expected_parent=source.block_id if source is not None else None,
                )
        if not page.has_more:
            return
        cursor = page.next_cursor


__all__ = [
    "append_to_page",
    "create_page",
    "query_database",
    "read_page",
    "search",
]
