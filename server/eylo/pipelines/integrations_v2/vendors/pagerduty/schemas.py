"""PagerDuty REST v2 contracts for incidents, services and on-call pages."""

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn

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

MAX_BODY_CHARS = 4_000
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
DEFAULT_SERVICE_PAGE_SIZE = 50
MAX_SERVICE_LOOKUP_PAGES = 10
API_ACCEPT = "application/vnd.pagerduty+json;version=2"


class PagerDutyErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    SERVICE_NOT_FOUND = "service_not_found"
    SERVICE_AMBIGUOUS = "service_ambiguous"
    LOOKUP_INCOMPLETE = "service_lookup_incomplete"
    POLICY_MISSING = "escalation_policy_missing"


class IncidentStatus(StrEnum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Urgency(StrEnum):
    HIGH = "high"
    LOW = "low"


class ServiceStatus(StrEnum):
    ACTIVE = "active"
    WARNING = "warning"
    CRITICAL = "critical"
    MAINTENANCE = "maintenance"
    DISABLED = "disabled"


class ResourceType(StrEnum):
    INCIDENT = "incident"
    SERVICE = "service"
    MERGE_REASON = "merge_resolve_reason"


class DateRange(StrEnum):
    ALL = "all"


class IncidentSort(StrEnum):
    CREATED_DESCENDING = "created_at:desc"


class OnCallInclude(StrEnum):
    USERS = "users"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("PagerDuty timestamps require an explicit timezone.")
    return value


Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]
Timestamp = Annotated[str, AfterValidator(timestamp)]
NativeIncidentStatus = Annotated[
    IncidentStatus,
    BeforeValidator(
        lambda value: IncidentStatus(value) if isinstance(value, str) else value
    ),
]
NativeUrgency = Annotated[
    Urgency,
    BeforeValidator(lambda value: Urgency(value) if isinstance(value, str) else value),
]
NativeServiceStatus = Annotated[
    ServiceStatus,
    BeforeValidator(
        lambda value: ServiceStatus(value) if isinstance(value, str) else value
    ),
]


class PagerDutyModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )


class PagerDutyRequest(PagerDutyModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Reference(PagerDutyModel):
    id: Identifier
    summary: str


class User(Reference):
    # include[]=users expands references. A reference alone does not prove an email.
    email: str | None = None


class Assignment(PagerDutyModel):
    assignee: User


class ResolveReason(PagerDutyModel):
    type: Literal[ResourceType.MERGE_REASON]
    incident: Reference


class Incident(PagerDutyModel):
    id: Identifier
    type: Literal[ResourceType.INCIDENT]
    incident_number: int = Field(ge=1)
    title: str
    status: NativeIncidentStatus
    urgency: NativeUrgency
    service: Reference
    assignments: list[Assignment]
    escalation_policy: Reference | None
    created_at: Timestamp
    last_status_change_at: Timestamp
    html_url: str
    description: str | None = Field(default=None, repr=False)
    resolve_reason: ResolveReason | None = None


class IncidentResponse(PagerDutyModel):
    incident: Incident


class Note(PagerDutyModel):
    content: str = Field(repr=False)
    user: Reference
    created_at: Timestamp


class NotesResponse(PagerDutyModel):
    notes: list[Note]


class Service(PagerDutyModel):
    id: Identifier
    type: Literal[ResourceType.SERVICE]
    name: str
    status: NativeServiceStatus
    escalation_policy: Reference | None


class OnCall(PagerDutyModel):
    user: User
    escalation_policy: Reference
    escalation_level: int = Field(ge=1)
    schedule: Reference | None = None
    start: Timestamp | None
    end: Timestamp | None


class Pagination(PagerDutyModel):
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0)
    more: bool


class IncidentsPage(Pagination):
    incidents: list[Incident]


class ServicesPage(Pagination):
    services: list[Service]


class OnCallsPage(Pagination):
    oncalls: list[OnCall]


class PageQuery(PagerDutyRequest):
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class IncidentsQuery(PageQuery):
    statuses: list[IncidentStatus] = Field(serialization_alias="statuses[]")
    urgencies: list[Urgency] | None = Field(
        default=None, serialization_alias="urgencies[]"
    )
    service_ids: list[Identifier] | None = Field(
        default=None, serialization_alias="service_ids[]"
    )
    sort_by: IncidentSort = IncidentSort.CREATED_DESCENDING
    date_range: DateRange = DateRange.ALL


class OnCallsQuery(PageQuery):
    include: tuple[OnCallInclude, ...] = Field(
        default=(OnCallInclude.USERS,), serialization_alias="include[]"
    )
    escalation_policy_ids: list[Identifier] | None = Field(
        default=None, serialization_alias="escalation_policy_ids[]"
    )
    since: Timestamp
    until: Timestamp


class IncidentView(PagerDutyModel):
    id: str
    number: int
    title: str
    status: IncidentStatus
    urgency: Urgency
    service: str
    assigned_to: list[str]
    escalation_policy: str | None
    created_at: str
    last_status_change: str
    web_link: str


class IncidentsView(PagerDutyModel):
    incidents: list[IncidentView]
    count: int
    statuses: list[IncidentStatus]
    next_offset: int | None


class NoteView(PagerDutyModel):
    content: str = Field(repr=False)
    author: str
    created_at: str


class IncidentDetail(IncidentView):
    description: str | None = Field(repr=False)
    resolve_reason: ResolveReason | None
    notes: list[NoteView] | None = None


class ServiceView(PagerDutyModel):
    id: str
    name: str
    status: ServiceStatus
    escalation_policy: str | None


class ServicesView(PagerDutyModel):
    services: list[ServiceView]
    count: int
    next_offset: int | None


class OnCallView(PagerDutyModel):
    user_id: str
    name: str
    email: str | None
    escalation_level: int
    policy_id: str
    policy: str
    schedule: str | None
    shift_start: str | None
    shift_end: str | None


class OnCallsView(PagerDutyModel):
    service: str | None
    on_call: list[OnCallView]
    count: int
    as_of: str
    next_offset: int | None


INCIDENTS_RESPONSE = TypeAdapter(IncidentsPage)
INCIDENT_RESPONSE = TypeAdapter(IncidentResponse)
NOTES_RESPONSE = TypeAdapter(NotesResponse)
SERVICES_RESPONSE = TypeAdapter(ServicesPage)
ONCALLS_RESPONSE = TypeAdapter(OnCallsPage)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        PagerDutyErrorCode.RESPONSE_INVALID,
        "PagerDuty returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            PagerDutyErrorCode.REJECTED, "PagerDuty rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()


def next_offset(page: Pagination, *, requested: PageQuery, count: int) -> int | None:
    """Require echoed pagination and forward progress; never silently truncate."""
    if (
        page.offset != requested.offset
        or page.limit != requested.limit
        or count > page.limit
    ):
        invalid_response()
    if page.more:
        if count == 0:
            invalid_response()
        return page.offset + page.limit
    return None
