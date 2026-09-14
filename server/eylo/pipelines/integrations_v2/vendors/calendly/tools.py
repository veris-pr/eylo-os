"""Account-scoped Calendly tools; typed pages and confirmed cancellation results."""

from datetime import datetime
from http import HTTPStatus

from pydantic import BaseModel, Field, JsonValue, StrictBool, StrictInt, model_validator

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    CANCELLATION_RESPONSE,
    DEFAULT_PAGE_SIZE,
    EVENTS_RESPONSE,
    EVENT_TYPES_RESPONSE,
    INVITEES_RESPONSE,
    MAX_PAGE_SIZE,
    MAX_REASON_LENGTH,
    USER_RESPONSE,
    BookingLinkView,
    BookingLinksView,
    CalendlyScope,
    CancellationRequest,
    CancellationView,
    EventStatus,
    EventTypesQuery,
    Identifier,
    InviteeView,
    InviteesView,
    MeetingView,
    MeetingsView,
    PageQuery,
    ScheduledEvent,
    ScheduledEventsQuery,
    TimestampText,
    User,
    event_id,
    invalid_response,
    parse_response,
    utc_timestamp,
)


class GetAccountInput(BaseModel):
    pass


class ListEventTypesInput(BaseModel):
    include_inactive: StrictBool = False
    page_token: Identifier | None = Field(
        default=None, description="Continue with the same include_inactive setting."
    )


