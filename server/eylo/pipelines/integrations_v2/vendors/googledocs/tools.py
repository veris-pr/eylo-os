"""Google Docs text tools: tab-aware reads and acknowledged, revision-safe writes."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictBool

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import DOCUMENTS, vendor
from .schemas import (
    CREATE_RESPONSE,
    DOCUMENT_RESPONSE,
    FIRST_TEXT_INDEX,
    HEADING_PREFIX,
    INSERT_RESPONSE,
    MAX_TEXT_CHARS,
    NON_TEXT_MARKER,
    REPLACE_RESPONSE,
    DocsAppendView,
    DocsBatchRequest,
    DocsBody,
    DocsContainsText,
    DocsCreateRequest,
    DocsCreateView,
    DocsDocument,
    DocsErrorCode,
    DocsHeading,
    DocsInsertRequest,
    DocsInsertText,
    DocsLocation,
    DocsReadQuery,
    DocsReadView,
    DocsReplaceRequest,
    DocsReplaceText,
    DocsReplaceView,
    DocsStructuralElement,
    DocsTab,
    DocsTabView,
    DocsTabsCriteria,
    DocsWriteControl,
    parse_response,
    require_identity,
)


class ReadDocumentInput(BaseModel):
    document_id: str = Field(
        min_length=1,
        description="Document id — the long identifier in its URL, or from Drive search.",
    )
    tab_id: str | None = Field(
        default=None,
        min_length=1,
        description="Read this tab only. Omit to read all tabs.",
    )


class CreateDocumentInput(BaseModel):
    title: str = Field(min_length=1)
    body: str | None = Field(
        default=None, description="Opening content. Written immediately after creation."
    )


class AppendTextInput(BaseModel):
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1, description="Text to add at the end.")
    start_on_new_line: StrictBool = Field(
        default=True, description="Begin with a line break so it does not run on."
    )
    tab_id: str | None = Field(
        default=None,
        min_length=1,
        description="Append to this tab. Omit for the first tab.",
    )


class ReplaceTextInput(BaseModel):
    document_id: str = Field(min_length=1)
    find: str = Field(min_length=1, description="Exact text to look for.")
    replace_with: str = Field(description="Replacement text. Empty removes the match.")
    match_case: StrictBool = Field(default=True)
    tab_id: str | None = Field(
        default=None,
        min_length=1,
        description="Replace in this tab only. Omit for all tabs.",
    )


@curated_tool(
    vendor=vendor.vendor,
    name="read_document",
    display_name="Read Google Doc",
    description=(
        "Read body text across document tabs, or select one tab. Preserves "
        "headings, table text and table-of-contents text. Non-text elements "
        "are marked, not interpreted. Headers, footers and footnotes are not "
        "included. Long text is truncated and marked as such."
    ),
    input_model=ReadDocumentInput,
    effect=ToolEffect.READ,
    scopes=(DOCUMENTS,),
)
async def read_document(
    payload: ReadDocumentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    document = await _read_document(ctx, payload.document_id)
    tabs = _tabs(document)
    selected = [_select_tab(tabs, payload.tab_id)] if payload.tab_id else tabs
    sections: list[str] = []
    for tab in selected:
        text = _flatten(tab.documentTab.body)
        sections.append(
            f"## {tab.tabProperties.title}\n{text}" if len(selected) > 1 else text
        )
    text = "\n\n".join(sections)
    return DocsReadView(
        document_id=document.documentId,
        title=document.title,
        text=text[:MAX_TEXT_CHARS],
        truncated=len(text) > MAX_TEXT_CHARS,
        character_count=len(text),
        tabs=[
            DocsTabView(tab_id=tab.tabProperties.tabId, title=tab.tabProperties.title)
            for tab in selected
        ],
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_document",
    display_name="Create Google Doc",
    description=(
        "Create a document, optionally with opening content. Google requires "
        "two separate writes for creation and content: a content failure may "
        "leave an empty document. Returns the id and editing link after the "
        "requested writes are acknowledged."
    ),
    input_model=CreateDocumentInput,
    effect=ToolEffect.MUTATION,
    scopes=(DOCUMENTS,),
)
async def create_document(
    payload: CreateDocumentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    created = parse_response(
        await ctx.mutate(
            "/documents",
            json=DocsCreateRequest(title=payload.title).model_dump(mode="json"),
        ),
        CREATE_RESPONSE,
    )
    if payload.body:
        request = DocsBatchRequest[DocsInsertRequest](
            requests=[
                DocsInsertRequest(
                    insertText=DocsInsertText(
                        location=DocsLocation(index=FIRST_TEXT_INDEX), text=payload.body
                    )
                )
            ]
        )
        result = parse_response(
            await ctx.mutate(
                f"/documents/{quote(created.documentId, safe='')}:batchUpdate",
                json=request.model_dump(mode="json", exclude_none=True),
            ),
            INSERT_RESPONSE,
        )
        require_identity(result, created.documentId)
    return DocsCreateView(
        document_id=created.documentId,
        title=created.title,
        web_link=f"https://docs.google.com/document/d/{quote(created.documentId, safe='')}/edit",
        body_written=bool(payload.body),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="append_text",
    display_name="Append to Google Doc",
    description=(
        "Add text to the end of the first or selected tab. Reads Google's "
        "UTF-16 end position and requires that revision when writing, so a "
        "concurrent edit cannot silently move the insertion into existing text."
    ),
    input_model=AppendTextInput,
    effect=ToolEffect.MUTATION,
    scopes=(DOCUMENTS,),
)
async def append_text(
    payload: AppendTextInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    document = await _read_document(ctx, payload.document_id)
    tab = _select_tab(_tabs(document), payload.tab_id)
    index = _end_index(tab.documentTab.body)
    if not document.revisionId:
        raise VendorToolError(
            DocsErrorCode.RESPONSE_INVALID,
            "Google Docs omitted the revision required for a safe append.",
        )
    text = f"\n{payload.text}" if payload.start_on_new_line else payload.text
    request = DocsBatchRequest[DocsInsertRequest](
        requests=[
            DocsInsertRequest(
                insertText=DocsInsertText(
                    location=DocsLocation(index=index, tabId=tab.tabProperties.tabId),
                    text=text,
                )
            )
        ],
        writeControl=DocsWriteControl(requiredRevisionId=document.revisionId),
    )
    result = parse_response(
        await ctx.mutate(
            f"/documents/{quote(payload.document_id, safe='')}:batchUpdate",
            json=request.model_dump(mode="json", exclude_none=True),
        ),
        INSERT_RESPONSE,
    )
    require_identity(result, payload.document_id)
    return DocsAppendView(
        document_id=document.documentId,
        title=document.title,
        tab_id=tab.tabProperties.tabId,
        inserted_at_index=index,
        characters_added=len(text),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="replace_text",
    display_name="Replace Text in Google Doc",
    description=(
        "Replace every occurrence of text throughout all tabs, or one selected "
        "tab, including tables and headers. Useful for filling a template. "
        "Reports Google's acknowledged occurrence count, including zero."
    ),
    input_model=ReplaceTextInput,
    effect=ToolEffect.MUTATION,
    scopes=(DOCUMENTS,),
)
async def replace_text(
    payload: ReplaceTextInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    request = DocsBatchRequest[DocsReplaceRequest](
        requests=[
            DocsReplaceRequest(
                replaceAllText=DocsReplaceText(
                    containsText=DocsContainsText(
                        text=payload.find, matchCase=payload.match_case
                    ),
                    replaceText=payload.replace_with,
                    tabsCriteria=DocsTabsCriteria(tabIds=[payload.tab_id])
                    if payload.tab_id
                    else None,
                )
            )
        ]
    )
    result = parse_response(
        await ctx.mutate(
            f"/documents/{quote(payload.document_id, safe='')}:batchUpdate",
            json=request.model_dump(mode="json", exclude_none=True),
        ),
        REPLACE_RESPONSE,
    )
    require_identity(result, payload.document_id)
    occurrences = result.replies[0].replaceAllText.occurrencesChanged
    return DocsReplaceView(
        document_id=result.documentId,
        occurrences_changed=occurrences,
        found=occurrences > 0,
    ).model_dump(mode="json")


async def _read_document(ctx: VendorToolContext, document_id: str) -> DocsDocument:
    document = parse_response(
        await ctx.read(
            f"/documents/{quote(document_id, safe='')}",
            query=DocsReadQuery().model_dump(mode="json"),
        ),
        DOCUMENT_RESPONSE,
    )
    require_identity(document, document_id)
    return document


def _tabs(document: DocsDocument) -> list[DocsTab]:
    """Preorder preserves Google's display order, including nested tabs."""
    pending = list(reversed(document.tabs))
    tabs: list[DocsTab] = []
    seen: set[str] = set()
    while pending:
        tab = pending.pop()
        if tab.tabProperties.tabId in seen:
            raise VendorToolError(
                DocsErrorCode.RESPONSE_INVALID,
                "Google Docs returned duplicate tab IDs.",
            )
        seen.add(tab.tabProperties.tabId)
        tabs.append(tab)
        pending.extend(reversed(tab.childTabs))
    return tabs


