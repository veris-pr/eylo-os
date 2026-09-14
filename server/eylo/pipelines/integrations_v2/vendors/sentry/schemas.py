"""Sentry native issue/event contracts and validated cursor metadata."""

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
    StrictInt,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_FRAMES = 20
MAX_BODY_CHARS = 4_000
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
MAX_CURSOR_CHARS = 4_096
API_ORIGIN = "sentry.io"
API_ROOT = "/api/0"
ALL_PROJECTS = "-1"


class SentryErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"


class IssueStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class IssueFilter(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    ALL = "all"


class IssueLevel(StrEnum):
    FATAL = "fatal"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class EntryType(StrEnum):
    EXCEPTION = "exception"


class LinkParameter(StrEnum):
    RELATION = "rel"
    RESULTS = "results"
    CURSOR = "cursor"


class LinkRelation(StrEnum):
    NEXT = "next"


class LinkResults(StrEnum):
    PRESENT = "true"
    ABSENT = "false"


class StatisticsPeriod(StrEnum):
    FORTNIGHT = "14d"


FILTER_QUERIES = {
    IssueFilter.UNRESOLVED: "is:unresolved",
    IssueFilter.RESOLVED: "is:resolved",
    IssueFilter.IGNORED: "is:ignored",
    IssueFilter.ALL: "",
}


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Sentry timestamps require an explicit timezone.")
    return value


def event_count(value: object) -> object:
    # Sentry serializes event counts as decimal strings, not JSON numbers.
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    return value


def context_pair(value: object) -> object:
    # Native JSON source-context rows are [line number, source text].
    return tuple(value) if isinstance(value, list) else value


IssueId = Annotated[str, Field(pattern=r"^[0-9]+$")]
Slug = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]
Cursor = Annotated[
    str,
    Field(min_length=1, max_length=MAX_CURSOR_CHARS, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]
Timestamp = Annotated[str, AfterValidator(timestamp)]
EventCount = Annotated[int, Field(ge=0), BeforeValidator(event_count)]
NativeStatus = Annotated[
    IssueStatus,
    BeforeValidator(
        lambda value: IssueStatus(value) if isinstance(value, str) else value
    ),
]
NativeLevel = Annotated[
    IssueLevel,
    BeforeValidator(
        lambda value: IssueLevel(value) if isinstance(value, str) else value
    ),
]
ContextPair = Annotated[tuple[StrictInt | None, str], BeforeValidator(context_pair)]


class SentryModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class SentryRequest(SentryModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Metadata(SentryModel):
    type: str | None = None
    value: str | None = Field(default=None, repr=False)


class Project(SentryModel):
    id: IssueId
    slug: Slug
    name: str


class Issue(SentryModel):
    id: IssueId
    title: str
    culprit: str | None = None
    metadata: Metadata
    status: NativeStatus
    level: NativeLevel
    count: EventCount
    user_count: int = Field(alias="userCount", ge=0)
    first_seen: Timestamp = Field(alias="firstSeen")
    last_seen: Timestamp = Field(alias="lastSeen")
    permalink: str
    project: Project | None = None


class Frame(SentryModel):
    function: str | None = None
    filename: str | None = None
    line_no: int | None = Field(default=None, alias="lineNo", ge=0)
    in_app: bool | None = Field(default=None, alias="inApp")
    context: list[ContextPair] | None = Field(default=None, repr=False)


class StackTrace(SentryModel):
    frames: list[Frame]


class ExceptionValue(SentryModel):
    type: str | None = None
    value: str | None = Field(default=None, repr=False)
    stacktrace: StackTrace | None = None


class ExceptionData(SentryModel):
    values: list[ExceptionValue]


class ExceptionEntry(SentryModel):
    type: Literal[EntryType.EXCEPTION]
    data: ExceptionData


class OtherEntry(SentryModel):
    # Other native entry bodies are not consumed by this tool; discard them.
    type: str = Field(min_length=1)

    @field_validator("type")
    @classmethod
    def not_exception(cls, value: str) -> str:
        if value == EntryType.EXCEPTION:
            raise ValueError("Exception entries must validate their native body.")
        return value


class Tag(SentryModel):
    key: str
    value: str


class Event(SentryModel):
    id: str = Field(min_length=1)
    group_id: IssueId = Field(alias="groupID")
    date_created: Timestamp = Field(alias="dateCreated")
    entries: list[ExceptionEntry | OtherEntry]
    tags: list[Tag]


class IssuesQuery(SentryRequest):
    project: Slug
    query: str
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    group_stats_period: StatisticsPeriod = Field(
        default=StatisticsPeriod.FORTNIGHT, alias="groupStatsPeriod"
    )
    cursor: Cursor | None = None


class ChangeIssueRequest(SentryRequest):
    status: IssueStatus


class IssueView(SentryModel):
    organization: Slug
    id: str
    title: str
    culprit: str | None
    type: str | None
    value: str | None = Field(repr=False)
    status: IssueStatus
    level: IssueLevel
    event_count: int
    users_affected: int
    first_seen: str
    last_seen: str
    web_link: str


class IssuesView(SentryModel):
    organization: Slug
    project: str
    issues: list[IssueView]
    count: int
    next_cursor: str | None


class SourceLine(SentryModel):
    line: int | None
    text: str = Field(repr=False)


class FrameView(SentryModel):
    function: str | None
    file: str | None
    line: int | None
    in_app: bool | None
    context: list[SourceLine] | None = Field(repr=False)


class ExceptionView(SentryModel):
    type: str | None
    value: str | None = Field(repr=False)


class IssueDetail(IssueView):
    last_event_at: str | None = None
    stack_trace: list[FrameView] | None = None
    exception: ExceptionView | None = None
    tags: dict[str, str] | None = None


class ChangeIssueView(SentryModel):
    organization: Slug
    issue_id: str
    status: IssueStatus
    web_link: str


ISSUE_RESPONSE = TypeAdapter(Issue)
ISSUES_RESPONSE = TypeAdapter(list[Issue])
EVENT_RESPONSE = TypeAdapter(Event)
CURSOR_VALUE = TypeAdapter(Cursor)

_LINK = re.compile(r'<([^<>]+)>((?:\s*;\s*[A-Za-z_-]+\s*=\s*(?:"[^"]*"|[^;,\s]+))*)\s*')
_PARAMETER = re.compile(r';\s*([A-Za-z_-]+)\s*=\s*(?:"([^"]*)"|([^;,\s]+))')


def invalid_response() -> NoReturn:
    raise VendorToolError(
        SentryErrorCode.RESPONSE_INVALID,
        "Sentry returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(SentryErrorCode.REJECTED, "Sentry rejected the request.")
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def next_cursor(
    response: VendorResponse, *, path: str, previous: str | None
) -> str | None:
    """Extract a token only; never follow a vendor-supplied URL or forward its headers."""
    found = False
    continuation = None
    for header in response.link_headers:
        for part in re.split(r",\s*(?=<)", header):
            match = _LINK.fullmatch(part.strip())
            if match is None:
                raise VendorToolError(
                    SentryErrorCode.RESPONSE_INVALID,
                    "Sentry returned malformed pagination metadata.",
                )
            parameters: dict[str, str] = {}
            for parameter in _PARAMETER.finditer(match.group(2)):
                name = parameter.group(1).lower()
                if name in parameters:
                    invalid_response()
                parameters[name] = (
                    parameter.group(2)
                    if parameter.group(2) is not None
                    else parameter.group(3)
                )
            if parameters.get(LinkParameter.RELATION) != LinkRelation.NEXT:
                continue
            if found:
                invalid_response()
            found = True
            try:
                target = urlsplit(match.group(1))
            except ValueError:
                raise VendorToolError(
                    SentryErrorCode.RESPONSE_INVALID,
                    "Sentry returned a malformed pagination URL.",
                ) from None
            if (
                target.scheme != "https"
                or target.netloc != API_ORIGIN
                or target.path != API_ROOT + path
                or target.fragment
            ):
                invalid_response()
            result = parameters.get(LinkParameter.RESULTS)
            if result == LinkResults.ABSENT:
                continue
            if result != LinkResults.PRESENT:
                invalid_response()
            url_tokens = parse_qs(target.query).get(LinkParameter.CURSOR, [])
            token = parameters.get(LinkParameter.CURSOR)
            if len(url_tokens) > 1 or (
                token is not None and url_tokens and token != url_tokens[0]
            ):
                invalid_response()
            token = (
                token if token is not None else (url_tokens[0] if url_tokens else None)
            )
            try:
                continuation = CURSOR_VALUE.validate_python(token, strict=True)
            except ValidationError:
                invalid_response()
            if continuation == previous:
                invalid_response()
    if not found:
        invalid_response()
    return continuation
