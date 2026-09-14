"""Typed Zoom meeting workflows with explicit scheduling and cancellation targets."""

from datetime import UTC, datetime
from http import HTTPStatus
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import MEETING_READ, MEETING_WRITE, vendor
from .schemas import (
    DEFAULT_DURATION_MINUTES,
    DEFAULT_PAGE_SIZE,
    MAX_AGENDA_CHARS,
    MAX_DURATION_MINUTES,
    MAX_PAGE_SIZE,
    MEETING,
    MEETINGS_PATH,
    PAGE,
    AgendaExtent,
    CancelQuery,
    CancelView,
    CancellationScope,
    CreateRequest,
    CreateSettings,
    CreatedMeetingView,
    Identifier,
    ListQuery,
    Meeting,
    MeetingId,
    MeetingList,
    MeetingStatus,
    MeetingType,
    MeetingView,
    MeetingsView,
    Notifications,
    OccurrenceStatus,
    TimezoneName,
    WaitingRoom,
    ZoomErrorCode,
    invalid_response,
    moment,
    parse_response,
    require_deleted,
)


class ZoomInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListMeetingsInput(ZoomInput):
    which: MeetingList = MeetingList.UPCOMING
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    next_page_token: Identifier | None = None
    page_number: StrictInt | None = Field(default=None, ge=1)

    @field_validator("which", mode="before")
    @classmethod
    def normalize_kind(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value

    @model_validator(mode="after")
    def one_continuation(self) -> Self:
        if self.next_page_token is not None and self.page_number is not None:
            raise ValueError("Use next_page_token or page_number, not both.")
        return self


class CreateMeetingInput(ZoomInput):
    topic: str = Field(min_length=1)
    start_time: str = Field(
        min_length=1,
        description="ISO timestamp with offset, or local time plus timezone. Whole-second resolution.",
    )
    duration_minutes: StrictInt = Field(
        default=DEFAULT_DURATION_MINUTES, ge=1, le=MAX_DURATION_MINUTES
    )
    timezone: TimezoneName | None = None
    agenda: str | None = Field(default=None, max_length=MAX_AGENDA_CHARS)
    waiting_room_mode: Literal[WaitingRoom.ENABLED, WaitingRoom.DISABLED] | None = None
    waiting_room: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input. Use waiting_room_mode.",
    )

    @model_validator(mode="after")
    def scheduling_input(self) -> Self:
        parsed = moment(self.start_time, self.timezone)
        if parsed.microsecond:
            raise ValueError("Use whole-second start time resolution.")
        if self.waiting_room_mode is not None and self.waiting_room is not None:
            raise ValueError("Use waiting_room_mode or legacy waiting_room, not both.")
        return self

    @property
    def selected_waiting_room(self) -> WaitingRoom:
        return self.waiting_room_mode or (
            WaitingRoom.DISABLED if self.waiting_room is False else WaitingRoom.ENABLED
        )


class GetMeetingInput(ZoomInput):
    meeting_id: MeetingId


class CancelMeetingInput(GetMeetingInput):
    scope: CancellationScope = CancellationScope.SINGLE
    occurrence_id: Identifier | None = None
    notifications: Notifications | None = None
    notify_attendees: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input: true requests host and registrant notifications, not delivery confirmation.",
    )

    @model_validator(mode="after")
    def cancellation_input(self) -> Self:
        if self.scope == CancellationScope.SERIES and self.occurrence_id is not None:
            raise ValueError("A series cancellation cannot target one occurrence.")
        if self.notifications is not None and self.notify_attendees is not None:
            raise ValueError("Use notifications or legacy notify_attendees, not both.")
        return self

    @property
    def selected_notifications(self) -> Notifications:
        return self.notifications or (
            Notifications.NONE if self.notify_attendees is False else Notifications.ALL
        )


