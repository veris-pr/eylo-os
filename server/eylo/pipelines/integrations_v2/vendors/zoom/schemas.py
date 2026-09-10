"""Zoom meeting resources, calendar-time conversion and native request contracts."""

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from http import HTTPStatus
from typing import Annotated, NoReturn
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

MEETINGS_PATH = "/users/me/meetings"
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
DEFAULT_DURATION_MINUTES = 30
MAX_DURATION_MINUTES = 1440
MAX_AGENDA_CHARS = 2000
MAX_INT64 = 2**63 - 1


class ZoomErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    TIME_INVALID = "time_invalid"
    CANCEL_TARGET_REQUIRED = "meeting_cancel_target_required"
    CANCEL_TARGET_INVALID = "meeting_cancel_target_invalid"


class MeetingType(IntEnum):
    INSTANT = 1
    SCHEDULED = 2
    RECURRING_UNTIMED = 3
    PERSONAL = 4
    RECURRING_TIMED = 8
    SCREEN_SHARE = 10


class MeetingStatus(StrEnum):
    WAITING = "waiting"
    STARTED = "started"


class OccurrenceStatus(StrEnum):
    AVAILABLE = "available"
    DELETED = "deleted"


class MeetingList(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    UPCOMING = "upcoming"
    UPCOMING_MEETINGS = "upcoming_meetings"
    PREVIOUS = "previous_meetings"


class WaitingRoom(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class Notifications(StrEnum):
    ALL = "all"
    NONE = "none"
    HOSTS = "hosts"
    REGISTRANTS = "registrants"


class CancellationScope(StrEnum):
    SINGLE = "single"
    SERIES = "series"


class AgendaExtent(StrEnum):
    EXCERPT = "provider_excerpt"
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"


class CancellationState(StrEnum):
    DELETED = "deleted"


def timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Use an installed IANA timezone name.") from None
    return value


def moment(value: str, zone_name: str | None = None) -> datetime:
    """Preserve explicit instants; require offsets for DST gaps and overlaps."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if "T" not in value:
        raise ValueError("Use a timestamp, not a date.")
    zone = ZoneInfo(timezone_name(zone_name)) if zone_name else None
    if parsed.tzinfo is not None:
        return parsed.astimezone(zone or UTC)
    if zone is None:
        raise ValueError("Provide a timestamp offset or an IANA timezone.")
    first = parsed.replace(tzinfo=zone)
    second = parsed.replace(tzinfo=zone, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed
    ):
        raise ValueError(
            "This local time is ambiguous or nonexistent. Supply an offset."
        )
    return first


def native_timestamp(value: str) -> str:
    moment(value)
    return value


def native_type(value: object) -> MeetingType:
    if isinstance(value, MeetingType):
        return value
    if type(value) is not int:
        raise ValueError("Zoom meeting type must be an integer.")
    return MeetingType(value)


def meeting_id(value: str) -> str:
    if int(value) > MAX_INT64:
        raise ValueError("Meeting ID exceeds int64.")
    return value


TimezoneName = Annotated[str, AfterValidator(timezone_name)]
Timestamp = Annotated[str, AfterValidator(native_timestamp)]
MeetingId = Annotated[
    str, Field(pattern=r"^[1-9][0-9]{0,18}$"), AfterValidator(meeting_id)
]
Identifier = Annotated[str, Field(min_length=1, max_length=4096)]
NativeType = Annotated[MeetingType, BeforeValidator(native_type)]
NativeStatus = Annotated[
    MeetingStatus,
    BeforeValidator(
        lambda value: MeetingStatus(value) if isinstance(value, str) else value
    ),
]


class ZoomModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class ZoomRequest(ZoomModel):
    model_config = ConfigDict(extra="forbid")


class MeetingSettings(ZoomModel):
    waiting_room: bool | None = None


class Occurrence(ZoomModel):
    occurrence_id: Identifier
    start_time: Timestamp
    duration: int = Field(ge=0)
    status: Annotated[
        OccurrenceStatus,
        BeforeValidator(
            lambda value: OccurrenceStatus(value) if isinstance(value, str) else value
        ),
    ]


class Meeting(ZoomModel):
    id: int = Field(gt=0, le=MAX_INT64)
    uuid: Identifier
    topic: str
    type: NativeType
    start_time: Timestamp | None = None
    duration: int | None = Field(default=None, ge=0)
    timezone: str | None = None
    join_url: str | None = None
    password: str | None = None
    agenda: str | None = None
    host_email: str | None = None
    status: NativeStatus | None = None
    settings: MeetingSettings | None = None
    occurrences: list[Occurrence] = Field(default_factory=list)


class MeetingPage(ZoomModel):
    meetings: list[Meeting]
    next_page_token: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    page_count: int | None = Field(default=None, ge=0)
    total_records: int | None = Field(default=None, ge=0)


class ErrorEnvelope(ZoomModel):
    code: int | None = None
    message: str | None = None


class ListQuery(ZoomRequest):
    type: MeetingList
    page_size: int
    next_page_token: str | None = None
    page_number: int | None = None


class CreateSettings(ZoomRequest):
    waiting_room: bool


class CreateRequest(ZoomRequest):
    topic: str
    type: MeetingType = MeetingType.SCHEDULED
    start_time: str
    duration: int
    timezone: str | None = None
    agenda: str | None = None
    settings: CreateSettings


class CancelQuery(ZoomRequest):
    occurrence_id: str | None = None
    schedule_for_reminder: bool
    cancel_meeting_reminder: bool


class MeetingView(ZoomModel):
    id: str
    instance_uuid: str
    kind: MeetingType
    topic: str
    start_time: str | None
    duration_minutes: int | None
    timezone: str | None
    join_url: str | None
    passcode: str | None
    agenda: str | None
    agenda_extent: AgendaExtent
    host_email: str | None
    status: MeetingStatus | None
    waiting_room: WaitingRoom
    occurrences: list[Occurrence]


class CreatedMeetingView(MeetingView):
    requested_waiting_room: WaitingRoom


class MeetingsView(ZoomModel):
    meetings: list[MeetingView]
    count: int
    total: int | None
    next_page_token: str | None
    next_page_number: int | None


class CancelView(ZoomModel):
    meeting_id: str
    occurrence_id: str | None
    scope: CancellationScope
    state: CancellationState = CancellationState.DELETED
    notifications_requested: Notifications


MEETING = TypeAdapter(Meeting)
PAGE = TypeAdapter(MeetingPage)
ERROR = TypeAdapter(ErrorEnvelope)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        ZoomErrorCode.RESPONSE_INVALID,
        "Zoom returned an invalid response for this operation.",
    )


def parse_response[T](
    response: VendorResponse, schema: TypeAdapter[T], status: HTTPStatus = HTTPStatus.OK
) -> T:
    if not response.ok:
        raise VendorToolError(ZoomErrorCode.REJECTED, "Zoom rejected the request.")
    if response.status_code != status:
        invalid_response()
    try:
        if ERROR.validate_python(response.data).code is not None:
            raise VendorToolError(ZoomErrorCode.REJECTED, "Zoom rejected the request.")
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def require_deleted(response: VendorResponse) -> None:
    if not response.ok:
        raise VendorToolError(ZoomErrorCode.REJECTED, "Zoom rejected the cancellation.")
    if response.status_code != HTTPStatus.NO_CONTENT or response.data is not None:
        invalid_response()
