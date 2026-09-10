"""Analytics-owned query vocabulary and detached aggregate result contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ANALYTICS_DATE_FORMAT = "%Y-%m-%d"


class AnalyticsTimeSlice(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class AnalyticsEntity(StrEnum):
    CONVERSATIONS = "conversations"
    CONTACTS = "contacts"
    MESSAGES = "messages"
    MEMBERS = "members"


class AnalyticsPeriod(BaseModel):
    """Tenant and inclusive date bounds for one read-only aggregate query."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    organization_id: UUID
    start_date: datetime
    end_date: datetime
    timeslice: AnalyticsTimeSlice

    def query_parameters(self) -> dict[str, UUID | datetime | str]:
        """Keep native UUID/datetime bindings and decode the enum at the SQL edge."""
        return {
            "organization_id": self.organization_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "timeslice": self.timeslice.value,
        }


class AnalyticsCountBucket(BaseModel):
    """Validated DB aggregate, detached before the read transaction closes."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    count: int = Field(ge=0)
    day_created: datetime


class AnalyticsAgentBucket(AnalyticsCountBucket):
    agent_id: UUID


class AnalyticsCountPoint(BaseModel):
    """Existing public count/date wire shape."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    count: int = Field(ge=0)
    date: str


class AnalyticsAgentPoint(AnalyticsCountPoint):
    """Agent identity keeps its established camel-case JSON name."""

    agent_id: UUID = Field(serialization_alias="agentId")
