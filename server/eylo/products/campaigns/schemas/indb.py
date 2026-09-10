"""Internal database schemas for campaigns."""

import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.common.schemas import EyloOrganizationModelSchema
from eylo.products.campaigns.channel_config import (
    CampaignChannelConfig,
    CampaignChannelFields,
)
from eylo.products.campaigns.constants import CampaignChannel
from eylo.products.campaigns.domain import (
    CampaignRetryPolicy,
    CampaignScheduleConfig,
    CampaignVariables,
)


class CampaignModelSchema(EyloOrganizationModelSchema, CampaignChannelFields):
    name: str
    description: Optional[str] = None
    status: str = "draft"
    agent_id: UUID
    agent_revision: int
    published_revision: int
    active_revision: Optional[int] = None
    initial_message_template_id: Optional[UUID] = None
    initial_message_template_revision: Optional[int] = None
    schedule_config: CampaignScheduleConfig = Field(
        default_factory=CampaignScheduleConfig
    )
    retry_policy: CampaignRetryPolicy = Field(default_factory=CampaignRetryPolicy)
    concurrency_limit: int = 5
    total_contacts: int = 0
    completed_contacts: int = 0
    failed_contacts: int = 0
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None


class CampaignInDb(CampaignModelSchema):
    model_config = ConfigDict(from_attributes=True)


class CampaignCreateSchema(CampaignChannelFields):
    organization_id: UUID
    name: str
    description: Optional[str] = None
    agent_id: UUID
    agent_revision: int
    published_revision: int = 1
    active_revision: Optional[int] = None
    initial_message_template_id: Optional[UUID] = None
    initial_message_template_revision: Optional[int] = None
    schedule_config: CampaignScheduleConfig = Field(
        default_factory=CampaignScheduleConfig
    )
    retry_policy: CampaignRetryPolicy
    concurrency_limit: int = 5


class CampaignUpdateSchema(BaseModel):
    expected_revision: int
    name: Optional[str] = None
    description: Optional[str] = None
    channel: CampaignChannel | None = None
    channel_config: CampaignChannelConfig | None = None
    agent_id: Optional[UUID] = None
    initial_message_template_id: Optional[UUID] = None
    schedule_config: CampaignScheduleConfig | None = None
    retry_policy: CampaignRetryPolicy | None = None
    concurrency_limit: Optional[int] = None

    @field_validator("schedule_config", mode="before")
    @classmethod
    def require_supplied_schedule_config(cls, value: object) -> object:
        if value is None:
            raise ValueError("A supplied schedule config cannot be null.")
        return value

    @field_validator("retry_policy", mode="before")
    @classmethod
    def require_supplied_retry_policy(cls, value: object) -> object:
        if value is None:
            raise ValueError("A supplied retry policy cannot be null.")
        return value


class CampaignContactModelSchema(EyloOrganizationModelSchema):
    campaign_id: UUID
    campaign_revision: Optional[int] = None
    contact_id: Optional[UUID] = None
    contact_address: str
    status: str = "pending"
    attempt_count: int = 0
    last_attempt_at: Optional[datetime.datetime] = None
    next_retry_at: Optional[datetime.datetime] = None
    last_tracking_id: Optional[str] = None
    last_outcome_reason: Optional[str] = None
    variables: CampaignVariables = Field(default_factory=dict)


class CampaignContactInDb(CampaignContactModelSchema):
    model_config = ConfigDict(from_attributes=True)


class CampaignContactCreateSchema(BaseModel):
    contact_address: str
    contact_id: Optional[UUID] = None
    variables: CampaignVariables = Field(default_factory=dict)


class CampaignContactBulkCreateSchema(BaseModel):
    """Schema for bulk-creating campaign contacts from CSV upload."""

    contacts: List[CampaignContactCreateSchema]
