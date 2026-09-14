"""Read-only PagerDuty tools with validated references and explicit pagination."""

from datetime import UTC, datetime

from pydantic import (
    BaseModel,
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
from .definition import vendor
from .schemas import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_SERVICE_PAGE_SIZE,
    INCIDENTS_RESPONSE,
    INCIDENT_RESPONSE,
    MAX_BODY_CHARS,
    MAX_PAGE_SIZE,
    MAX_SERVICE_LOOKUP_PAGES,
    NOTES_RESPONSE,
    ONCALLS_RESPONSE,
    SERVICES_RESPONSE,
    Identifier,
    Incident,
    IncidentDetail,
    IncidentStatus,
    IncidentView,
    IncidentsQuery,
    IncidentsView,
    NoteView,
    OnCallView,
    OnCallsQuery,
    OnCallsView,
    PageQuery,
    PagerDutyErrorCode,
    Service,
    ServiceView,
    ServicesPage,
    ServicesView,
    Timestamp,
    Urgency,
    invalid_response,
    next_offset,
    parse_response,
)


class ListIncidentsInput(BaseModel):
    statuses: list[IncidentStatus] | None = None
    urgency: Urgency | None = None
    service_name: str | None = Field(
        default=None, min_length=1, description="Exact service name or ID."
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: StrictInt = Field(
        default=0, ge=0, description="Use next_offset with the same filters."
    )

    @field_validator("statuses", mode="before")
    @classmethod
    def normalize_statuses(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                item.strip().casefold() if isinstance(item, str) else item
                for item in value
            ]
        return value

    @field_validator("urgency", mode="before")
    @classmethod
    def normalize_urgency(cls, value: object) -> object:
        if value == "":
            return None
        return value.strip().casefold() if isinstance(value, str) else value


class GetIncidentInput(BaseModel):
    incident_id: Identifier = Field(description="Incident ID or its number.")
    include_notes: StrictBool = True


class WhoIsOnCallInput(BaseModel):
    service_name: str | None = Field(
        default=None,
        min_length=1,
        description="Exact service name or ID; omit for all policies.",
    )
    limit: StrictInt = Field(default=DEFAULT_SERVICE_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: StrictInt = Field(default=0, ge=0)
    as_of: Timestamp | None = Field(
        default=None,
        description="Omit for now. Reuse returned as_of with next_offset to continue the same time window.",
    )

    @model_validator(mode="after")
    def continuation_window(self) -> "WhoIsOnCallInput":
        if self.offset > 0 and self.as_of is None:
            raise ValueError("Continuing on-call pages requires the returned as_of.")
        return self


class ListServicesInput(BaseModel):
    limit: StrictInt = Field(default=DEFAULT_SERVICE_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: StrictInt = Field(default=0, ge=0)


@curated_tool(
    vendor=vendor.vendor,
    name="list_incidents",
    display_name="List PagerDuty Incidents",
    description="List incidents across all dates, by default triggered and acknowledged. Narrow by status, urgency or exact service name/ID. Reports assignment and timestamps. Count is this page; continue using next_offset with the same filters.",
    input_model=ListIncidentsInput,
    effect=ToolEffect.READ,
)
async def list_incidents(
    payload: ListIncidentsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    statuses = payload.statuses or [
        IncidentStatus.TRIGGERED,
        IncidentStatus.ACKNOWLEDGED,
    ]
    service_ids = None
    if payload.service_name is not None:
        service_ids = [(await _service(ctx, payload.service_name)).id]
    query = IncidentsQuery(
        statuses=statuses,
        urgencies=[payload.urgency] if payload.urgency is not None else None,
        service_ids=service_ids,
        limit=payload.limit,
        offset=payload.offset,
    )
    page = parse_response(
        await ctx.read(
            "/incidents",
            query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
        ),
        INCIDENTS_RESPONSE,
    )
    continuation = next_offset(page, requested=query, count=len(page.incidents))
    return IncidentsView(
        incidents=[_incident_view(item) for item in page.incidents],
        count=len(page.incidents),
        statuses=statuses,
        next_offset=continuation,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="get_incident",
    display_name="Get PagerDuty Incident",
    description="Read one incident by ID or number, with responder notes unless include_notes is false. Notes and description are capped at 4,000 characters each.",
    input_model=GetIncidentInput,
    effect=ToolEffect.READ,
)
async def get_incident(
    payload: GetIncidentInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    incident = parse_response(
        await ctx.read(f"/incidents/{payload.incident_id}"), INCIDENT_RESPONSE
    ).incident
    if payload.incident_id not in {incident.id, str(incident.incident_number)}:
        invalid_response()
    notes = None
    if payload.include_notes:
        response = parse_response(
            await ctx.read(f"/incidents/{incident.id}/notes"), NOTES_RESPONSE
        )
        notes = [
            NoteView(
                content=note.content[:MAX_BODY_CHARS],
                author=note.user.summary,
                created_at=note.created_at,
            )
            for note in response.notes
        ]
    return IncidentDetail(
        **_incident_view(incident).model_dump(),
        description=incident.description[:MAX_BODY_CHARS]
        if incident.description is not None
        else None,
        resolve_reason=incident.resolve_reason,
        notes=notes,
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="who_is_on_call",
    display_name="Who Is On Call",
    description="Report current on-call shifts, optionally for an exact service name/ID. Preserve separate policies and shifts for the same person. Email is returned when PagerDuty provides it. Count is this page; use next_offset and returned as_of to continue.",
    input_model=WhoIsOnCallInput,
    effect=ToolEffect.READ,
)
async def who_is_on_call(
    payload: WhoIsOnCallInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    service = (
        await _service(ctx, payload.service_name)
        if payload.service_name is not None
        else None
    )
    if service is not None and service.escalation_policy is None:
        raise VendorToolError(
            PagerDutyErrorCode.POLICY_MISSING, "The service has no escalation policy."
        )
    policy_ids = (
        [service.escalation_policy.id]
        if service is not None and service.escalation_policy is not None
        else None
    )
    as_of = payload.as_of or datetime.now(UTC).isoformat()
    query = OnCallsQuery(
        limit=payload.limit,
        offset=payload.offset,
        escalation_policy_ids=policy_ids,
        since=as_of,
        until=as_of,
    )
    page = parse_response(
        await ctx.read(
            "/oncalls",
            query=query.model_dump(mode="json", by_alias=True, exclude_none=True),
        ),
        ONCALLS_RESPONSE,
    )
    continuation = next_offset(page, requested=query, count=len(page.oncalls))
    people = [
        OnCallView(
            user_id=entry.user.id,
            name=entry.user.summary,
            email=entry.user.email,
            escalation_level=entry.escalation_level,
            policy_id=entry.escalation_policy.id,
            policy=entry.escalation_policy.summary,
            schedule=entry.schedule.summary if entry.schedule is not None else None,
            shift_start=entry.start,
            shift_end=entry.end,
        )
        for entry in page.oncalls
    ]
    people.sort(key=lambda item: item.escalation_level)
    return OnCallsView(
        service=service.name if service is not None else None,
        on_call=people,
        count=len(people),
        as_of=as_of,
        next_offset=continuation,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_services",
    display_name="List PagerDuty Services",
    description="List PagerDuty services with IDs, names, state and escalation policy. Other tools accept an exact service name or ID. Count is this page; continue using next_offset.",
    input_model=ListServicesInput,
    effect=ToolEffect.READ,
)
async def list_services(
    payload: ListServicesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = PageQuery(limit=payload.limit, offset=payload.offset)
    page = await _services(ctx, query)
    continuation = next_offset(page, requested=query, count=len(page.services))
    return ServicesView(
        services=[
            ServiceView(
                id=item.id,
                name=item.name,
                status=item.status,
                escalation_policy=item.escalation_policy.summary
                if item.escalation_policy is not None
                else None,
            )
            for item in page.services
        ],
        count=len(page.services),
        next_offset=continuation,
    ).model_dump(mode="json")


async def _services(ctx: VendorToolContext, query: PageQuery) -> ServicesPage:
    return parse_response(
        await ctx.read("/services", query=query.model_dump(mode="json")),
        SERVICES_RESPONSE,
    )


async def _service(ctx: VendorToolContext, name: str) -> Service:
    """Select only from a complete bounded catalog; duplicate names are not authority."""
    query = PageQuery(limit=MAX_PAGE_SIZE)
    services: dict[str, Service] = {}
    for _ in range(MAX_SERVICE_LOOKUP_PAGES):
        page = await _services(ctx, query)
        for service in page.services:
            if service.id in services:
                invalid_response()
            services[service.id] = service
        continuation = next_offset(page, requested=query, count=len(page.services))
        if continuation is None:
            break
        query = PageQuery(limit=MAX_PAGE_SIZE, offset=continuation)
    else:
        raise VendorToolError(
            PagerDutyErrorCode.LOOKUP_INCOMPLETE,
            "The service catalog exceeded the lookup bound; the name cannot be resolved safely.",
        )
    wanted = name.strip()
    if wanted in services:
        return services[wanted]
    matches = [
        item for item in services.values() if item.name.casefold() == wanted.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise VendorToolError(
            PagerDutyErrorCode.SERVICE_AMBIGUOUS,
            "Several services have this name. Use the intended service ID.",
        )
    raise VendorToolError(
        PagerDutyErrorCode.SERVICE_NOT_FOUND,
        "No service matches the requested name or ID.",
    )


def _incident_view(incident: Incident) -> IncidentView:
    return IncidentView(
        id=incident.id,
        number=incident.incident_number,
        title=incident.title,
        status=incident.status,
        urgency=incident.urgency,
        service=incident.service.summary,
        assigned_to=[
            assignment.assignee.summary for assignment in incident.assignments
        ],
        escalation_policy=incident.escalation_policy.summary
        if incident.escalation_policy is not None
        else None,
        created_at=incident.created_at,
        last_status_change=incident.last_status_change_at,
        web_link=incident.html_url,
    )