class ListScheduledEventsInput(BaseModel):
    status: EventStatus = EventStatus.ACTIVE
    min_start_time: TimestampText | None = Field(
        default=None,
        description="ISO timestamp with timezone; only meetings starting after this.",
    )
    max_start_time: TimestampText | None = Field(
        default=None, description="ISO timestamp with timezone; exclusive upper bound."
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    page_token: Identifier | None = Field(
        default=None, description="Continue with the same filters and limit."
    )

    @model_validator(mode="after")
    def ordered_window(self) -> "ListScheduledEventsInput":
        if self.min_start_time is not None and self.max_start_time is not None:
            start = datetime.fromisoformat(self.min_start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.max_start_time.replace("Z", "+00:00"))
            if end <= start:
                raise ValueError("max_start_time must be after min_start_time.")
        return self


class GetEventInviteesInput(BaseModel):
    event: Identifier = Field(description="Event identifier or its Calendly API URI.")
    page_token: Identifier | None = Field(
        default=None, description="Continue for the same event."
    )


class CancelEventInput(BaseModel):
    event: Identifier = Field(description="Event identifier or its Calendly API URI.")
    reason: str | None = Field(
        default=None,
        max_length=MAX_REASON_LENGTH,
        description="Human-readable cancellation reason, visible to the invitee.",
    )


@curated_tool(
    vendor=vendor.vendor,
    name="get_account",
    display_name="Get Calendly Account",
    description="Report whose Calendly account this connection acts as: name, email, scheduling page, and timezone.",
    input_model=GetAccountInput,
    effect=ToolEffect.READ,
    scopes=(CalendlyScope.USERS_READ,),
)
async def get_account(
    payload: GetAccountInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    return (await _current_user(ctx)).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_event_types",
    display_name="List Calendly Booking Links",
    description=(
        "List this account's booking links with names, durations and booking URLs. "
        "Inactive links are hidden unless requested. Pass next_page_token as "
        "page_token with the same settings to continue; count is this page only."
    ),
    input_model=ListEventTypesInput,
    effect=ToolEffect.READ,
    scopes=(CalendlyScope.USERS_READ, CalendlyScope.EVENT_TYPES_READ),
)
async def list_event_types(
    payload: ListEventTypesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    user = await _current_user(ctx)
    query = EventTypesQuery(
        user=user.uri,
        active=None if payload.include_inactive else True,
        page_token=payload.page_token,
    )
    response = await ctx.read(
        "/event_types", query=query.model_dump(mode="json", exclude_none=True)
    )
    page = parse_response(response, EVENT_TYPES_RESPONSE)
    items = [
        item for item in page.collection if payload.include_inactive or item.active
    ]
    return BookingLinksView(
        booking_links=[
            BookingLinkView(
                name=item.name,
                duration_minutes=item.duration,
                booking_url=item.scheduling_url,
                kind=item.kind,
                active=item.active,
                description=item.description_plain,
            )
            for item in items
        ],
        count=len(items),
        next_page_token=page.pagination.next_page_token,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_scheduled_events",
    display_name="List Calendly Meetings",
    description=(
        "List meetings booked on this account, newest start first, with times, location "
        "and attendee count. Narrow by a timezone-qualified time window. Pass "
        "next_page_token as page_token with unchanged filters to continue."
    ),
    input_model=ListScheduledEventsInput,
    effect=ToolEffect.READ,
    scopes=(CalendlyScope.USERS_READ, CalendlyScope.EVENTS_READ),
)
async def list_scheduled_events(
    payload: ListScheduledEventsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    user = await _current_user(ctx)
    query = ScheduledEventsQuery(
        user=user.uri,
        status=payload.status,
        count=payload.limit,
        min_start_time=utc_timestamp(payload.min_start_time),
        max_start_time=utc_timestamp(payload.max_start_time),
        page_token=payload.page_token,
    )
    response = await ctx.read(
        "/scheduled_events", query=query.model_dump(mode="json", exclude_none=True)
    )
    page = parse_response(response, EVENTS_RESPONSE)
    return MeetingsView(
        meetings=[_event_view(item) for item in page.collection],
        count=len(page.collection),
        next_page_token=page.pagination.next_page_token,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_event_invitees",
    display_name="Get Calendly Meeting Invitees",
    description=(
        "List who booked a meeting, their email, timezone, status and booking answers. "
        "Pass next_page_token as page_token for the same event to continue."
    ),
    input_model=GetEventInviteesInput,
    effect=ToolEffect.READ,
    scopes=(CalendlyScope.EVENTS_READ,),
)
async def get_event_invitees(
    payload: GetEventInviteesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    identifier = event_id(payload.event)
    response = await ctx.read(
        f"/scheduled_events/{identifier}/invitees",
        query=PageQuery(page_token=payload.page_token).model_dump(
            mode="json", exclude_none=True
        ),
    )
    page = parse_response(response, INVITEES_RESPONSE)
    if any(event_id(item.event) != identifier for item in page.collection):
        invalid_response()
    return InviteesView(
        event_uuid=identifier,
        invitees=[
            InviteeView(
                name=item.name,
                email=item.email,
                timezone=item.timezone,
                status=item.status,
                answers=item.questions_and_answers,
                cancel_url=item.cancel_url,
                reschedule_url=item.reschedule_url,
            )
            for item in page.collection
        ],
        count=len(page.collection),
        next_page_token=page.pagination.next_page_token,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="cancel_event",
    display_name="Cancel Calendly Meeting",
    description=(
        "Cancel a booked meeting with an optional human-readable reason. "
        "Confirms Calendly's cancellation acknowledgement, not delivery of an "
        "email notice; invitee_notified remains unknown."
    ),
    input_model=CancelEventInput,
    effect=ToolEffect.MUTATION,
    scopes=(CalendlyScope.EVENTS_WRITE,),
)
async def cancel_event(
    payload: CancelEventInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    identifier = event_id(payload.event)
    response = await ctx.mutate(
        f"/scheduled_events/{identifier}/cancellation",
        json=CancellationRequest(reason=payload.reason).model_dump(
            mode="json", exclude_none=True
        ),
    )
    cancellation = parse_response(
        response, CANCELLATION_RESPONSE, status=HTTPStatus.CREATED
    ).resource
    if payload.reason is not None and cancellation.reason != payload.reason:
        invalid_response()
    return CancellationView(
        event_uuid=identifier,
        cancelled_by=cancellation.canceled_by,
        reason=cancellation.reason,
        canceler_type=cancellation.canceler_type,
        cancelled_at=cancellation.created_at,
    ).model_dump(mode="json")


async def _current_user(ctx: VendorToolContext) -> User:
    return parse_response(await ctx.read("/users/me"), USER_RESPONSE).resource


def _event_view(event: ScheduledEvent) -> MeetingView:
    location = event.location
    return MeetingView(
        uuid=event_id(event.uri),
        name=event.name,
        status=event.status,
        start_time=event.start_time,
        end_time=event.end_time,
        location=(location.location or location.join_url or location.type)
        if location is not None
        else None,
        invitee_count=event.invitees_counter.active,
        hosts=[membership.user_email for membership in event.event_memberships],
        created_at=event.created_at,
    )


__all__ = [
    "cancel_event",
    "get_account",
    "get_event_invitees",
    "list_event_types",
    "list_scheduled_events",
]
