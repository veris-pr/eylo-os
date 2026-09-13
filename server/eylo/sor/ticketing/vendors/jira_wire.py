"""Consumed Jira Cloud v3 and Agile wire values, separate from canonical data."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_validator,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import (
    SorJsonValue,
    require_json_object,
    require_json_value,
)

JIRA_IDENTIFIER_MAX_LENGTH = 512
JIRA_READ_PAGE_SIZE = 100
JIRA_COMMENT_PAGE_SIZE = 200
JIRA_CUSTOM_FIELD_PREFIX = "customfield_"


def _identifier(value: object) -> object:
    """Retain native ID encoding while rejecting booleans and negative numbers."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Jira identity must be a string or nonnegative integer.")
    if isinstance(value, int) and value < 0:
        raise ValueError("Jira identity must be nonnegative.")
    if not str(value).strip() or len(str(value).strip()) > JIRA_IDENTIFIER_MAX_LENGTH:
        raise ValueError("Jira identity is empty or too long.")
    return value


JiraIdentifier = Annotated[str | int, BeforeValidator(_identifier)]


class JiraResponse(BaseModel):
    """Validate known native fields without rejecting unrelated vendor additions."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class JiraCollection[T: JiraResponse](RootModel[list[T]]):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)


class JiraSite(JiraResponse):
    """Identity is required by the adapter only for the exact configured site."""

    id: str | int | None = None
    url: str | None = None
    name: str | None = None


class JiraViewer(JiraResponse):
    displayName: str | None = None


class JiraFieldType(StrEnum):
    ARRAY = "array"
    DATE = "date"
    DATETIME = "datetime"
    NUMBER = "number"
    OPTION = "option"
    STRING = "string"
    USER = "user"


class JiraFieldSchema(JiraResponse):
    """Unknown native field types retain the existing bounded-JSON mapping."""

    type: str | None = None
    custom: str | None = None


class JiraField(JiraResponse):
    id: str | int | None = None
    name: str | None = None
    description: str | None = None
    custom: bool | None = None
    field_schema: JiraFieldSchema | None = Field(default=None, alias="schema")


class JiraProjectIdentity(JiraResponse):
    id: JiraIdentifier


class JiraProject(JiraProjectIdentity):
    key: str | None = None
    name: str
    description: SorJsonValue = Field(default=None, repr=False)


class JiraStatusCategory(JiraResponse):
    key: str | None = None
    name: str | None = None


class JiraStatus(JiraResponse):
    id: JiraIdentifier
    name: str
    statusCategory: JiraStatusCategory | None = None


class JiraAvatars(JiraResponse):
    large: str | None = Field(default=None, alias="48x48")


class JiraUser(JiraResponse):
    accountId: JiraIdentifier
    displayName: str
    active: bool
    emailAddress: str | None = Field(default=None, repr=False)
    avatarUrls: JiraAvatars | None = None


class JiraLabel(JiraResponse):
    name: str


class JiraPage[T: JiraResponse](JiraResponse):
    values: list[T]
    isLast: bool


class JiraLabelPage(JiraResponse):
    values: list[str]
    isLast: bool


class JiraOrderBy(StrEnum):
    KEY = "key"
    CREATED = "created"


class JiraRequest(BaseModel):
    """Outbound native parameters; unknown keys indicate a construction error."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", hide_input_in_errors=True
    )


class JiraPageQuery(JiraRequest):
    startAt: int = Field(ge=0)
    maxResults: int = Field(ge=1, le=JIRA_READ_PAGE_SIZE)
    orderBy: JiraOrderBy | None = None


type JiraDirectoryRecord = JiraProject | JiraStatus | JiraUser | JiraLabel


class JiraAccountReference(JiraResponse):
    accountId: JiraIdentifier | None = None


class JiraComment(JiraResponse):
    id: JiraIdentifier
    body: SorJsonValue = Field(default=None, repr=False)
    created: str
    updated: str | None = None
    author: JiraAccountReference | None = None


class JiraCommentPage(JiraResponse):
    comments: list[JiraComment]
    startAt: int = Field(ge=0)
    total: int = Field(ge=0)


class JiraCommentFields(JiraResponse):
    comment: JiraCommentPage