def _view(meeting: Meeting, extent: AgendaExtent) -> MeetingView:
    waiting = meeting.settings.waiting_room if meeting.settings is not None else None
    return MeetingView(
        id=str(meeting.id),
        instance_uuid=meeting.uuid,
        kind=meeting.type,
        topic=meeting.topic,
        start_time=meeting.start_time,
        duration_minutes=meeting.duration,
        timezone=meeting.timezone,
        join_url=meeting.join_url,
        passcode=meeting.password,
        agenda=meeting.agenda,
        agenda_extent=extent
        if meeting.agenda is not None
        else AgendaExtent.UNAVAILABLE,
        host_email=meeting.host_email,
        status=meeting.status,
        waiting_room=WaitingRoom.UNKNOWN
        if waiting is None
        else WaitingRoom.ENABLED
        if waiting
        else WaitingRoom.DISABLED,
        occurrences=meeting.occurrences,
    )


async def _meeting(ctx: VendorToolContext, meeting_id: str) -> Meeting:
    meeting = parse_response(await ctx.read(f"/meetings/{meeting_id}"), MEETING)
    if str(meeting.id) != meeting_id:
        invalid_response()
    return meeting


@curated_tool(
    vendor=vendor.vendor,
    name="list_meetings",
    display_name="List Zoom Meetings",
    description="List one page of unexpired scheduled meetings. Upcoming includes live meetings; previous is not a full historical archive. Follow next_page_token or next_page_number, not both, with unchanged options. Zoom truncates list agendas; get_meeting returns details.",
    input_model=ListMeetingsInput,
    effect=ToolEffect.READ,
    scopes=(MEETING_READ,),
)
async def list_meetings(
    payload: ListMeetingsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = ListQuery(
        type=payload.which,
        page_size=payload.limit,
        next_page_token=payload.next_page_token,
        page_number=payload.page_number,
    )
    page = parse_response(
        await ctx.read(
            MEETINGS_PATH, query=query.model_dump(mode="json", exclude_none=True)
        ),
        PAGE,
    )
    if len(page.meetings) > payload.limit:
        invalid_response()
    token = page.next_page_token or None
    if token is not None and token == payload.next_page_token:
        invalid_response()
    next_page: int | None = None
    if token is None and page.page_count:
        current_page = page.page_number
        if current_page is None:
            invalid_response()
        else:
            if payload.page_number is not None and current_page != payload.page_number:
                invalid_response()
            if current_page < page.page_count:
                next_page = current_page + 1
    views = [_view(meeting, AgendaExtent.EXCERPT) for meeting in page.meetings]
    return MeetingsView(
        meetings=views,
        count=len(views),
        total=page.total_records,
        next_page_token=token,
        next_page_number=next_page,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_meeting",
    display_name="Schedule Zoom Meeting",
    description="Schedule a future meeting with an explicit timestamp offset or local time plus IANA timezone. DST gaps/overlaps require an offset. Returns actual join details and waiting-room setting, which account policy may override. A successful creation does not prove invitations were delivered.",
    input_model=CreateMeetingInput,
    effect=ToolEffect.MUTATION,
    scopes=(MEETING_WRITE,),
)
async def create_meeting(
    payload: CreateMeetingInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    start = moment(payload.start_time, payload.timezone)
    if start <= datetime.now(UTC):
        raise VendorToolError(
            ZoomErrorCode.TIME_INVALID,
            "Start time must be in the future; Zoom would replace a past time with the current time.",
        )
    # Always send the instant as UTC. Keep the chosen zone for display.
    wire_start = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    request = CreateRequest(
        topic=payload.topic,
        start_time=wire_start,
        duration=payload.duration_minutes,
        timezone=payload.timezone,
        agenda=payload.agenda,
        settings=CreateSettings(
            waiting_room=payload.selected_waiting_room == WaitingRoom.ENABLED
        ),
    )
    meeting = parse_response(
        await ctx.mutate(
            MEETINGS_PATH, json=request.model_dump(mode="json", exclude_none=True)
        ),
        MEETING,
        HTTPStatus.CREATED,
    )
    if (
        meeting.type != MeetingType.SCHEDULED
        or meeting.topic != payload.topic
        or meeting.start_time is None
        or moment(meeting.start_time) != start
        or meeting.duration != payload.duration_minutes
        or not meeting.join_url
    ):
        invalid_response()
    return CreatedMeetingView(
        **_view(meeting, AgendaExtent.COMPLETE).model_dump(),
        requested_waiting_room=payload.selected_waiting_room,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_meeting",
    display_name="Get Zoom Meeting",
    description="Read meeting identity, kind, agenda, join details and actual waiting-room setting. Host start URLs are not exposed. A recurring meeting number identifies a series; instance_uuid is separate.",
    input_model=GetMeetingInput,
    effect=ToolEffect.READ,
    scopes=(MEETING_READ,),
)
async def get_meeting(
    payload: GetMeetingInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    return _view(
        await _meeting(ctx, payload.meeting_id), AgendaExtent.COMPLETE
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="cancel_meeting",
    display_name="Cancel Zoom Meeting",
    description="Delete a scheduled meeting, one recurring occurrence, or an explicitly selected series. Recurring meetings require occurrence_id or scope=series. Read preflight prevents accidental series deletion and refuses active meetings. Notification requests target hosts, registrants, both or neither; delivery is not confirmed.",
    input_model=CancelMeetingInput,
    effect=ToolEffect.MUTATION,
    scopes=(MEETING_WRITE, MEETING_READ),
)
async def cancel_meeting(
    payload: CancelMeetingInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    meeting = await _meeting(ctx, payload.meeting_id)
    if meeting.status is None:
        invalid_response()
    if meeting.type not in (
        MeetingType.SCHEDULED,
        MeetingType.RECURRING_TIMED,
        MeetingType.RECURRING_UNTIMED,
    ):
        raise VendorToolError(
            ZoomErrorCode.CANCEL_TARGET_INVALID,
            "This tool cancels scheduled meetings, not personal or instant meetings.",
        )
    recurring = meeting.type in (
        MeetingType.RECURRING_TIMED,
        MeetingType.RECURRING_UNTIMED,
    )
    if meeting.status == MeetingStatus.STARTED:
        raise VendorToolError(
            ZoomErrorCode.CANCEL_TARGET_INVALID,
            "This tool cancels scheduled meetings, not active calls.",
        )
    if (
        recurring
        and payload.scope == CancellationScope.SINGLE
        and payload.occurrence_id is None
    ):
        raise VendorToolError(
            ZoomErrorCode.CANCEL_TARGET_REQUIRED,
            "Choose an occurrence ID or explicitly set scope=series.",
        )
    if not recurring and (
        payload.scope == CancellationScope.SERIES or payload.occurrence_id is not None
    ):
        raise VendorToolError(
            ZoomErrorCode.CANCEL_TARGET_INVALID,
            "This meeting is not a recurring series.",
        )
    if payload.occurrence_id is not None and not any(
        occurrence.occurrence_id == payload.occurrence_id
        and occurrence.status == OccurrenceStatus.AVAILABLE
        for occurrence in meeting.occurrences
    ):
        raise VendorToolError(
            ZoomErrorCode.CANCEL_TARGET_INVALID,
            "This occurrence is not available in the meeting's current details.",
        )
    mode = payload.selected_notifications
    query = CancelQuery(
        occurrence_id=payload.occurrence_id,
        schedule_for_reminder=mode in (Notifications.ALL, Notifications.HOSTS),
        cancel_meeting_reminder=mode in (Notifications.ALL, Notifications.REGISTRANTS),
    )
    response = await ctx.mutate(
        f"/meetings/{payload.meeting_id}",
        method="DELETE",
        query=query.model_dump(mode="json", exclude_none=True),
    )
    require_deleted(response)
    return CancelView(
        meeting_id=payload.meeting_id,
        occurrence_id=payload.occurrence_id,
        scope=payload.scope,
        notifications_requested=mode,
    ).model_dump(mode="json")


__all__ = ["cancel_meeting", "create_meeting", "get_meeting", "list_meetings"]
