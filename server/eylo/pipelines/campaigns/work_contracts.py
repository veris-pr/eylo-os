"""Campaign worker inputs, detached dispatch context, and durable receipts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.absurd_work import DurableState
from eylo.products.campaigns.channels.base import CampaignChannelAdapter
from eylo.products.campaigns.schemas.indb import CampaignContactInDb, CampaignInDb


class CampaignAttemptParams(BaseModel):
    """Accept the producer's ID-only payload; never stringify arbitrary objects."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    organization_id: UUID
    attempt_id: UUID

    @field_validator("organization_id", "attempt_id", mode="before")
    @classmethod
    def decode_uuid(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value

    @property
    def work_id(self) -> UUID:
        return self.attempt_id

    def to_task_payload(self) -> dict[str, JsonValue]:
        return CampaignAttemptParams(
            organization_id=self.organization_id, attempt_id=self.attempt_id
        ).model_dump(mode="json")


class PreparedCampaignDispatch(BaseModel):
    """Detached validated values plus the same adapter that validated them.

    The adapter remains a live dependency, not a serialized snapshot. Protocol
    validation checks its interface; concrete implementations are type-checked.
    """

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", arbitrary_types_allowed=True
    )

    adapter: CampaignChannelAdapter = Field(exclude=True, repr=False)
    campaign: CampaignInDb = Field(exclude=True, repr=False)
    contact: CampaignContactInDb = Field(exclude=True, repr=False)
    initial_message: str | None = Field(exclude=True, repr=False)


class CampaignEffectAction(StrEnum):
    """A start-effect decision, distinct from an already-terminal receipt."""

    SEND = "send"
    RECOVER = "recover"


class CampaignAttemptReceipt(BaseModel):
    """Existing v1 task-result shape, including its stored ambiguity Boolean.

    This is a wire projection, not dispatch policy. Internal recovery decisions
    use CampaignEffectAction and the adapter's ChannelDispatchState instead.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    organization_id: UUID
    attempt_id: UUID
    state: DurableState
    tracking_id: str | None
    dispatch_unknown: bool

    def to_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")
