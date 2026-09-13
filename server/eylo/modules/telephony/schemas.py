"""Schemas for the telephony module."""

import re
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SkipValidation,
    StrictStr,
    field_serializer,
    field_validator,
    model_validator,
)

from eylo.common.contracts.json_values import JsonObject
from eylo.common.contracts.telephony import CallStatus as CallStatus
from eylo.common.outbound import (
    OUTBOUND_STATUS_CODE_MAX,
    OUTBOUND_STATUS_CODE_MIN,
    OutboundAttemptState,
)
from eylo.common.schemas import (
    EyloBaseApiSchema,
    EyloBaseOrganizationModelSchema,
    EyloBaseRequestSchema,
    EyloBaseResponseSchema,
    EyloBaseSchema,
    EyloOrganizationModelSchema,
    PaginatedResponseSchema,
)
from eylo.modules.telephony.constants import (
    CallControlFailureCode,
    CallControlStatus,
    CallOpenerDeliveryStatus,
    CallTransferStatus,
)
from eylo.modules.telephony.provider_config_domain import (
    TelephonyOperation,
    TelephonyProvider,
)
from eylo.modules.telephony.transfer_metadata import CallTransferMetadata


class PhoneNumberStatus(str, Enum):
    """Enum for phone number status."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PROVISIONING = "PROVISIONING"
    PROVISIONING_UNKNOWN = "PROVISIONING_UNKNOWN"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"


class CallDirection(str, Enum):
    """Direction of a telephony call."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallControlErrorDetail(BaseModel):
    """HTTP error projection shared by call-control producers and tool consumers."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    code: CallControlFailureCode
    operation: TelephonyOperation
    provider: TelephonyProvider | None = None


class OutboundCallRequest(BaseModel):
    """Operator call input; organization and call identity come from auth/header."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    to_number: StrictStr = Field(min_length=1)
    agent_id: UUID
    initial_message: StrictStr | None = None
    context: JsonObject | None = Field(default=None, repr=False)

    @field_validator("context")
    @classmethod
    def validate_origin_links(cls, value: JsonObject | None) -> JsonObject | None:
        """Check known links without rewriting original idempotency input."""
        OutboundCallOrigin.model_validate(value or {})
        return value


class OutboundCallOrigin(BaseModel):
    """Campaign links parsed separately from the unchanged request fingerprint."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    campaign_id: UUID | None = None
    campaign_contact_id: UUID | None = None
    campaign_attempt_id: UUID | None = None

    @field_validator(
        "campaign_id", "campaign_contact_id", "campaign_attempt_id", mode="before"
    )
    @classmethod
    def empty_link_is_absent(cls, value: object) -> object:
        """Preserve empty-string compatibility; all other values must be UUIDs."""
        return None if value == "" else value


class CallControlAcceptedResult(BaseModel):
    """Platform projection after the carrier accepts a live control."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[CallControlStatus.ACCEPTED] = CallControlStatus.ACCEPTED
    operation: TelephonyOperation
    provider_status: int | None = Field(
        default=None, ge=OUTBOUND_STATUS_CODE_MIN, le=OUTBOUND_STATUS_CODE_MAX
    )


