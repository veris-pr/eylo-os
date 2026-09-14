"""Curated Calendar operations with complete name resolution and fail-closed availability."""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue, StrictInt, model_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import CALENDAR, CALENDAR_EVENTS, vendor
from .schemas import (
    CALENDARS_RESPONSE,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_EVENT_PAGE_SIZE,
    EVENTS_RESPONSE,
    EVENT_RESPONSE,
    FREE_BUSY_RESPONSE,
    MAX_CALENDAR_LOOKUP_PAGES,
    MAX_DURATION_MINUTES,
    MAX_EVENT_PAGE_SIZE,
    MAX_FREE_BUSY_CALENDARS,
    MIN_FREE_SLOT_MINUTES,
    PRIMARY,
    SECONDS_PER_MINUTE,
    AttendeeRequest,
    CalendarEntry,
    CalendarErrorCode,
    CalendarListQuery,
    CalendarReference,
    CalendarView,
    CalendarsView,
    CancelledView,
    Event,
    EventCreate,
    EventShift,
    EventStatus,
    EventsQuery,
    EventsView,
    FreeBusyRequest,
    FreeSlot,
    FreeSlotsView,
    Identifier,
    TimestampText,
    TimezoneName,
    event_view,
    input_moment,
    invalid_response,
    moment,
    parse_response,
    shift_request,
)


class ListEventsInput(BaseModel):
    calendar: Identifier = Field(
        default=PRIMARY,
        description="Calendar id or name; primary is the account's primary calendar.",
    )
    time_min: TimestampText | None = Field(
        default=None,
        description="Timezone-qualified exclusive lower bound on event end time.",
    )
    time_max: TimestampText | None = Field(
        default=None,
        description="Timezone-qualified exclusive upper bound on event start time.",
    )
    query: str | None = Field(default=None, description="Free text search.")
    limit: StrictInt = Field(
        default=DEFAULT_EVENT_PAGE_SIZE, ge=1, le=MAX_EVENT_PAGE_SIZE
    )
    page_token: Identifier | None = Field(
        default=None, description="Continue with the same calendar and filters."
    )

    @model_validator(mode="after")
    def ordered_window(self) -> "ListEventsInput":
        if (
            self.time_min is not None
            and self.time_max is not None
            and moment(self.time_max) <= moment(self.time_min)
        ):
            raise ValueError("time_max must be after time_min.")
        return self


class CreateEventInput(BaseModel):
    summary: Identifier = Field(description="Event title.")
    start: Identifier = Field(
        description="ISO timestamp with offset, or local time with an explicit timezone."
    )
    duration_minutes: StrictInt = Field(
        default=DEFAULT_DURATION_MINUTES, ge=1, le=MAX_DURATION_MINUTES
    )
    calendar: Identifier = Field(default=PRIMARY, description="Calendar id or name.")
    timezone: TimezoneName | None = Field(
        default=None, description="IANA timezone such as Europe/London."
    )
    description: str | None = None
    location: str | None = None
    attendee_emails: list[Identifier] | None = Field(
        default=None, description="Email addresses to invite."
    )


class RescheduleEventInput(BaseModel):
    event_id: Identifier
    new_start: Identifier = Field(
        description="ISO timestamp; supply an offset if the existing event has no timezone."
    )
    calendar: Identifier = PRIMARY
    duration_minutes: StrictInt | None = Field(
        default=None,
        ge=1,
        le=MAX_DURATION_MINUTES,
        description="Omit to preserve the exact existing duration.",
    )


class CancelEventInput(BaseModel):
    event_id: Identifier
    calendar: Identifier = PRIMARY


class FindFreeTimeInput(BaseModel):
    time_min: TimestampText = Field(description="Timezone-qualified window start.")
    time_max: TimestampText = Field(description="Timezone-qualified window end.")
    calendars: list[Identifier] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_FREE_BUSY_CALENDARS,
        description="Calendar ids or names; omit to use primary. Calendar groups are not supported.",
    )
    minimum_minutes: StrictInt = Field(
        default=DEFAULT_DURATION_MINUTES,
        ge=MIN_FREE_SLOT_MINUTES,
        le=MAX_DURATION_MINUTES,
    )

    @model_validator(mode="after")
    def ordered_window(self) -> "FindFreeTimeInput":
        if moment(self.time_max) <= moment(self.time_min):
            raise ValueError("time_max must be after time_min.")
        return self


