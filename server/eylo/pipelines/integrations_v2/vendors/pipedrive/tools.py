"""Curated Pipedrive tool implementations for the `integrations_v2` pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field, FiniteFloat, JsonValue, StrictInt

from eylo.modules.integrations_v2.domain.enums import ToolEffect

from ...contracts import VendorToolContext, VendorToolError
from ...registry import curated_tool
from .definition import vendor
from .schemas import (
    DEALS_PATH,
    DEALS_RESPONSE,
    DEAL_RESPONSE,
    DEFAULT_DEAL_LIMIT,
    MAX_DEAL_LIMIT,
    MAX_NOTE_CHARS,
    MAX_STAGE_PAGES,
    NOTES_PATH,
    NOTE_RESPONSE,
    PERSONS_PATH,
    PERSONS_RESPONSE,
    PERSON_RESPONSE,
    PERSON_SEARCH_PATH,
    SEARCH_RESPONSE,
    STAGES_PATH,
    STAGES_RESPONSE,
    PipedriveDeal,
    PipedriveDealFilter,
    PipedriveDealStatus,
    PipedriveDealView,
    PipedriveDealWrite,
    PipedriveDealsQuery,
    PipedriveDealsView,
    PipedriveErrorCode,
    PipedriveNoteView,
    PipedriveNoteWrite,
    PipedrivePersonDetailQuery,
    PipedrivePersonMissing,
    PipedrivePersonSearchQuery,
    PipedrivePersonView,
    PipedrivePersonsQuery,
    PipedriveSearchPerson,
    PipedriveStage,
    PipedriveStageWrite,
    PipedriveStagesQuery,
    parse_response,
    require_identity,
)


class FindPersonInput(BaseModel):
    email: str = Field(min_length=1, description="Email address to search for.")


class ListDealsInput(BaseModel):
    status: PipedriveDealFilter = Field(
        default=PipedriveDealFilter.OPEN,
        description="open, won, lost, deleted, or all_not_deleted.",
    )
    person_email: str | None = Field(
        default=None, description="Only deals for this person."
    )
    limit: StrictInt = Field(default=DEFAULT_DEAL_LIMIT, ge=1, le=MAX_DEAL_LIMIT)


class CreateDealInput(BaseModel):
    title: str = Field(min_length=1, description="What the deal is.")
    value: FiniteFloat | None = Field(
        default=None, description="Deal value as a number."
    )
    currency: str | None = Field(
        default=None, description="Three-letter code, e.g. GBP."
    )
    person_email: str | None = Field(
        default=None, description="Attach to this person, if they exist."
    )
    stage: str | None = Field(default=None, description="Pipeline stage name.")


class MoveDealStageInput(BaseModel):
    deal_id: StrictInt = Field(ge=1)
    stage: str = Field(min_length=1, description="Target stage name, e.g. Negotiation.")


class AddNoteInput(BaseModel):
    content: str = Field(min_length=1, description="Note text.")
    deal_id: StrictInt | None = Field(
        default=None, ge=1, description="Attach to this deal."
    )
    person_email: str | None = Field(
        default=None, description="Attach to this person instead."
    )


@curated_tool(
    vendor=vendor.vendor,
    name="find_person",
    display_name="Find Pipedrive Person",
    description=(
        "Look a person up by email and report their id, name, organization, "
        "phone numbers, and how many open and closed deals they have. The id "
        "is what deals and notes attach to."
    ),
    input_model=FindPersonInput,
    effect=ToolEffect.READ,
)
async def find_person(
    payload: FindPersonInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    person = await _person_or_none(ctx, payload.email)
    if person is None:
        return PipedrivePersonMissing(email=payload.email).model_dump(mode="json")
    response = await ctx.read(
        f"{PERSONS_PATH}/{person.id}",
        query=PipedrivePersonDetailQuery().model_dump(mode="json"),
    )
    detail = parse_response(response, PERSON_RESPONSE).data
    require_identity(detail, person.id)
    # Search includes the organization name; the v2 detail only includes its id.
    organization = person.organization
    organization_name = (
        organization.name if organization and organization.id == detail.org_id else None
    )
    return PipedrivePersonView(
        id=detail.id,
        name=detail.name,
        emails=[entry.value for entry in detail.emails],
        phones=[entry.value for entry in detail.phones],
        organization=organization_name,
        open_deals=detail.open_deals_count,
        closed_deals=detail.closed_deals_count,
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_deals",
    display_name="List Pipedrive Deals",
    description=(
        "List deals, optionally only those belonging to one person. Each deal "
        "reports its value with currency and its stage by name rather than by "
        "the numeric id Pipedrive stores, so what comes back is readable "
        "without a second lookup."
    ),
    input_model=ListDealsInput,
    effect=ToolEffect.READ,
)
async def list_deals(
    payload: ListDealsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    person = None
    if payload.person_email:
        person = await _person_or_none(ctx, payload.person_email)
        if person is None:
            return PipedriveDealsView(deals=[], count=0, person_found=False).model_dump(
                mode="json", exclude_unset=True
            )
    status = (
        None
        if payload.status is PipedriveDealFilter.ALL_NOT_DELETED
        else PipedriveDealStatus(payload.status.value)
    )
    response = await ctx.read(
        DEALS_PATH,
        query=PipedriveDealsQuery(
            status=status, limit=payload.limit, person_id=person.id if person else None
        ).model_dump(mode="json", exclude_none=True),
    )
    deals = parse_response(response, DEALS_RESPONSE).data
    stages = await _stage_names(ctx)
    people: dict[int, str] = {person.id: person.name} if person else {}
    missing = sorted(
        {deal.person_id for deal in deals if deal.person_id is not None} - people.keys()
    )
    if missing:
        response = await ctx.read(
            PERSONS_PATH,
            query=PipedrivePersonsQuery(
                ids=",".join(str(person_id) for person_id in missing)
            ).model_dump(mode="json"),
        )
        resolved = parse_response(response, PERSONS_RESPONSE).data
        if any(item.id not in missing for item in resolved):
            raise VendorToolError(
                PipedriveErrorCode.RESPONSE_INVALID,
                "Pipedrive returned an unrequested person.",
            )
        people.update({item.id: item.name for item in resolved})
    return PipedriveDealsView(
        person=person.name if person else None,
        deals=[_deal_view(deal, stages, people) for deal in deals],
        count=len(deals),
    ).model_dump(mode="json", exclude_unset=True)


@curated_tool(
    vendor=vendor.vendor,
    name="create_deal",
    display_name="Create Pipedrive Deal",
    description=(
        "Open a deal, optionally attached to a person given by email and "
        "placed in a stage named rather than numbered. Returns the deal's id "
        "and the stage it landed in."
    ),
    input_model=CreateDealInput,
    effect=ToolEffect.MUTATION,
)
async def create_deal(
    payload: CreateDealInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    person = None
    if payload.person_email:
        person = await _person_or_none(ctx, payload.person_email)
        if person is None:
            raise VendorToolError(
                PipedriveErrorCode.PERSON_NOT_FOUND, "No matching Pipedrive person."
            )
    stages = await _stage_names(ctx)
    stage_id = _stage_id(stages, payload.stage) if payload.stage else None
    body = PipedriveDealWrite(
        title=payload.title,
        value=payload.value,
        currency=payload.currency.upper() if payload.currency else None,
        person_id=person.id if person else None,
        stage_id=stage_id,
    )
    created = parse_response(
        await ctx.mutate(
            DEALS_PATH, json=body.model_dump(mode="json", exclude_none=True)
        ),
        DEAL_RESPONSE,
    ).data
    if stage_id is not None and created.stage_id != stage_id:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned a different deal stage.",
        )
    if person is not None and created.person_id != person.id:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned a deal linked to a different person.",
        )
    return _deal_view(
        created, stages, {person.id: person.name} if person else {}
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="move_deal_stage",
    display_name="Move Pipedrive Deal",
    description=(
        "Move a deal to a different pipeline stage, named rather than "
        "numbered. If the name does not match a stage, the error lists the "
        "stages that exist."
    ),
    input_model=MoveDealStageInput,
    effect=ToolEffect.MUTATION,
)
async def move_deal_stage(
    payload: MoveDealStageInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    stages = await _stage_names(ctx)
    stage_id = _stage_id(stages, payload.stage)
    updated = parse_response(
        await ctx.mutate(
            f"{DEALS_PATH}/{payload.deal_id}",
            method="PATCH",
            json=PipedriveStageWrite(stage_id=stage_id).model_dump(mode="json"),
        ),
        DEAL_RESPONSE,
    ).data
    require_identity(updated, payload.deal_id)
    if updated.stage_id != stage_id:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive did not confirm the requested stage.",
        )
    return _deal_view(updated, stages, {}).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="add_note",
    display_name="Add Pipedrive Note",
    description=(
        "Log a note against a deal or a person. Notes are how conversation "
        "history reaches the CRM, so this is the tool for recording what was "
        "said or agreed."
    ),
    input_model=AddNoteInput,
    effect=ToolEffect.MUTATION,
)
async def add_note(
    payload: AddNoteInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    person_id = None
    if payload.deal_id is None:
        if not payload.person_email:
            raise VendorToolError(
                PipedriveErrorCode.TARGET_MISSING, "Give a deal_id or a person_email."
            )
        person = await _person_or_none(ctx, payload.person_email)
        if person is None:
            raise VendorToolError(
                PipedriveErrorCode.PERSON_NOT_FOUND, "No matching Pipedrive person."
            )
        person_id = person.id
    body = PipedriveNoteWrite(
        content=payload.content[:MAX_NOTE_CHARS],
        deal_id=payload.deal_id,
        person_id=person_id,
    )
    note = parse_response(
        await ctx.mutate(
            NOTES_PATH, json=body.model_dump(mode="json", exclude_none=True)
        ),
        NOTE_RESPONSE,
    ).data
    if (payload.deal_id is not None and note.deal_id != payload.deal_id) or (
        person_id is not None and note.person_id != person_id
    ):
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned a note linked to a different record.",
        )
    return PipedriveNoteView(
        note_id=note.id, deal_id=payload.deal_id, person_id=person_id
    ).model_dump(mode="json")


async def _person_or_none(
    ctx: VendorToolContext, email: str
) -> PipedriveSearchPerson | None:
    if not email.strip():
        raise VendorToolError(
            PipedriveErrorCode.TARGET_MISSING, "Give an email address."
        )
    response = await ctx.read(
        PERSON_SEARCH_PATH,
        query=PipedrivePersonSearchQuery(term=email.strip()).model_dump(mode="json"),
    )
    results = parse_response(response, SEARCH_RESPONSE).data.items
    matches = {
        entry.item.id: entry.item
        for entry in results
        if any(
            value.casefold() == email.strip().casefold() for value in entry.item.emails
        )
    }
    if len(matches) > 1:
        raise VendorToolError(
            PipedriveErrorCode.PERSON_AMBIGUOUS,
            "More than one Pipedrive person has that email.",
        )
    if results and not matches:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned a person that does not match the email.",
        )
    return next(iter(matches.values()), None)


async def _stage_names(ctx: VendorToolContext) -> dict[int, PipedriveStage]:
    stages: dict[int, PipedriveStage] = {}
    cursor = None
    seen: set[str] = set()
    for _ in range(MAX_STAGE_PAGES):
        response = await ctx.read(
            STAGES_PATH,
            query=PipedriveStagesQuery(cursor=cursor).model_dump(
                mode="json", exclude_none=True
            ),
        )
        page = parse_response(response, STAGES_RESPONSE)
        stages.update({stage.id: stage for stage in page.data})
        cursor = page.additional_data.next_cursor if page.additional_data else None
        if not cursor:
            return stages
        if cursor in seen:
            break
        seen.add(cursor)
    raise VendorToolError(
        PipedriveErrorCode.STAGE_CATALOG_INCOMPLETE,
        "Pipedrive stage lookup could not complete within its bounded page limit.",
    )


def _stage_id(stages: dict[int, PipedriveStage], name: str) -> int:
    matches = [
        stage.id
        for stage in stages.values()
        if stage.name.casefold() == name.strip().casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise VendorToolError(
            PipedriveErrorCode.STAGE_AMBIGUOUS,
            "The stage name is not unique across Pipedrive pipelines.",
        )
    available = ", ".join(sorted(stage.name for stage in stages.values()))
    raise VendorToolError(
        PipedriveErrorCode.STAGE_NOT_FOUND,
        f"No matching stage. Available: {available}.",
    )


def _deal_view(
    deal: PipedriveDeal, stages: dict[int, PipedriveStage], people: dict[int, str]
) -> PipedriveDealView:
    stage = stages.get(deal.stage_id)
    person = (
        people.get(deal.person_id, deal.person_id)
        if deal.person_id is not None
        else None
    )
    return PipedriveDealView(
        id=deal.id,
        title=deal.title,
        status=deal.status,
        value=deal.value,
        currency=deal.currency,
        formatted_value=f"{deal.value} {deal.currency}" if deal.currency else None,
        stage=stage.name if stage else None,
        stage_id=deal.stage_id,
        person=person,
        expected_close=deal.expected_close_date,
        won_at=deal.won_time,
        lost_reason=deal.lost_reason,
        updated_at=deal.update_time,
    )


__all__ = [
    "add_note",
    "create_deal",
    "find_person",
    "list_deals",
    "move_deal_stage",
]
