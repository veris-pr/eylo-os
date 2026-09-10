"""Calendly v2 wire contracts, resource identities and curated result projections."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn
from urllib.parse import urlsplit

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

API_ORIGIN = "https://api.calendly.com"
VENDOR_KEY = "calendly"
AUTHORIZATION_URL = "https://auth.calendly.com/oauth/authorize"
TOKEN_URL = "https://auth.calendly.com/oauth/token"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
MAX_REASON_LENGTH = 10000


class CalendlyScope(StrEnum):
    USERS_READ = "users:read"
    EVENT_TYPES_READ = "event_types:read"
    EVENT_TYPES_WRITE = "event_types:write"
    EVENTS_READ = "scheduled_events:read"
    EVENTS_WRITE = "scheduled_events:write"


def effective_scopes(granted: set[str]) -> set[str]:
    """Expand only documented Calendly write-to-read implications for our tools."""
    result = set(granted)
    if CalendlyScope.EVENTS_WRITE in granted:
        result.add(CalendlyScope.EVENTS_READ)
    if CalendlyScope.EVENT_TYPES_WRITE in granted:
        result.add(CalendlyScope.EVENT_TYPES_READ)
    return result


class CalendlyErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    EVENT_INVALID = "event_invalid"


class EventStatus(StrEnum):
    ACTIVE = "active"
    CANCELED = "canceled"


class EventTypeKind(StrEnum):
    SOLO = "solo"
    GROUP = "group"


class CancelerType(StrEnum):
    HOST = "host"
    INVITEE = "invitee"


class ResourceKind(StrEnum):
    USER = "users"
    EVENT = "scheduled_events"
    EVENT_TYPE = "event_types"


class EventSort(StrEnum):
    START_DESCENDING = "start_time:desc"


def resource_id(value: str, kind: ResourceKind) -> str:
    """Require the expected API resource; never reinterpret an unrelated URI."""
    parsed = urlsplit(value)
    prefix = f"/{kind.value}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.calendly.com"
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        raise ValueError("Use a Calendly API resource URI of the expected kind.")
    identifier = parsed.path[len(prefix) :]
    if re.fullmatch(r"[A-Za-z0-9_-]+", identifier) is None:
        raise ValueError("Calendly resource identifier is invalid.")
    return identifier


def event_id(value: str) -> str:
    candidate = value.strip()
    try:
        if "://" in candidate:
            return resource_id(candidate, ResourceKind.EVENT)
        if re.fullmatch(r"[A-Za-z0-9_-]+", candidate) is not None:
            return candidate
    except ValueError:
        pass
    raise VendorToolError(
        CalendlyErrorCode.EVENT_INVALID,
        "Use a Calendly event identifier or its scheduled_events API URI.",
    )


def _user_uri(value: str) -> str:
    resource_id(value, ResourceKind.USER)
    return value


def _event_uri(value: str) -> str:
    resource_id(value, ResourceKind.EVENT)
    return value


def _event_type_uri(value: str) -> str:
    resource_id(value, ResourceKind.EVENT_TYPE)
    return value


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Calendly timestamps require an explicit timezone.")
    return value


def utc_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(timestamp(value).replace("Z", "+00:00"))
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


Identifier = Annotated[str, Field(min_length=1)]
TimestampText = Annotated[str, AfterValidator(timestamp)]
UserUri = Annotated[str, AfterValidator(_user_uri)]
EventUri = Annotated[str, AfterValidator(_event_uri)]
EventTypeUri = Annotated[str, AfterValidator(_event_type_uri)]
NativeStatus = Annotated[
    EventStatus,
    BeforeValidator(
        lambda value: EventStatus(value) if isinstance(value, str) else value
    ),
]
NativeEventKind = Annotated[
    EventTypeKind,
    BeforeValidator(
        lambda value: EventTypeKind(value) if isinstance(value, str) else value
    ),
]
NativeCanceler = Annotated[
    CancelerType,
    BeforeValidator(
        lambda value: CancelerType(value) if isinstance(value, str) else value
    ),
]


class CalendlyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class CalendlyRequest(CalendlyModel):
    model_config = ConfigDict(extra="forbid")


class Resource[T](CalendlyModel):
    resource: T


class Pagination(CalendlyModel):
    count: int = Field(ge=0)
    next_page_token: Identifier | None


class Page[T](CalendlyModel):
    collection: list[T]
    pagination: Pagination


class User(CalendlyModel):
    uri: UserUri
    name: str
    email: str
    scheduling_url: str
    timezone: str


class EventType(CalendlyModel):
    uri: EventTypeUri
    name: str
    duration: int = Field(ge=1)
    scheduling_url: str
    kind: NativeEventKind
    active: bool
    description_plain: str | None = Field(default=None, repr=False)


class Location(CalendlyModel):
    # Vendor adds new conferencing types; display their native name, not a policy.
    type: Identifier
    location: str | None = None
    join_url: str | None = None


class InviteesCounter(CalendlyModel):
    active: int = Field(ge=0)


class EventMembership(CalendlyModel):
    user: UserUri
    user_email: str


class ScheduledEvent(CalendlyModel):
    uri: EventUri
    name: str | None
    status: NativeStatus
    start_time: TimestampText
    end_time: TimestampText
    location: Location | None
    invitees_counter: InviteesCounter
    event_memberships: list[EventMembership]
    created_at: TimestampText


class Answer(CalendlyModel):
    question: str
    answer: str = Field(repr=False)


class Invitee(CalendlyModel):
    event: EventUri
    name: str
    email: str
    timezone: str | None
    status: NativeStatus
    questions_and_answers: list[Answer]
    cancel_url: str | None
    reschedule_url: str | None


class Cancellation(CalendlyModel):
    canceled_by: str
    reason: str | None
    canceler_type: NativeCanceler
    created_at: TimestampText


class PageQuery(CalendlyRequest):
    count: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    page_token: Identifier | None = None


class EventTypesQuery(PageQuery):
    user: UserUri
    active: bool | None = None


class ScheduledEventsQuery(PageQuery):
    user: UserUri
    status: EventStatus
    sort: Literal[EventSort.START_DESCENDING] = EventSort.START_DESCENDING
    min_start_time: TimestampText | None = None
    max_start_time: TimestampText | None = None


class CancellationRequest(CalendlyRequest):
    reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH, repr=False)


class BookingLinkView(CalendlyModel):
    name: str
    duration_minutes: int
    booking_url: str
    kind: EventTypeKind
    active: bool
    description: str | None = Field(repr=False)


class BookingLinksView(CalendlyModel):
    booking_links: list[BookingLinkView]
    count: int
    next_page_token: str | None


class MeetingView(CalendlyModel):
    uuid: str
    name: str | None
    status: EventStatus
    start_time: str
    end_time: str
    location: str | None
    invitee_count: int
    hosts: list[str]
    created_at: str


class MeetingsView(CalendlyModel):
    meetings: list[MeetingView]
    count: int
    next_page_token: str | None


class InviteeView(CalendlyModel):
    name: str
    email: str
    timezone: str | None
    status: EventStatus
    answers: list[Answer] = Field(repr=False)
    cancel_url: str | None
    reschedule_url: str | None


class InviteesView(CalendlyModel):
    event_uuid: str
    invitees: list[InviteeView]
    count: int
    next_page_token: str | None


class CancellationView(CalendlyModel):
    event_uuid: str
    cancelled: Literal[True] = True
    cancelled_by: str
    reason: str | None = Field(repr=False)
    canceler_type: CancelerType
    cancelled_at: str
    # The cancellation acknowledgement contains no delivery receipt.
    invitee_notified: None = None


USER_RESPONSE = TypeAdapter(Resource[User])
EVENT_TYPES_RESPONSE = TypeAdapter(Page[EventType])
EVENTS_RESPONSE = TypeAdapter(Page[ScheduledEvent])
INVITEES_RESPONSE = TypeAdapter(Page[Invitee])
CANCELLATION_RESPONSE = TypeAdapter(Resource[Cancellation])


def parse_response[T](
    response: VendorResponse,
    schema: TypeAdapter[T],
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> T:
    if not response.ok:
        raise VendorToolError(
            CalendlyErrorCode.REJECTED, "Calendly rejected the request."
        )
    if response.status_code != status:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def invalid_response() -> NoReturn:
    raise VendorToolError(
        CalendlyErrorCode.RESPONSE_INVALID,
        "Calendly did not return a valid acknowledgement for the requested operation.",
    )