class ListCalendarsInput(BaseModel):
    query: str | None = Field(default=None, description="Filter on calendar name.")


@curated_tool(
    vendor=vendor.vendor,
    name="list_calendars",
    display_name="List Google Calendars",
    description=(
        "List calendars this account can see with ids, names and timezones. "
        "Name lookup is bounded and refuses an incomplete catalog instead of choosing silently."
    ),
    input_model=ListCalendarsInput,
    effect=ToolEffect.READ,
    scopes=(CALENDAR,),
)
async def list_calendars(
    payload: ListCalendarsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    entries = await _calendar_entries(ctx)
    needle = (payload.query or "").strip().casefold()
    matched = [
        entry for entry in entries if not needle or needle in entry.summary.casefold()
    ]
    return CalendarsView(
        calendars=[
            CalendarView(
                id=e.id,
                name=e.summary,
                timezone=e.timeZone,
                primary=e.primary,
                access_role=e.accessRole,
            )
            for e in matched
        ],
        count=len(matched),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_events",
    display_name="List Calendar Events",
    description=(
        "List calendar events, expanding recurrences and ordering by start time. "
        "time_min excludes events ending at or before the lower bound; time_max "
        "excludes events starting at or after the upper bound. Pass next_page_token "
        "as page_token with unchanged calendar and filters to continue."
    ),
    input_model=ListEventsInput,
    effect=ToolEffect.READ,
    scopes=(CALENDAR,),
)
async def list_events(
    payload: ListEventsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    calendar_id = (await _resolve_calendars(ctx, [payload.calendar]))[0]
    query = EventsQuery(
        maxResults=payload.limit,
        timeMin=payload.time_min,
        timeMax=payload.time_max,
        q=payload.query,
        pageToken=payload.page_token,
    )
    response = await ctx.read(
        _events_path(calendar_id),
        query=query.model_dump(mode="json", exclude_none=True),
    )
    page = parse_response(response, EVENTS_RESPONSE)
    return EventsView(
        calendar_id=calendar_id,
        events=[event_view(event) for event in page.items],
        count=len(page.items),
        next_page_token=page.nextPageToken,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_event",
    display_name="Create Calendar Event",
    description=(
        "Create a timed calendar event from a start time and duration in minutes. "
        "Supply an offset or an explicit IANA timezone; ambiguous daylight-saving "
        "times require an offset. Attendees are email addresses. Notification "
        "delivery is governed by Google; this result is not a delivery receipt."
    ),
    input_model=CreateEventInput,
    effect=ToolEffect.MUTATION,
    scopes=(CALENDAR_EVENTS, CALENDAR),
)
async def create_event(
    payload: CreateEventInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    start = input_moment(payload.start, payload.timezone)
    shift = shift_request(
        start, timedelta(minutes=payload.duration_minutes), payload.timezone
    )
    body = EventCreate(
        start=shift.start,
        end=shift.end,
        summary=payload.summary,
        description=payload.description,
        location=payload.location,
        attendees=[AttendeeRequest(email=email) for email in payload.attendee_emails]
        if payload.attendee_emails is not None
        else None,
    )
    calendar_id = (await _resolve_calendars(ctx, [payload.calendar]))[0]
    response = await ctx.mutate(
        _events_path(calendar_id), json=body.model_dump(mode="json", exclude_none=True)
    )
    event = parse_response(response, EVENT_RESPONSE)
    _validate_shift(event, shift)
    if event.summary != payload.summary:
        invalid_response()
    return event_view(event).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="reschedule_event",
    display_name="Reschedule Calendar Event",
    description=(
        "Move an existing timed event, preserving its exact duration unless a new "
        "duration is supplied. All-day and cancelled events are refused. Reads current "
        "times then patches them; this is not an atomic read/write transaction."
    ),
    input_model=RescheduleEventInput,
    effect=ToolEffect.MUTATION,
    scopes=(CALENDAR_EVENTS, CALENDAR),
)
async def reschedule_event(
    payload: RescheduleEventInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    calendar_id = (await _resolve_calendars(ctx, [payload.calendar]))[0]
    path = _events_path(calendar_id, payload.event_id)
    current = parse_response(await ctx.read(path), EVENT_RESPONSE)
    if current.id != payload.event_id:
        invalid_response()
    if (
        current.status is EventStatus.CANCELLED
        or current.start is None
        or current.end is None
    ):
        raise VendorToolError(
            CalendarErrorCode.EVENT_NOT_TIMED,
            "This event has no active times to shift.",
        )
    existing_start = current.start.timed().astimezone(UTC)
    existing_end = current.end.timed().astimezone(UTC)
    duration = (
        timedelta(minutes=payload.duration_minutes)
        if payload.duration_minutes is not None
        else existing_end - existing_start
    )
    if duration <= timedelta(0):
        invalid_response()
    start = input_moment(payload.new_start, current.start.timeZone)
    body = shift_request(start, duration, current.start.timeZone)
    response = await ctx.mutate(
        path, method="PATCH", json=body.model_dump(mode="json", exclude_none=True)
    )
    event = parse_response(response, EVENT_RESPONSE)
    if event.id != payload.event_id:
        invalid_response()
    _validate_shift(event, body)
    return event_view(event).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="cancel_event",
    display_name="Cancel Calendar Event",
    description=(
        "Cancel and remove an event from a calendar. Confirms the deletion response; "
        "does not confirm attendee notification delivery. Missing/already-deleted "
        "events may be rejected by Google."
    ),
    input_model=CancelEventInput,
    effect=ToolEffect.MUTATION,
    scopes=(CALENDAR_EVENTS, CALENDAR),
)
async def cancel_event(
    payload: CancelEventInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    calendar_id = (await _resolve_calendars(ctx, [payload.calendar]))[0]
    response = await ctx.mutate(
        _events_path(calendar_id, payload.event_id), method="DELETE"
    )
    if not response.ok:
        raise VendorToolError(
            CalendarErrorCode.REJECTED, "Google Calendar rejected deletion."
        )
    if response.status_code not in {
        HTTPStatus.OK,
        HTTPStatus.NO_CONTENT,
    } or response.data not in (None, {}):
        invalid_response()
    return CancelledView(event_id=payload.event_id, calendar_id=calendar_id).model_dump(
        mode="json"
    )


@curated_tool(
    vendor=vendor.vendor,
    name="find_free_time",
    display_name="Find Free Time",
    description=(
        "Find common free gaps across calendars in a timezone-qualified window. "
        "Merges busy blocks and filters by minimum duration. If any requested calendar "
        "is missing, inaccessible or returns an error, refuses availability rather than guessing."
    ),
    input_model=FindFreeTimeInput,
    effect=ToolEffect.READ,
    scopes=(CALENDAR,),
)
async def find_free_time(
    payload: FindFreeTimeInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    calendar_ids = await _resolve_calendars(ctx, payload.calendars or [PRIMARY])
    window_start, window_end = moment(payload.time_min), moment(payload.time_max)
    body = FreeBusyRequest(
        timeMin=payload.time_min,
        timeMax=payload.time_max,
        items=[CalendarReference(id=identifier) for identifier in calendar_ids],
    )
    response = await ctx.read(
        "/freeBusy", method="POST", json=body.model_dump(mode="json")
    )
    result = parse_response(response, FREE_BUSY_RESPONSE)
    if moment(result.timeMin) != window_start or moment(result.timeMax) != window_end:
        invalid_response()
    busy: list[tuple[datetime, datetime]] = []
    for identifier in calendar_ids:
        entry = result.calendars.get(identifier)
        if entry is None or entry.errors or entry.busy is None:
            raise VendorToolError(
                CalendarErrorCode.AVAILABILITY_UNAVAILABLE,
                "At least one requested calendar could not be checked; no free-time conclusion is available.",
            )
        busy.extend((moment(block.start), moment(block.end)) for block in entry.busy)
    free = _free_intervals(window_start, window_end, busy, payload.minimum_minutes)
    return FreeSlotsView(
        calendars_checked=calendar_ids,
        free_slots=[
            FreeSlot(
                start=start.astimezone(window_start.tzinfo).isoformat(),
                end=end.astimezone(window_start.tzinfo).isoformat(),
                minutes=int((end - start).total_seconds() // SECONDS_PER_MINUTE),
            )
            for start, end in free
        ],
        count=len(free),
    ).model_dump(mode="json")


def _free_intervals(
    window_start: datetime,
    window_end: datetime,
    busy: list[tuple[datetime, datetime]],
    minimum_minutes: int,
) -> list[tuple[datetime, datetime]]:
    """Merge busy blocks, clipping gaps to the requested window."""
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(busy):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    free: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for start, end in merged:
        if start > cursor:
            free.append((cursor, min(start, window_end)))
        cursor = max(cursor, end)
        if cursor >= window_end:
            break
    if cursor < window_end:
        free.append((cursor, window_end))
    minimum = timedelta(minutes=minimum_minutes)
    return [(start, end) for start, end in free if end - start >= minimum]


async def _calendar_entries(ctx: VendorToolContext) -> list[CalendarEntry]:
    entries: list[CalendarEntry] = []
    tokens: set[str] = set()
    token: str | None = None
    for _ in range(MAX_CALENDAR_LOOKUP_PAGES):
        query = CalendarListQuery(pageToken=token)
        page = parse_response(
            await ctx.read(
                "/users/me/calendarList",
                query=query.model_dump(mode="json", exclude_none=True),
            ),
            CALENDARS_RESPONSE,
        )
        entries.extend(page.items)
        token = page.nextPageToken
        if token is None:
            if len({entry.id for entry in entries}) != len(entries):
                invalid_response()
            return entries
        if token in tokens:
            break
        tokens.add(token)
    raise VendorToolError(
        CalendarErrorCode.LOOKUP_INCOMPLETE,
        "Calendar name lookup exceeded its page budget; use an explicit calendar id.",
    )


async def _resolve_calendars(ctx: VendorToolContext, calendars: list[str]) -> list[str]:
    """Resolve a group of names against one complete catalog, never N catalog reads."""
    candidates = [value.strip() for value in calendars]
    needs_lookup = any(
        candidate != PRIMARY and "@" not in candidate for candidate in candidates
    )
    entries = await _calendar_entries(ctx) if needs_lookup else []
    identifiers: list[str] = []
    for candidate in candidates:
        if candidate == PRIMARY or "@" in candidate:
            identifiers.append(candidate)
            continue
        exact = [entry for entry in entries if entry.id == candidate]
        matches = exact or [
            entry
            for entry in entries
            if entry.summary.casefold() == candidate.casefold()
        ]
        if len(matches) > 1:
            raise VendorToolError(
                CalendarErrorCode.CALENDAR_AMBIGUOUS,
                "Several calendars have that name; use an id.",
            )
        if not matches:
            raise VendorToolError(
                CalendarErrorCode.CALENDAR_NOT_FOUND,
                "No matching calendar is visible to this connection.",
            )
        identifiers.append(matches[0].id)
    return list(dict.fromkeys(identifiers))


def _events_path(calendar_id: str, event_id: str | None = None) -> str:
    path = f"/calendars/{quote(calendar_id, safe='')}/events"
    return path if event_id is None else f"{path}/{quote(event_id, safe='')}"


def _validate_shift(event: Event, expected: EventShift) -> None:
    start, end = event.start, event.end
    if event.status is EventStatus.CANCELLED or start is None or end is None:
        return invalid_response()
    if start.dateTime is None or end.dateTime is None:
        invalid_response()
    if start.timed().astimezone(UTC) != moment(expected.start.dateTime).astimezone(
        UTC
    ) or end.timed().astimezone(UTC) != moment(expected.end.dateTime).astimezone(UTC):
        invalid_response()


__all__ = [
    "cancel_event",
    "create_event",
    "find_free_time",
    "list_calendars",
    "list_events",
    "reschedule_event",
]
