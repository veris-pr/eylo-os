"""Google Docs v1 tab-aware document trees and bounded update contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_TEXT_CHARS = 20_000
FIRST_TEXT_INDEX = 1
NON_TEXT_MARKER = "[Non-text content]"


class DocsErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    TAB_NOT_FOUND = "tab_not_found"


class DocsHeading(StrEnum):
    TITLE = "TITLE"
    HEADING_1 = "HEADING_1"
    HEADING_2 = "HEADING_2"
    HEADING_3 = "HEADING_3"
    HEADING_4 = "HEADING_4"
    HEADING_5 = "HEADING_5"
    HEADING_6 = "HEADING_6"


HEADING_PREFIX = {
    DocsHeading.TITLE: "# ",
    DocsHeading.HEADING_1: "# ",
    DocsHeading.HEADING_2: "## ",
    DocsHeading.HEADING_3: "### ",
    DocsHeading.HEADING_4: "#### ",
    DocsHeading.HEADING_5: "##### ",
    DocsHeading.HEADING_6: "###### ",
}


class DocsModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class DocsRequest(DocsModel):
    model_config = ConfigDict(extra="forbid")


class DocsTextRun(DocsModel):
    content: str = Field(repr=False)


class DocsParagraphElement(DocsModel):
    textRun: DocsTextRun | None = None


class DocsParagraphStyle(DocsModel):
    namedStyleType: str | None = None


class DocsParagraph(DocsModel):
    elements: list[DocsParagraphElement]
    paragraphStyle: DocsParagraphStyle | None = None


class DocsSectionBreak(DocsModel):
    """Structural break; layout is not interpreted by this text-reading tool."""


class DocsTableCell(DocsModel):
    content: list[DocsStructuralElement]


class DocsTableRow(DocsModel):
    tableCells: list[DocsTableCell]


class DocsTable(DocsModel):
    tableRows: list[DocsTableRow]


class DocsTableOfContents(DocsModel):
    content: list[DocsStructuralElement]


class DocsStructuralElement(DocsModel):
    endIndex: int | None = Field(default=None, ge=0)
    paragraph: DocsParagraph | None = None
    table: DocsTable | None = None
    tableOfContents: DocsTableOfContents | None = None
    sectionBreak: DocsSectionBreak | None = None

    @model_validator(mode="after")
    def one_element_kind(self) -> Self:
        if (
            sum(
                value is not None
                for value in (
                    self.paragraph,
                    self.table,
                    self.tableOfContents,
                    self.sectionBreak,
                )
            )
            != 1
        ):
            raise ValueError("Exactly one document structural element is required.")
        return self


class DocsBody(DocsModel):
    content: list[DocsStructuralElement] = Field(min_length=1)


class DocsTabProperties(DocsModel):
    tabId: str = Field(min_length=1)
    title: str


class DocsDocumentTab(DocsModel):
    body: DocsBody


class DocsTab(DocsModel):
    tabProperties: DocsTabProperties
    documentTab: DocsDocumentTab
    childTabs: list[DocsTab] = Field(default_factory=list)


class DocsResource(DocsModel):
    documentId: str = Field(min_length=1)


class DocsCreatedDocument(DocsResource):
    title: str


class DocsDocument(DocsCreatedDocument):
    tabs: list[DocsTab] = Field(min_length=1)
    revisionId: str | None = None


class DocsReadQuery(DocsRequest):
    includeTabsContent: Literal[True] = True


class DocsCreateRequest(DocsRequest):
    title: str = Field(min_length=1)


class DocsLocation(DocsRequest):
    index: int = Field(ge=FIRST_TEXT_INDEX)
    tabId: str | None = None


class DocsInsertText(DocsRequest):
    location: DocsLocation
    text: str = Field(min_length=1, repr=False)


class DocsInsertRequest(DocsRequest):
    insertText: DocsInsertText


class DocsContainsText(DocsRequest):
    text: str = Field(min_length=1, repr=False)
    matchCase: bool


class DocsTabsCriteria(DocsRequest):
    tabIds: list[str] = Field(min_length=1)


class DocsReplaceText(DocsRequest):
    containsText: DocsContainsText
    replaceText: str = Field(repr=False)
    tabsCriteria: DocsTabsCriteria | None = None


class DocsReplaceRequest(DocsRequest):
    replaceAllText: DocsReplaceText


class DocsWriteControl(DocsRequest):
    requiredRevisionId: str = Field(min_length=1)


class DocsBatchRequest[T](DocsRequest):
    requests: list[T] = Field(min_length=1, max_length=1)
    writeControl: DocsWriteControl | None = None


class DocsEmptyReply(DocsRequest):
    """InsertText has an empty reply object in the corresponding reply slot."""


class DocsReplaceResult(DocsModel):
    # Google JSON encoding can omit a zero-valued scalar.
    occurrencesChanged: int = Field(default=0, ge=0)


class DocsReplaceReply(DocsRequest):
    replaceAllText: DocsReplaceResult


class DocsBatchResponse[T](DocsResource):
    replies: list[T] = Field(min_length=1, max_length=1)


class DocsApiError(DocsModel):
    code: int | None = None
    message: str | None = Field(default=None, repr=False)


class DocsErrorEnvelope(DocsModel):
    error: DocsApiError | None = None


class DocsTabView(DocsModel):
    tab_id: str
    title: str


class DocsReadView(DocsModel):
    document_id: str
    title: str
    text: str = Field(repr=False)
    truncated: bool
    character_count: int
    tabs: list[DocsTabView]


class DocsCreateView(DocsModel):
    document_id: str
    title: str
    web_link: str
    body_written: bool


class DocsAppendView(DocsModel):
    document_id: str
    title: str
    tab_id: str
    inserted_at_index: int
    characters_added: int


class DocsReplaceView(DocsModel):
    document_id: str
    occurrences_changed: int
    found: bool


DOCUMENT_RESPONSE = TypeAdapter(DocsDocument)
CREATE_RESPONSE = TypeAdapter(DocsCreatedDocument)
INSERT_RESPONSE = TypeAdapter(DocsBatchResponse[DocsEmptyReply])
REPLACE_RESPONSE = TypeAdapter(DocsBatchResponse[DocsReplaceReply])


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            DocsErrorCode.REJECTED, "Google Docs rejected the request."
        )
    try:
        if DocsErrorEnvelope.model_validate(response.data).error is not None:
            raise VendorToolError(
                DocsErrorCode.REJECTED, "Google Docs rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            DocsErrorCode.RESPONSE_INVALID,
            "Google Docs returned an invalid operation response.",
        ) from None


def require_identity(document: DocsResource, expected_id: str) -> None:
    if document.documentId != expected_id:
        raise VendorToolError(
            DocsErrorCode.RESPONSE_INVALID, "Google Docs returned a different document."
        )
