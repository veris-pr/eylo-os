"""Curated HubSpot tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from datetime import UTC
from urllib.parse import quote

from pydantic import BaseModel, Field, FiniteFloat, JsonValue, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import CONTACTS_READ, CONTACTS_WRITE, DEALS_READ, DEALS_WRITE, vendor
from .schemas import (
    ASSOCIATIONS_RESPONSE,
    CONTACTS_RESPONSE,
    CONTACT_RESPONSE,
    DEALS_RESPONSE,
    DEAL_RESPONSE,
    MAX_NOTE_CHARS,
    MAX_PAGE_LIMIT,
    NOTE_RESPONSE,
    PIPELINES_RESPONSE,
    HubSpotAssociation,
    HubSpotAssociationDefinition,
    HubSpotAssociationTarget,
    HubSpotAssociationType,
    HubSpotContact,
    HubSpotContactView,
    HubSpotContactWrite,
    HubSpotContactsView,
    HubSpotCreatedDealView,
    HubSpotDeal,
    HubSpotDealView,
    HubSpotDealWrite,
    HubSpotDealsQuery,
    HubSpotDealsView,
    HubSpotErrorCode,
    HubSpotFilter,
    HubSpotFilterGroup,
    HubSpotFilterOperator,
    HubSpotLabels,
    HubSpotLimitQuery,
    HubSpotNoteView,
    HubSpotNoteWrite,
    HubSpotPropertiesQuery,
    HubSpotSearch,
    HubSpotSearchProperty,
    HubSpotWrite,
    parse_response,
    require_identity,
)


class FindContactInput(BaseModel):
    email: str | None = Field(default=None, description="Exact email address.")
    name_contains: str | None = Field(
        default=None, description="Part of a first or last name."
    )
    limit: StrictInt = Field(default=10, ge=1, le=MAX_PAGE_LIMIT)


class CreateContactInput(BaseModel):
    email: str = Field(min_length=1)
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    company: str | None = None
    job_title: str | None = None


class UpdateContactInput(BaseModel):
    contact_id: str = Field(min_length=1, description="HubSpot's contact id.")
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    company: str | None = None
    lifecycle_stage: str | None = Field(
        default=None, description="e.g. lead, marketingqualifiedlead, customer."
    )


class ListDealsInput(BaseModel):
    contact_email: str | None = Field(
        default=None, description="Only deals associated with this person."
    )
    limit: StrictInt = Field(default=20, ge=1, le=MAX_PAGE_LIMIT)


class CreateDealInput(BaseModel):
    name: str = Field(min_length=1)
    amount: FiniteFloat | None = Field(default=None, ge=0)
    stage_id: str | None = Field(
        default=None,
        description="Internal deal stage id. If omitted, HubSpot decides whether creation is valid.",
    )
    close_date: str | None = Field(default=None, description="ISO 8601 date.")
    contact_email: str | None = Field(
        default=None, description="Associate the deal with this person."
    )


class AddNoteInput(BaseModel):
    contact_email: str = Field(min_length=1, description="Person to log against.")
    body: str = Field(
        min_length=1, max_length=MAX_NOTE_CHARS, description="The note's text."
    )


@curated_tool(
    vendor=vendor.vendor,
    name="find_contact",
    display_name="Find HubSpot Contact",
    description=(
        "Look a person up by exact email or by part of their name, without "
        "building HubSpot's nested search filters. Returns their id and the "
        "properties worth knowing — company, job title, lifecycle stage — so "
        "a second read is rarely needed."
    ),
    input_model=FindContactInput,
    effect=ToolEffect.READ,
    scopes=(CONTACTS_READ,),
)
async def find_contact(
    payload: FindContactInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if payload.email and payload.email.strip():
        groups = [
            _group(
                HubSpotSearchProperty.EMAIL,
                HubSpotFilterOperator.EQUAL,
                payload.email.strip(),
            )
        ]
    elif payload.name_contains and payload.name_contains.strip():
        # Separate groups are ORed by HubSpot.
        groups = [
            _group(
                field,
                HubSpotFilterOperator.CONTAINS_TOKEN,
                payload.name_contains.strip(),
            )
            for field in (
                HubSpotSearchProperty.FIRST_NAME,
                HubSpotSearchProperty.LAST_NAME,
            )
        ]
    else:
        raise VendorToolError(
            HubSpotErrorCode.SEARCH_UNBOUNDED,
            "Give an email address or part of a name.",
        )
    results = await _search(ctx, groups, payload.limit)
    return HubSpotContactsView(
        contacts=[_contact_view(item) for item in results], count=len(results)
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="create_contact",
    display_name="Create HubSpot Contact",
    description=(
        "Add a person to the CRM. HubSpot rejects a duplicate email, and that "
        "is reported as a clear conflict rather than a raw error, so the "
        "sensible next step is to find the existing contact."
    ),
    input_model=CreateContactInput,
    effect=ToolEffect.MUTATION,
    scopes=(CONTACTS_WRITE,),
)
async def create_contact(
    payload: CreateContactInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    properties = HubSpotContactWrite(
        email=payload.email,
        firstname=payload.first_name,
        lastname=payload.last_name,
        phone=payload.phone,
        company=payload.company,
        jobtitle=payload.job_title,
    )
    response = await ctx.mutate(
        "/crm/v3/objects/contacts",
        json=HubSpotWrite(properties=properties).model_dump(
            mode="json", exclude_none=True
        ),
    )
    return _contact_view(parse_response(response, CONTACT_RESPONSE)).model_dump(
        mode="json"
    )


@curated_tool(
    vendor=vendor.vendor,
    name="update_contact",
    display_name="Update HubSpot Contact",
    description=(
        "Change a contact's properties. Only the fields given are sent, so "
        "everything else is left as it was. Use find_contact first to get the "
        "contact's id."
    ),
    input_model=UpdateContactInput,
    effect=ToolEffect.MUTATION,
    scopes=(CONTACTS_WRITE,),
)
async def update_contact(
    payload: UpdateContactInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    properties = HubSpotContactWrite(
        email=payload.email,
        firstname=payload.first_name,
        lastname=payload.last_name,
        phone=payload.phone,
        company=payload.company,
        lifecyclestage=payload.lifecycle_stage,
    )
    if not properties.model_dump(exclude_none=True):
        raise VendorToolError(
            HubSpotErrorCode.NO_CHANGE_REQUESTED,
            "Give at least one property to change.",
        )
    response = await ctx.mutate(
        f"/crm/v3/objects/contacts/{quote(payload.contact_id, safe='')}",
        method="PATCH",
        json=HubSpotWrite(properties=properties).model_dump(
            mode="json", exclude_none=True
        ),
    )
    contact = parse_response(response, CONTACT_RESPONSE)
    require_identity(contact, payload.contact_id)
    return _contact_view(contact).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_deals",
    display_name="List HubSpot Deals",
    description=(
        "List deals with their stage and pipeline resolved to readable names "
        "rather than the internal ids HubSpot stores. Give a contact's email "
        "to see only the deals associated with that person."
    ),
    input_model=ListDealsInput,
    effect=ToolEffect.READ,
    scopes=(DEALS_READ, CONTACTS_READ),
)
async def list_deals(
    payload: ListDealsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    labels = await _stage_labels(ctx)
    if payload.contact_email:
        contact = await _contact_by_email(ctx, payload.contact_email)
        if contact is None:
            return HubSpotDealsView(deals=[], count=0, contact_found=False).model_dump(
                mode="json"
            )
        response = await ctx.read(
            f"/crm/v3/objects/contacts/{quote(contact.id, safe='')}/associations/deals",
            query=HubSpotLimitQuery(limit=payload.limit).model_dump(mode="json"),
        )
        associations = parse_response(response, ASSOCIATIONS_RESPONSE).results
        deals: list[HubSpotDeal] = []
        for association in associations[: payload.limit]:
            detail = await ctx.read(
                f"/crm/v3/objects/deals/{quote(association.id, safe='')}",
                query=HubSpotPropertiesQuery().model_dump(mode="json"),
            )
            deal = parse_response(detail, DEAL_RESPONSE)
            require_identity(deal, association.id)
            deals.append(deal)
        return HubSpotDealsView(
            deals=[_deal_view(deal, labels) for deal in deals],
            count=len(deals),
            contact_found=True,
        ).model_dump(mode="json")
    response = await ctx.read(
        "/crm/v3/objects/deals",
        query=HubSpotDealsQuery(limit=payload.limit).model_dump(mode="json"),
    )
    deals = parse_response(response, DEALS_RESPONSE).results
    return HubSpotDealsView(
        deals=[_deal_view(deal, labels) for deal in deals], count=len(deals)
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_deal",
    display_name="Create HubSpot Deal",
    description=(
        "Open a deal, optionally associated with a person given by email. The "
        "association is made here, which HubSpot otherwise requires as a "
        "separate call against an association endpoint."
    ),
    input_model=CreateDealInput,
    effect=ToolEffect.MUTATION,
    scopes=(DEALS_READ, DEALS_WRITE, CONTACTS_READ),
)
async def create_deal(
    payload: CreateDealInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    # Resolve display metadata before the write: a later read failure must not
    # disguise an already accepted creation as a retryable failed operation.
    labels = await _stage_labels(ctx)
    properties = HubSpotDealWrite(
        dealname=payload.name,
        amount=str(payload.amount) if payload.amount is not None else None,
        dealstage=payload.stage_id,
        closedate=payload.close_date,
    )
    contact_id = None
    associations = None
    if payload.contact_email:
        contact = await _contact_by_email(ctx, payload.contact_email)
        if contact is None:
            raise VendorToolError(
                HubSpotErrorCode.CONTACT_NOT_FOUND, "No matching HubSpot contact."
            )
        contact_id = contact.id
        associations = [
            _association(contact_id, HubSpotAssociationType.DEAL_TO_CONTACT)
        ]
    response = await ctx.mutate(
        "/crm/v3/objects/deals",
        json=HubSpotWrite(properties=properties, associations=associations).model_dump(
            mode="json", exclude_none=True
        ),
    )
    view = _deal_view(parse_response(response, DEAL_RESPONSE), labels)
    return HubSpotCreatedDealView(
        **view.model_dump(), associated_contact_id=contact_id
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_note",
    display_name="Log a HubSpot Note",
    description=(
        "Log a note against a person, given by email. HubSpot models a note as "
        "an engagement. Creation and contact association use one request. "
        "The note appears on the contact's timeline."
    ),
    input_model=AddNoteInput,
    effect=ToolEffect.MUTATION,
    scopes=(CONTACTS_READ, CONTACTS_WRITE),
)
async def add_note(
    payload: AddNoteInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    if ctx.started_at is None:
        raise VendorToolError(
            HubSpotErrorCode.INVOCATION_TIME_MISSING,
            "A durable invocation timestamp is required.",
        )
    contact = await _contact_by_email(ctx, payload.contact_email)
    if contact is None:
        raise VendorToolError(
            HubSpotErrorCode.CONTACT_NOT_FOUND, "No matching HubSpot contact."
        )
    properties = HubSpotNoteWrite(
        hs_note_body=payload.body,
        hs_timestamp=ctx.started_at.astimezone(UTC),
    )
    response = await ctx.mutate(
        "/crm/v3/objects/notes",
        json=HubSpotWrite(
            properties=properties,
            associations=[
                _association(contact.id, HubSpotAssociationType.NOTE_TO_CONTACT)
            ],
        ).model_dump(mode="json", exclude_none=True),
    )
    note = parse_response(response, NOTE_RESPONSE)
    return HubSpotNoteView(
        note_id=note.id, contact_id=contact.id, contact_email=payload.contact_email
    ).model_dump(mode="json")


async def _search(
    ctx: VendorToolContext, filter_groups: list[HubSpotFilterGroup], limit: int
) -> list[HubSpotContact]:
    response = await ctx.read(
        "/crm/v3/objects/contacts/search",
        method="POST",
        json=HubSpotSearch(filterGroups=filter_groups, limit=limit).model_dump(
            mode="json"
        ),
    )
    return parse_response(response, CONTACTS_RESPONSE).results


async def _contact_by_email(
    ctx: VendorToolContext, email: str
) -> HubSpotContact | None:
    if not email.strip():
        raise VendorToolError(
            HubSpotErrorCode.SEARCH_UNBOUNDED, "Give an email address."
        )
    found = await _search(
        ctx,
        [
            _group(
                HubSpotSearchProperty.EMAIL, HubSpotFilterOperator.EQUAL, email.strip()
            )
        ],
        1,
    )
    if not found:
        return None
    contact = found[0]
    if (
        contact.properties.email is None
        or contact.properties.email.casefold() != email.strip().casefold()
    ):
        raise VendorToolError(
            HubSpotErrorCode.RESPONSE_INVALID,
            "HubSpot returned a contact that does not match the requested email.",
        )
    return contact


async def _stage_labels(ctx: VendorToolContext) -> HubSpotLabels:
    response = await ctx.read("/crm/v3/pipelines/deals")
    pipelines = parse_response(response, PIPELINES_RESPONSE).results
    return HubSpotLabels(
        pipelines={
            pipeline.id: pipeline.label or pipeline.id for pipeline in pipelines
        },
        stages={
            (pipeline.id, stage.id): stage.label or stage.id
            for pipeline in pipelines
            for stage in pipeline.stages
        },
    )


def _group(
    property_name: HubSpotSearchProperty, operator: HubSpotFilterOperator, value: str
) -> HubSpotFilterGroup:
    return HubSpotFilterGroup(
        filters=[
            HubSpotFilter(propertyName=property_name, operator=operator, value=value)
        ]
    )


def _association(contact_id: str, kind: HubSpotAssociationType) -> HubSpotAssociation:
    return HubSpotAssociation(
        to=HubSpotAssociationTarget(id=contact_id),
        types=[HubSpotAssociationDefinition(associationTypeId=kind)],
    )


def _contact_view(contact: HubSpotContact) -> HubSpotContactView:
    properties = contact.properties
    name = " ".join(
        part for part in (properties.firstname, properties.lastname) if part
    )
    return HubSpotContactView(
        id=contact.id,
        name=name or None,
        email=properties.email,
        phone=properties.phone,
        company=properties.company,
        job_title=properties.jobtitle,
        lifecycle_stage=properties.lifecyclestage,
        lead_status=properties.hs_lead_status,
        created_at=properties.createdate,
    )


def _deal_view(deal: HubSpotDeal, labels: HubSpotLabels) -> HubSpotDealView:
    properties = deal.properties
    stage_id = properties.dealstage or None
    pipeline_id = properties.pipeline or None
    return HubSpotDealView(
        id=deal.id,
        name=properties.dealname,
        amount=properties.amount,
        stage=labels.stages.get((pipeline_id or "", stage_id or ""), stage_id),
        stage_id=stage_id,
        pipeline=labels.pipelines.get(pipeline_id or "", pipeline_id),
        close_date=properties.closedate,
        probability=properties.hs_deal_stage_probability,
    )


__all__ = [
    "add_note",
    "create_contact",
    "create_deal",
    "find_contact",
    "list_deals",
    "update_contact",
]
