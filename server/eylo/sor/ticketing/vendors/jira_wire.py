"""Consumed Jira Cloud v3 wire values, separate from canonical ticketing data."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
)
from eylo.sor.shared.json_values import SorJsonValue

JIRA_IDENTIFIER_MAX_LENGTH = 512
JIRA_READ_PAGE_SIZE = 100
JIRA_COMMENT_PAGE_SIZE = 200


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