class JiraCommentIssue(JiraResponse):
    id: JiraIdentifier
    fields: JiraCommentFields


class JiraSearchPage[T: JiraResponse](JiraResponse):
    issues: list[T]
    isLast: bool
    nextPageToken: str | None = None


class JiraSearchRequest(JiraRequest):
    fields: list[str]
    fieldsByKeys: Literal[True]
    jql: str
    maxResults: int = Field(ge=1, le=JIRA_READ_PAGE_SIZE)
    nextPageToken: str | None = None


class JiraCommentQuery(JiraRequest):
    startAt: int = Field(ge=0)
    maxResults: int = Field(ge=1, le=JIRA_COMMENT_PAGE_SIZE)
    orderBy: Literal[JiraOrderBy.CREATED]


class JiraEntityReference(JiraResponse):
    id: JiraIdentifier | None = None
    name: str | None = None


class JiraIssueStatus(JiraEntityReference):
    statusCategory: JiraStatusCategory | None = None


class JiraCustomFields(JiraResponse):
    """Validate dynamic Jira keys without requiring unrequested fixed fields."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="allow", hide_input_in_errors=True
    )

    @model_validator(mode="before")
    @classmethod
    def validate_native_json(cls, value: object) -> object:
        return value if isinstance(value, cls) else require_json_object(value)

    def custom_field(self, key: str) -> SorJsonValue:
        """Only discovered custom fields cross this open native-key boundary."""
        if not key.startswith(JIRA_CUSTOM_FIELD_PREFIX):
            raise ValueError("Expected a Jira custom-field key.")
        return require_json_value((self.model_extra or {}).get(key))


class JiraIssueFields(JiraCustomFields):
    """Fixed native fields plus validated, discovered custom-field values."""

    summary: str
    updated: str
    created: str | None = None
    resolutiondate: str | None = None
    description: SorJsonValue = Field(default=None, repr=False)
    issuetype: JiraEntityReference | None = None
    status: JiraIssueStatus | None = None
    priority: JiraEntityReference | None = None
    project: JiraEntityReference | None = None
    parent: JiraEntityReference | None = None
    assignee: JiraAccountReference | None = None
    reporter: JiraAccountReference | None = None
    timeoriginalestimate: int | None = None
    labels: list[str] | None = None
    duedate: str | None = None


class JiraIssue(JiraResponse):
    id: JiraIdentifier
    key: str
    fields: JiraIssueFields


class JiraSprintFields(JiraCustomFields):
    updated: str


class JiraSprintIssue(JiraResponse):
    fields: JiraSprintFields


class JiraSprintState(StrEnum):
    ACTIVE = "active"
    FUTURE = "future"
    CLOSED = "closed"


class JiraLegacySprintField(StrEnum):
    ID = "id"
    NAME = "name"
    STATE = "state"
    GOAL = "goal"
    START_DATE = "startDate"
    END_DATE = "endDate"
    COMPLETE_DATE = "completeDate"
    BOARD_ID = "rapidViewId"


class JiraSprintReference(JiraResponse):
    """Embedded references may contain only identity; unknown states stay open."""

    id: JiraIdentifier
    state: str | None = None


class JiraSprint(JiraSprintReference):
    """Incomplete issue snapshots trigger an authoritative Agile Sprint lookup."""

    name: str | None = None
    goal: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    completeDate: str | None = None
    originBoardId: JiraIdentifier | None = None
    boardId: JiraIdentifier | None = None


class JiraIssueQuery(JiraRequest):
    fields: list[str]


class JiraLinkType(JiraResponse):
    id: JiraIdentifier | None = None
    name: str | None = None
    inward: str | None = None
    outward: str | None = None


class JiraLinkTypes(JiraResponse):
    issueLinkTypes: list[JiraLinkType]


class JiraIssueLink(JiraResponse):
    id: JiraIdentifier
    type: JiraLinkType
    inwardIssue: JiraEntityReference | None = None
    outwardIssue: JiraEntityReference | None = None


class JiraIssueLinkFields(JiraResponse):
    issuelinks: list[JiraIssueLink]


class JiraLinkedIssue(JiraResponse):
    id: JiraIdentifier | None = None
    fields: JiraIssueLinkFields


class JiraIdInput(JiraRequest):
    id: JiraIdentifier


class JiraLinkCreate(JiraRequest):
    inwardIssue: JiraIdInput
    outwardIssue: JiraIdInput
    type: JiraIdInput


class JiraAdfNodeKind(StrEnum):
    DOCUMENT = "doc"
    PARAGRAPH = "paragraph"
    TEXT = "text"
    HARD_BREAK = "hardBreak"
    BLOCKQUOTE = "blockquote"
    BULLET_LIST = "bulletList"
    HEADING = "heading"
    LIST_ITEM = "listItem"
    ORDERED_LIST = "orderedList"


class JiraAdfField(StrEnum):
    """Consumed field names in Atlassian's extensible document format."""

    TYPE = "type"
    TEXT = "text"
    CONTENT = "content"