class OutboundCallResult(BaseModel):
    """Committed initiation outcome, not the eventual status of the phone call.

    Keep IDs and effect state typed until the caller's serialization boundary.
    Retry requests propagate separately from the outbound execution authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_id: UUID
    call_sid: str | None
    status: OutboundAttemptState
    failure_code: str | None
    outbound_attempt_id: UUID
    agent_revision: int
    provider: TelephonyProvider
    provider_config_id: UUID
    provider_config_revision: int
    from_number: str


class PhoneNumberInDb(EyloBaseOrganizationModelSchema):
    """Schema for phone number data as it is in the database."""

    number: str
    label: Optional[str] = None
    status: PhoneNumberStatus
    provider: str
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    provider_reference: Optional[str] = None
    provisioning_failure_code: Optional[str] = None
    inbound_agent_id: Optional[UUID] = None
    outbound_agent_id: Optional[UUID] = None


class PhoneNumberApiResponseSchema(PhoneNumberInDb, EyloBaseResponseSchema):
    """Schema for phone number API responses."""

    pass


class PhoneNumbersPaginated(PaginatedResponseSchema):
    """Paginated response schema for phone numbers."""

    data: List[PhoneNumberApiResponseSchema]


class PhoneNumberCreateSchema(EyloBaseRequestSchema):
    """Schema for creating a new phone number."""

    number: str
    label: Optional[str] = None
    provider: str
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    inbound_agent_id: Optional[UUID] = None
    outbound_agent_id: Optional[UUID] = None

    @field_validator("number")
    def validate_phone_number(cls, v):
        if not re.match(r"^\+[1-9]\d{1,14}$", v):
            raise ValueError("Invalid phone number format")
        return v


class PhoneNumberUpdateSchema(EyloBaseRequestSchema):
    """Schema for updating an existing phone number."""

    label: Optional[str] = None
    status: Optional[PhoneNumberStatus] = None
    inbound_agent_id: Optional[UUID] = None
    outbound_agent_id: Optional[UUID] = None

    @field_validator("status")
    @classmethod
    def validate_operator_status(
        cls,
        value: Optional[PhoneNumberStatus],
    ) -> Optional[PhoneNumberStatus]:
        if value not in {
            None,
            PhoneNumberStatus.ACTIVE,
            PhoneNumberStatus.INACTIVE,
        }:
            raise ValueError("Provisioning status is controlled by the platform.")
        return value


# --- Telephony Call schemas ---


class TelephonyCallInDb(EyloOrganizationModelSchema):
    """Schema for telephony call data as it is in the database."""

    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None
    provider: str
    provider_config_id: UUID
    provider_config_revision: int = Field(gt=0)
    direction: str
    status: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    ended_reason: Optional[str] = None
    agent_id: Optional[UUID] = None
    agent_revision: Optional[int] = Field(default=None, gt=0)
    conversation_id: Optional[UUID] = None
    user_session_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None
    campaign_attempt_id: Optional[UUID] = None
    phone_number_id: Optional[UUID] = None
    voice_session_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    provider_status: Optional[str] = None
    media_claimed_at: Optional[datetime] = None
    opener_delivery_status: CallOpenerDeliveryStatus = (
        CallOpenerDeliveryStatus.NOT_REQUESTED
    )
    opener_delivered_at: Optional[datetime] = None
    status_history: list[dict] = Field(default_factory=list)
    recording_id: Optional[UUID] = None
    recording_url: Optional[str] = None
    transcript_id: Optional[UUID] = None
    transcript_url: Optional[str] = None
    transfer_status: CallTransferStatus = CallTransferStatus.NONE
    transfer_to: Optional[str] = None
    transfer_reason: Optional[str] = None
    transferred_at: Optional[datetime] = None
    transfer_metadata: CallTransferMetadata = Field(
        default_factory=CallTransferMetadata
    )
    cost_amount: Optional[float] = None
    cost_currency: Optional[str] = None
    latency_metrics: dict = Field(default_factory=dict)
    provider_metadata: dict = Field(default_factory=dict)
    analysis_metadata: dict = Field(default_factory=dict)

    @field_serializer("transfer_metadata")
    def serialize_transfer_metadata(self, value: CallTransferMetadata) -> JsonObject:
        return value.as_payload()

    @model_validator(mode="after")
    def exact_agent_ref(self) -> Self:
        if (self.agent_id is None) != (self.agent_revision is None):
            raise ValueError(
                "Telephony calls require a complete exact agent reference."
            )
        return self


class TelephonyCallStatusUpdateResult(EyloBaseSchema):
    """Result of applying a provider call-status update."""

    call: Optional[SkipValidation[TelephonyCallInDb]] = None
    previous_status: Optional[str] = None
    incoming_status: str
    status_changed: bool = False
    ignored: bool = False
    entered_terminal_status: bool = False


class TelephonyCallApiResponseSchema(EyloBaseResponseSchema):
    """Minimal public projection backed by canonical call writers."""

    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    call_sid: Optional[str] = None
    provider: str
    provider_config_id: UUID
    provider_config_revision: int
    direction: str
    status: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    ended_reason: Optional[str] = None
    agent_id: Optional[UUID] = None
    agent_revision: Optional[int] = None
    conversation_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    campaign_contact_id: Optional[UUID] = None
    campaign_attempt_id: Optional[UUID] = None
    phone_number_id: Optional[UUID] = None
    voice_session_id: Optional[UUID] = None
    started_at: Optional[datetime] = None
    connected_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    provider_status: Optional[str] = None
    opener_delivery_status: CallOpenerDeliveryStatus
    opener_delivered_at: Optional[datetime] = None
    transfer_status: CallTransferStatus
    transfer_to: Optional[str] = None
    transfer_reason: Optional[str] = None
    transferred_at: Optional[datetime] = None


class TelephonyCallsPaginated(PaginatedResponseSchema):
    """Paginated response schema for telephony calls."""

    data: List[TelephonyCallApiResponseSchema]


# --- Telephony Provider Config schemas ---


TelephonyProviderType = TelephonyProvider


class ProviderConfigApiResponseSchema(EyloBaseApiSchema):
    """Secret-safe telephony config lifecycle response."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    provider: str
    name: str
    revision: int = Field(gt=0)
    enabled: bool
    configured: bool
    verified: bool
    ready: bool
    verified_at: datetime | None
    config: JsonObject
    secrets: dict[str, str]
    operations: dict[TelephonyOperation, bool]


class ProviderConfigCreateSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid")

    provider: TelephonyProvider
    name: str = Field(min_length=1)
    config: JsonObject
    secrets: dict[str, str]


class ProviderConfigUpdateSchema(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    config: JsonObject | None = None
    secrets: dict[str, str | None] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be supplied.")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null.")
        return self


class ProviderConfigVerificationResponse(EyloBaseApiSchema):
    model_config = ConfigDict(extra="forbid")

    verified: bool = True
    provider: str
    revision: int = Field(gt=0)
    verified_at: datetime


# --- Number search & purchase schemas ---


class NumberType(str, Enum):
    """Types of phone numbers available from providers."""

    LOCAL = "Local"
    TOLL_FREE = "TollFree"
    MOBILE = "Mobile"


class NumberSearchParams(EyloBaseRequestSchema):
    """Query parameters for searching available numbers."""

    country: str
    number_type: NumberType = NumberType.LOCAL
    area_code: Optional[str] = None
    contains: Optional[str] = None
    limit: int = 20

    @field_validator("country")
    def validate_country(cls, v: str) -> str:
        if len(v) != 2 or not v.isalpha():
            raise ValueError("Country must be a 2-letter ISO code (e.g. US, GB)")
        return v.upper()

    @field_validator("limit")
    def validate_limit(cls, v: int) -> int:
        return max(1, min(v, 30))


class AvailableNumberSchema(EyloBaseRequestSchema):
    """A single available phone number from a provider search."""

    phone_number: str
    friendly_name: str
    locality: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    capabilities: dict = Field(default_factory=dict)


class AvailableNumbersResponseSchema(EyloBaseRequestSchema):
    """Response containing available numbers from a provider search."""

    provider: str
    country: str
    numbers: List[AvailableNumberSchema]


class NumberPurchaseRequest(EyloBaseRequestSchema):
    """Request to purchase a phone number from a provider."""

    phone_number: str
    label: Optional[str] = None
    country_code: Optional[str] = None

    @field_validator("phone_number")
    def validate_phone_number(cls, v: str) -> str:
        if not re.match(r"^\+[1-9]\d{1,14}$", v):
            raise ValueError("Invalid phone number format — must be E.164")
        return v

    @field_validator("country_code")
    def validate_country_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) != 2 or not v.isalpha():
            raise ValueError("Country code must be a 2-letter ISO code (e.g. US, GB)")
        return v.upper()
