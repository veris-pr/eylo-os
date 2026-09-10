"""Calendar v3 resources, timed-event requests and validated availability intervals."""

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

PRIMARY = "primary"
MAX_CALENDAR_PAGE_SIZE = 250
MAX_CALENDAR_LOOKUP_PAGES = 4
MAX_EVENT_PAGE_SIZE = 100
DEFAULT_EVENT_PAGE_SIZE = 25
MAX_FREE_BUSY_CALENDARS = 20
DEFAULT_DURATION_MINUTES = 30
MAX_DURATION_MINUTES = 1440
MIN_FREE_SLOT_MINUTES = 5
SECONDS_PER_MINUTE = 60


class CalendarErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    CALENDAR_NOT_FOUND = "calendar_not_found"
    CALENDAR_AMBIGUOUS = "calendar_ambiguous"
    LOOKUP_INCOMPLETE = "calendar_lookup_incomplete"
    TIME_INVALID = "time_invalid"
    EVENT_NOT_TIMED = "event_not_timed"
    AVAILABILITY_UNAVAILABLE = "availability_unavailable"


class EventStatus(StrEnum):
    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    CANCELLED = "cancelled"


class AttendeeResponse(StrEnum):
    NEEDS_ACTION = "needsAction"
    DECLINED = "declined"
    TENTATIVE = "tentative"
    ACCEPTED = "accepted"


class AccessRole(StrEnum):
    NONE = "none"
    FREE_BUSY_READER = "freeBusyReader"
    READER = "reader"
    WRITER = "writer"
    OWNER = "owner"


class EventOrder(StrEnum):
    START_TIME = "startTime"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Calendar range timestamps require an explicit timezone.")
    return value


