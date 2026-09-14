"""HubSpot CRM v3 selected wire contracts and agent-visible projections."""

from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)

from ...contracts import VendorResponse, VendorToolError

MAX_PAGE_LIMIT = 50
MAX_NOTE_CHARS = 65_536
CONTACT_PROPERTIES = (
    "email",
    "firstname",
    "lastname",
    "phone",
    "company",
    "jobtitle",
    "lifecyclestage",
    "hs_lead_status",
    "createdate",
)
DEAL_PROPERTIES = (
    "dealname",
    "amount",
    "dealstage",
    "pipeline",
    "closedate",
    "hs_deal_stage_probability",
)


class HubSpotErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"
    RECORD_EXISTS = "record_exists"
    SEARCH_UNBOUNDED = "search_unbounded"
    NO_CHANGE_REQUESTED = "no_change_requested"
    CONTACT_NOT_FOUND = "contact_not_found"
    INVOCATION_TIME_MISSING = "invocation_time_missing"


class HubSpotFilterOperator(StrEnum):
    EQUAL = "EQ"
    CONTAINS_TOKEN = "CONTAINS_TOKEN"


class HubSpotSearchProperty(StrEnum):
    EMAIL = "email"
    FIRST_NAME = "firstname"
    LAST_NAME = "lastname"


class HubSpotAssociationType(IntEnum):
    DEAL_TO_CONTACT = 3
    NOTE_TO_CONTACT = 202


class HubSpotModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class HubSpotRequest(HubSpotModel):
    model_config = ConfigDict(extra="forbid")


class HubSpotContactProperties(HubSpotModel):
    email: str | None = Field(default=None, repr=False)
    firstname: str | None = None
    lastname: str | None = None
    phone: str | None = Field(default=None, repr=False)
    company: str | None = None
    jobtitle: str | None = None
    lifecyclestage: str | None = None
    hs_lead_status: str | None = None
    createdate: str | None = None


class HubSpotContactWrite(HubSpotRequest):
    email: str | None = Field(default=None, repr=False)
    firstname: str | None = None
    lastname: str | None = None
    phone: str | None = Field(default=None, repr=False)
    company: str | None = None
    jobtitle: str | None = None
    lifecyclestage: str | None = None


class HubSpotDealProperties(HubSpotModel):
    dealname: str | None = None
    amount: str | None = None
    dealstage: str | None = None
    pipeline: str | None = None
    closedate: str | None = None
    hs_deal_stage_probability: str | None = None


class HubSpotDealWrite(HubSpotRequest):
    dealname: str = Field(min_length=1)
    amount: str | None = None
    dealstage: str | None = None
    closedate: str | None = None


class HubSpotNoteWrite(HubSpotRequest):
    hs_note_body: str = Field(min_length=1, max_length=MAX_NOTE_CHARS, repr=False)
    hs_timestamp: AwareDatetime


class HubSpotResource(HubSpotModel):
    id: str = Field(min_length=1)


class HubSpotContact(HubSpotResource):
    properties: HubSpotContactProperties


class HubSpotDeal(HubSpotResource):
    properties: HubSpotDealProperties


class HubSpotCollection[T](HubSpotModel):
    results: list[T]


class HubSpotAssociationTarget(HubSpotRequest):
    id: str = Field(min_length=1)


class HubSpotAssociationDefinition(HubSpotRequest):
    associationCategory: Literal["HUBSPOT_DEFINED"] = "HUBSPOT_DEFINED"
    associationTypeId: HubSpotAssociationType


class HubSpotAssociation(HubSpotRequest):
    to: HubSpotAssociationTarget
    types: list[HubSpotAssociationDefinition]


class HubSpotWrite[T](HubSpotRequest):
    properties: T
    associations: list[HubSpotAssociation] | None = None


class HubSpotFilter(HubSpotRequest):
    propertyName: HubSpotSearchProperty
    operator: HubSpotFilterOperator
    value: str = Field(min_length=1, repr=False)


class HubSpotFilterGroup(HubSpotRequest):
    filters: list[HubSpotFilter]


class HubSpotSearch(HubSpotRequest):
    filterGroups: list[HubSpotFilterGroup]
    properties: tuple[str, ...] = CONTACT_PROPERTIES
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)


class HubSpotLimitQuery(HubSpotRequest):
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)


class HubSpotPropertiesQuery(HubSpotRequest):
    properties: str = ",".join(DEAL_PROPERTIES)


class HubSpotDealsQuery(HubSpotPropertiesQuery):
    limit: int = Field(ge=1, le=MAX_PAGE_LIMIT)


class HubSpotStage(HubSpotResource):
    label: str


class HubSpotPipeline(HubSpotStage):
    stages: list[HubSpotStage]


class HubSpotLabels(HubSpotModel):
    pipelines: dict[str, str]
    stages: dict[tuple[str, str], str]


class HubSpotError(HubSpotModel):
    status: str | None = None
    category: str | None = None


class HubSpotContactView(HubSpotModel):
    id: str
    name: str | None
    email: str | None = Field(repr=False)
    phone: str | None = Field(repr=False)
    company: str | None
    job_title: str | None
    lifecycle_stage: str | None
    lead_status: str | None
    created_at: str | None


class HubSpotContactsView(HubSpotModel):
    contacts: list[HubSpotContactView]
    count: int


class HubSpotDealView(HubSpotModel):
    id: str
    name: str | None
    amount: str | None
    stage: str | None
    stage_id: str | None
    pipeline: str | None
    close_date: str | None
    probability: str | None


class HubSpotDealsView(HubSpotModel):
    deals: list[HubSpotDealView]
    count: int
    contact_found: bool | None = None


class HubSpotCreatedDealView(HubSpotDealView):
    associated_contact_id: str | None


class HubSpotNoteView(HubSpotModel):
    note_id: str
    contact_id: str
    contact_email: str = Field(repr=False)
    logged: Literal[True] = True


CONTACT_RESPONSE = TypeAdapter(HubSpotContact)
CONTACTS_RESPONSE = TypeAdapter(HubSpotCollection[HubSpotContact])
DEAL_RESPONSE = TypeAdapter(HubSpotDeal)
DEALS_RESPONSE = TypeAdapter(HubSpotCollection[HubSpotDeal])
ASSOCIATIONS_RESPONSE = TypeAdapter(HubSpotCollection[HubSpotResource])
PIPELINES_RESPONSE = TypeAdapter(HubSpotCollection[HubSpotPipeline])
NOTE_RESPONSE = TypeAdapter(HubSpotResource)
ERROR_STATUS = "error"
CONFLICT_CATEGORY = "CONFLICT"


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    """Require HTTP success and the operation's native shape; never replay writes."""
    try:
        error = HubSpotError.model_validate(response.data)
        if error.category == CONFLICT_CATEGORY or response.status_code == 409:
            raise VendorToolError(
                HubSpotErrorCode.RECORD_EXISTS, "HubSpot record already exists."
            )
        if not response.ok or error.status == ERROR_STATUS:
            raise VendorToolError(
                HubSpotErrorCode.REJECTED, "HubSpot rejected the request."
            )
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        raise VendorToolError(
            HubSpotErrorCode.RESPONSE_INVALID,
            "HubSpot returned an invalid operation response.",
        ) from None


def require_identity(resource: HubSpotResource, expected_id: str) -> None:
    if resource.id != expected_id:
        raise VendorToolError(
            HubSpotErrorCode.RESPONSE_INVALID, "HubSpot returned a different record."
        )