class JiraAdfText(JiraRequest):
    type: Literal[JiraAdfNodeKind.TEXT] = JiraAdfNodeKind.TEXT
    text: str = Field(repr=False)


class JiraAdfParagraph(JiraRequest):
    type: Literal[JiraAdfNodeKind.PARAGRAPH] = JiraAdfNodeKind.PARAGRAPH
    content: list[JiraAdfText] = Field(repr=False)


class JiraAdfDocument(JiraRequest):
    """Only Eylo's generated plain-text ADF, not arbitrary vendor document nodes."""

    type: Literal[JiraAdfNodeKind.DOCUMENT] = JiraAdfNodeKind.DOCUMENT
    version: Literal[1] = 1
    content: list[JiraAdfParagraph] = Field(repr=False)


class JiraNameInput(JiraRequest):
    name: str


class JiraIssueWriteField(StrEnum):
    SUMMARY = "summary"
    DESCRIPTION = "description"
    ISSUE_TYPE = "issuetype"
    PRIORITY = "priority"
    PROJECT = "project"
    ESTIMATE = "timeoriginalestimate"
    LABELS = "labels"
    PARENT = "parent"
    DUE_DATE = "duedate"


class JiraWriteFields(JiraCustomFields):
    """Omitted fields stay omitted; explicit null clears an existing value."""

    summary: str | None = None
    description: JiraAdfDocument | None = Field(default=None, repr=False)
    issuetype: JiraNameInput | None = None
    priority: JiraNameInput | None = None
    project: JiraIdInput | None = None
    parent: JiraIdInput | None = None
    timeoriginalestimate: int | None = Field(default=None, ge=0)
    labels: list[str] | None = None
    duedate: str | None = None


class JiraIssueWrite(JiraRequest):
    fields: JiraWriteFields


class JiraCreatedIssue(JiraResponse):
    id: JiraIdentifier
    key: str | None = None


class JiraTransition(JiraResponse):
    id: str | None = None
    to: JiraEntityReference | None = None


class JiraTransitions(JiraResponse):
    transitions: list[JiraTransition]


class JiraTransitionRequest(JiraRequest):
    transition: JiraIdInput


class JiraAssignment(JiraRequest):
    accountId: str | None


class JiraCommentWrite(JiraRequest):
    body: JiraAdfDocument | None = Field(repr=False)


class JiraCreatedComment(JiraResponse):
    id: JiraIdentifier
    updated: str | None = None
    created: str | None = None


class JiraLabelAction(StrEnum):
    ADD = "add"
    REMOVE = "remove"


class JiraLabelAdd(JiraRequest):
    add: str


class JiraLabelRemove(JiraRequest):
    remove: str


class JiraLabelUpdates(JiraRequest):
    labels: list[JiraLabelAdd | JiraLabelRemove]


class JiraLabelRequest(JiraRequest):
    update: JiraLabelUpdates


def parse_request[T: BaseModel](value: object, model: type[T]) -> T:
    """Refuse invalid mapped native fields before making the vendor request."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_COMMAND_INVALID,
            "The Jira request contains invalid field values.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error


def parse_response[T: BaseModel](value: object, model: type[T]) -> T:
    """Malformed consumed fields become a safe, non-retryable vendor failure."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Jira returned an invalid response.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