def calendar_date(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Use YYYY-MM-DD for an all-day date.")
    return value


def timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Use an installed IANA timezone name.") from None
    return value


def moment(value: str, zone_name: str | None = None) -> datetime:
    """Resolve local timestamps only with a zone; require offsets at DST ambiguity."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value:
        raise ValueError("Use a timestamp, not an all-day date.")
    zone = ZoneInfo(timezone_name(zone_name)) if zone_name is not None else None
    if parsed.tzinfo is not None:
        return parsed.astimezone(zone) if zone is not None else parsed
    if zone is None:
        raise ValueError("Supply a timestamp offset or an IANA timezone.")
    first = parsed.replace(tzinfo=zone, fold=0)
    second = parsed.replace(tzinfo=zone, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed
    ):
        raise ValueError(
            "This local time is ambiguous or nonexistent; supply an offset."
        )
    return first


def input_moment(value: str, zone_name: str | None = None) -> datetime:
    try:
        return moment(value, zone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise VendorToolError(
            CalendarErrorCode.TIME_INVALID,
            "Use an ISO timestamp with an offset, or an unambiguous time in an IANA timezone.",
        ) from None


Identifier = Annotated[str, Field(min_length=1)]
TimestampText = Annotated[str, AfterValidator(timestamp)]
DateText = Annotated[str, AfterValidator(calendar_date)]
TimezoneName = Annotated[str, AfterValidator(timezone_name)]
NativeStatus = Annotated[
    EventStatus, BeforeValidator(lambda v: EventStatus(v) if isinstance(v, str) else v)
]
NativeAttendeeResponse = Annotated[
    AttendeeResponse,
    BeforeValidator(lambda v: AttendeeResponse(v) if isinstance(v, str) else v),
]
NativeAccessRole = Annotated[
    AccessRole, BeforeValidator(lambda v: AccessRole(v) if isinstance(v, str) else v)
]


class CalendarModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class CalendarRequest(CalendarModel):
    model_config = ConfigDict(extra="forbid")


class CalendarEntry(CalendarModel):
    id: Identifier
    summary: str
    timeZone: TimezoneName
    primary: bool = False
    accessRole: NativeAccessRole


class CalendarPage(CalendarModel):
    kind: Literal["calendar#calendarList"]
    items: list[CalendarEntry] = Field(default_factory=list)
    nextPageToken: Identifier | None = None


class EventTime(CalendarModel):
    date: DateText | None = None
    dateTime: str | None = None
    timeZone: TimezoneName | None = None

    @model_validator(mode="after")
    def exclusive_time(self) -> Self:
        if (self.date is None) == (self.dateTime is None):
            raise ValueError("An event time must have exactly one date or dateTime.")
        if self.dateTime is not None:
            moment(self.dateTime, self.timeZone)
        return self

    def timed(self) -> datetime:
        if self.dateTime is None:
            raise VendorToolError(
                CalendarErrorCode.EVENT_NOT_TIMED,
                "This tool shifts timed events, not all-day events.",
            )
        return moment(self.dateTime, self.timeZone)


class Attendee(CalendarModel):
    email: Identifier
    responseStatus: NativeAttendeeResponse | None = None


class Organizer(CalendarModel):
    email: str | None = None


class Event(CalendarModel):
    kind: Literal["calendar#event"]
    id: Identifier
    status: NativeStatus
    summary: str | None = None
    description: str | None = Field(default=None, repr=False)
    location: str | None = None
    start: EventTime | None = None
    end: EventTime | None = None
    organizer: Organizer | None = None
    attendees: list[Attendee] = Field(default_factory=list)
    htmlLink: str | None = None

    @model_validator(mode="after")
    def active_times(self) -> Self:
        if self.status is not EventStatus.CANCELLED:
            if self.start is None or self.end is None:
                raise ValueError("An active event must supply start and end.")
            if (self.start.date is None) != (self.end.date is None):
                raise ValueError("Start and end must both be timed or all-day.")
        return self


class EventsPage(CalendarModel):
    kind: Literal["calendar#events"]
    items: list[Event] = Field(default_factory=list)
    nextPageToken: Identifier | None = None


class CalendarListQuery(CalendarRequest):
    maxResults: int = MAX_CALENDAR_PAGE_SIZE
    pageToken: Identifier | None = None


class EventsQuery(CalendarRequest):
    maxResults: int = Field(ge=1, le=MAX_EVENT_PAGE_SIZE)
    singleEvents: Literal[True] = True
    orderBy: Literal[EventOrder.START_TIME] = EventOrder.START_TIME
    timeMin: TimestampText | None = None
    timeMax: TimestampText | None = None
    q: str | None = None
    pageToken: Identifier | None = None


class TimedEventRequest(CalendarRequest):
    dateTime: TimestampText
    timeZone: TimezoneName | None = None


class EventShift(CalendarRequest):
    start: TimedEventRequest
    end: TimedEventRequest


class AttendeeRequest(CalendarRequest):
    email: Identifier


class EventCreate(EventShift):
    summary: Identifier
    description: str | None = Field(default=None, repr=False)
    location: str | None = None
    attendees: list[AttendeeRequest] | None = None


class CalendarReference(CalendarRequest):
    id: Identifier


class FreeBusyRequest(CalendarRequest):
    timeMin: TimestampText
    timeMax: TimestampText
    items: list[CalendarReference] = Field(
        min_length=1, max_length=MAX_FREE_BUSY_CALENDARS
    )


class BusyBlock(CalendarModel):
    start: TimestampText
    end: TimestampText

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if moment(self.end) <= moment(self.start):
            raise ValueError("Busy interval must have positive duration.")
        return self


class FreeBusyError(CalendarModel):
    domain: str
    # Google explicitly permits new reasons; every reason makes this result unusable.
    reason: Identifier


class CalendarBusy(CalendarModel):
    busy: list[BusyBlock] | None = None
    errors: list[FreeBusyError] = Field(default_factory=list)


class FreeBusyResult(CalendarModel):
    kind: Literal["calendar#freeBusy"]
    timeMin: TimestampText
    timeMax: TimestampText
    calendars: dict[str, CalendarBusy]


class CalendarView(CalendarModel):
    id: str
    name: str
    timezone: str
    primary: bool
    access_role: AccessRole


class CalendarsView(CalendarModel):
    calendars: list[CalendarView]
    count: int


class AttendeeView(CalendarModel):
    email: str
    response: AttendeeResponse | None


class EventView(CalendarModel):
    id: str
    summary: str | None
    description: str | None = Field(repr=False)
    location: str | None
    start: str | None
    end: str | None
    timezone: str | None
    organizer: str | None
    attendees: list[AttendeeView]
    html_link: str | None
    status: EventStatus


class EventsView(CalendarModel):
    calendar_id: str
    events: list[EventView]
    count: int
    next_page_token: str | None


class CancelledView(CalendarModel):
    event_id: str
    calendar_id: str
    cancelled: Literal[True] = True


class FreeSlot(CalendarModel):
    start: str
    end: str
    minutes: int


class FreeSlotsView(CalendarModel):
    calendars_checked: list[str]
    free_slots: list[FreeSlot]
    count: int


CALENDARS_RESPONSE = TypeAdapter(CalendarPage)
EVENT_RESPONSE = TypeAdapter(Event)
EVENTS_RESPONSE = TypeAdapter(EventsPage)
FREE_BUSY_RESPONSE = TypeAdapter(FreeBusyResult)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        CalendarErrorCode.RESPONSE_INVALID,
        "Google Calendar did not confirm the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            CalendarErrorCode.REJECTED, "Google Calendar rejected the request."
        )
    if response.status_code not in {HTTPStatus.OK, HTTPStatus.CREATED}:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def event_view(event: Event) -> EventView:
    return EventView(
        id=event.id,
        summary=event.summary,
        description=event.description,
        location=event.location,
        start=(event.start.dateTime or event.start.date) if event.start else None,
        end=(event.end.dateTime or event.end.date) if event.end else None,
        timezone=event.start.timeZone if event.start else None,
        organizer=event.organizer.email if event.organizer else None,
        attendees=[
            AttendeeView(email=a.email, response=a.responseStatus)
            for a in event.attendees
        ],
        html_link=event.htmlLink,
        status=event.status,
    )


def shift_request(
    start: datetime, duration: timedelta, zone_name: str | None
) -> EventShift:
    end = (start.astimezone(UTC) + duration).astimezone(start.tzinfo)
    return EventShift(
        start=TimedEventRequest(dateTime=start.isoformat(), timeZone=zone_name),
        end=TimedEventRequest(dateTime=end.isoformat(), timeZone=zone_name),
    )
