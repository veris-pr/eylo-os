"""Pipedrive v2 CRM and v1 note wire contracts; no platform domain types leak in."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ...contracts import VendorResponse, VendorToolError

MAX_NOTE_CHARS = 6_000
MAX_DEAL_LIMIT = 100
DEFAULT_DEAL_LIMIT = 25
PERSON_SEARCH_LIMIT = 5
STAGE_PAGE_LIMIT = 500
MAX_STAGE_PAGES = 10
DEALS_PATH = "/api/v2/deals"
PERSONS_PATH = "/api/v2/persons"
PERSON_SEARCH_PATH = "/api/v2/persons/search"
STAGES_PATH = "/api/v2/stages"
NOTES_PATH = "/v1/notes"


class PipedriveErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    PERSON_NOT_FOUND = "person_not_found"
    PERSON_AMBIGUOUS = "person_ambiguous"
    STAGE_NOT_FOUND = "stage_not_found"
    STAGE_AMBIGUOUS = "stage_ambiguous"
    STAGE_CATALOG_INCOMPLETE = "stage_catalog_incomplete"
    TARGET_MISSING = "target_missing"


class PipedriveDealStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    DELETED = "deleted"


class PipedriveDealFilter(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    DELETED = "deleted"
    ALL_NOT_DELETED = "all_not_deleted"


class PipedriveModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class PipedriveRequest(PipedriveModel):
    model_config = ConfigDict(extra="forbid")


class PipedriveEnvelope[T](PipedriveModel):
    success: bool
    data: T


class PipedriveStatus(PipedriveModel):
    success: bool


class PipedriveCursor(PipedriveModel):
    next_cursor: str | None = None


class PipedrivePage[T](PipedriveEnvelope[list[T]]):
    additional_data: PipedriveCursor | None = None


class PipedriveResource(PipedriveModel):
    id: int = Field(ge=1)


class PipedriveNamedResource(PipedriveResource):
    name: str


class PipedriveSearchPerson(PipedriveNamedResource):
    emails: list[str] = Field(repr=False)
    phones: list[str] = Field(default_factory=list, repr=False)
    organization: PipedriveNamedResource | None = None


class PipedriveSearchItem(PipedriveModel):
    item: PipedriveSearchPerson


class PipedriveSearchData(PipedriveModel):
    items: list[PipedriveSearchItem]


class PipedriveContactValue(PipedriveModel):
    value: str = Field(repr=False)


class PipedrivePerson(PipedriveNamedResource):
    emails: list[PipedriveContactValue] = Field(repr=False)
    phones: list[PipedriveContactValue] = Field(repr=False)
    org_id: int | None = None
    open_deals_count: int | None = Field(default=None, ge=0)
    closed_deals_count: int | None = Field(default=None, ge=0)


class PipedriveStage(PipedriveNamedResource):
    pipeline_id: int = Field(ge=1)


class PipedriveDeal(PipedriveResource):
    title: str
    status: str
    value: int | float
    currency: str
    stage_id: int = Field(ge=1)
    person_id: int | None = None
    expected_close_date: str | None = None
    won_time: str | None = None
    lost_reason: str | None = None
    update_time: str | None = None


class PipedriveNote(PipedriveResource):
    deal_id: int | None = None
    person_id: int | None = None


class PipedrivePersonSearchQuery(PipedriveRequest):
    term: str = Field(min_length=1, repr=False)
    fields: Literal["email"] = "email"
    exact_match: Literal[True] = True
    limit: int = PERSON_SEARCH_LIMIT


class PipedrivePersonDetailQuery(PipedriveRequest):
    include_fields: Literal["open_deals_count,closed_deals_count"] = (
        "open_deals_count,closed_deals_count"
    )


class PipedrivePersonsQuery(PipedriveRequest):
    ids: str = Field(min_length=1)
    limit: int = MAX_DEAL_LIMIT


class PipedriveDealsQuery(PipedriveRequest):
    status: PipedriveDealStatus | None = None
    limit: int = Field(ge=1, le=MAX_DEAL_LIMIT)
    person_id: int | None = None


class PipedriveStagesQuery(PipedriveRequest):
    limit: int = STAGE_PAGE_LIMIT
    cursor: str | None = None


class PipedriveDealWrite(PipedriveRequest):
    title: str = Field(min_length=1)
    value: float | None = None
    currency: str | None = None
    person_id: int | None = None
    stage_id: int | None = None


class PipedriveStageWrite(PipedriveRequest):
    stage_id: int = Field(ge=1)


class PipedriveNoteWrite(PipedriveRequest):
    content: str = Field(min_length=1, max_length=MAX_NOTE_CHARS, repr=False)
    deal_id: int | None = Field(default=None, ge=1)
    person_id: int | None = Field(default=None, ge=1)


class PipedrivePersonView(PipedriveModel):
    found: Literal[True] = True
    id: int
    name: str
    emails: list[str] = Field(repr=False)
    phones: list[str] = Field(repr=False)
    organization: str | None
    open_deals: int | None
    closed_deals: int | None


class PipedrivePersonMissing(PipedriveModel):
    found: Literal[False] = False
    email: str = Field(repr=False)


class PipedriveDealView(PipedriveModel):
    id: int
    title: str
    status: str
    value: int | float
    currency: str
    formatted_value: str | None
    stage: str | None
    stage_id: int
    person: str | int | None
    expected_close: str | None
    won_at: str | None
    lost_reason: str | None
    updated_at: str | None


class PipedriveDealsView(PipedriveModel):
    person: str | None = None
    deals: list[PipedriveDealView]
    count: int
    person_found: bool | None = None


class PipedriveNoteView(PipedriveModel):
    note_id: int
    deal_id: int | None
    person_id: int | None
    added: Literal[True] = True


SEARCH_RESPONSE = TypeAdapter(PipedriveEnvelope[PipedriveSearchData])
PERSON_RESPONSE = TypeAdapter(PipedriveEnvelope[PipedrivePerson])
PERSONS_RESPONSE = TypeAdapter(PipedrivePage[PipedriveNamedResource])
STAGES_RESPONSE = TypeAdapter(PipedrivePage[PipedriveStage])
DEALS_RESPONSE = TypeAdapter(PipedrivePage[PipedriveDeal])
DEAL_RESPONSE = TypeAdapter(PipedriveEnvelope[PipedriveDeal])
NOTE_RESPONSE = TypeAdapter(PipedriveEnvelope[PipedriveNote])


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """HTTP and native success are both required; malformed writes are not replayed."""
    if not response.ok:
        raise VendorToolError(
            PipedriveErrorCode.REJECTED, "Pipedrive rejected the request."
        )
    try:
        status = PipedriveStatus.model_validate(response.data)
        if not status.success:
            raise VendorToolError(
                PipedriveErrorCode.REJECTED, "Pipedrive rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned an invalid operation response.",
        ) from None


def require_identity(resource: PipedriveResource, expected_id: int) -> None:
    if resource.id != expected_id:
        raise VendorToolError(
            PipedriveErrorCode.RESPONSE_INVALID,
            "Pipedrive returned a different record.",
        )