def _select_tab(tabs: list[DocsTab], tab_id: str | None) -> DocsTab:
    if tab_id is None:
        return tabs[0]
    for tab in tabs:
        if tab.tabProperties.tabId == tab_id:
            return tab
    raise VendorToolError(
        DocsErrorCode.TAB_NOT_FOUND, "The requested document tab was not found."
    )


def _flatten(body: DocsBody) -> str:
    return "\n".join(
        line for element in body.content for line in _element_lines(element)
    ).strip()


def _element_lines(element: DocsStructuralElement) -> list[str]:
    if paragraph := element.paragraph:
        text = "".join(
            run.textRun.content if run.textRun else NON_TEXT_MARKER
            for run in paragraph.elements
        ).rstrip("\n")
        style = (
            paragraph.paragraphStyle.namedStyleType
            if paragraph.paragraphStyle
            else None
        )
        prefix = (
            HEADING_PREFIX[DocsHeading(style)]
            if style is not None and style in DocsHeading
            else ""
        )
        return [f"{prefix}{text}"] if text else [""]
    if table := element.table:
        return [
            " | ".join(
                " ".join(
                    line
                    for child in cell.content
                    for line in _element_lines(child)
                    if line
                ).strip()
                for cell in row.tableCells
            )
            for row in table.tableRows
        ]
    if toc := element.tableOfContents:
        return [line for child in toc.content for line in _element_lines(child)]
    return []


def _end_index(body: DocsBody) -> int:
    """Use the final native UTF-16 boundary; never infer it from Python text length."""
    end = body.content[-1].endIndex
    if end is None or end <= FIRST_TEXT_INDEX:
        raise VendorToolError(
            DocsErrorCode.RESPONSE_INVALID,
            "Google Docs omitted the final writable boundary.",
        )
    return end - 1


__all__ = ["append_text", "create_document", "read_document", "replace_text"]
