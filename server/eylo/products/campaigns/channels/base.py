"""Channel adapter protocol and dispatch result model."""

from enum import StrEnum
from typing import Optional, Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

from eylo.products.campaigns.schemas.indb import CampaignContactInDb, CampaignInDb


class ChannelDispatchState(StrEnum):
    """An identity alone does not establish whether a provider accepted work."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class ChannelReplayPolicy(StrEnum):
    """Whether replay can reenter an idempotent effect or must only recover it."""

    REPLAY_SAFE = "replay_safe"
    RECOVER_ONLY = "recover_only"


class _DispatchCheckpoint(BaseModel):
    """Persisted v1 wire shape; retained for existing and mixed-version workers."""

    model_config = ConfigDict(strict=True, extra="forbid")

    tracking_id: str
    error: str | None = None
    dispatch_unknown: bool = False


class ChannelDispatchResult(BaseModel):
    """Validated channel outcome; only accepted work requires a tracking identity."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    state: ChannelDispatchState
    tracking_id: str
    error: str | None = None

    @field_validator("tracking_id")
    @classmethod
    def normalize_tracking_id(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.state is ChannelDispatchState.ACCEPTED:
            if not self.tracking_id or self.error is not None:
                raise ValueError("Accepted dispatch requires an identity and no error.")
        if self.state is ChannelDispatchState.REJECTED and not self.error:
            raise ValueError("Rejected dispatch requires an error.")
        return self

    def to_checkpoint(self) -> dict[str, JsonValue]:
        """Keep the existing durable step JSON shape, not a new replay format."""
        return {
            "tracking_id": self.tracking_id,
            "error": self.error,
            "dispatch_unknown": self.state is ChannelDispatchState.UNKNOWN,
        }

    @classmethod
    def from_checkpoint(cls, value: object) -> Self:
        checkpoint = _DispatchCheckpoint.model_validate(value)
        if checkpoint.dispatch_unknown:
            state = ChannelDispatchState.UNKNOWN
        elif checkpoint.error:
            state = ChannelDispatchState.REJECTED
        else:
            state = ChannelDispatchState.ACCEPTED
        return cls(
            state=state,
            tracking_id=checkpoint.tracking_id,
            error=checkpoint.error or None,
        )


@runtime_checkable
class CampaignChannelAdapter(Protocol):
    """Protocol that every campaign channel must implement.

    Adapters are responsible for:
    - Validating campaign-level configuration for their channel
    - Validating individual contacts (correct address format)
    - Dispatching the actual outreach (call, email, chat message)
    """

    channel: str
    replay_policy: ChannelReplayPolicy

    async def validate_campaign(self, campaign: CampaignInDb) -> list[str]:
        """Return a list of validation error messages. Empty list = valid."""
        ...

    async def validate_contact(self, contact: CampaignContactInDb) -> bool:
        """Return True if the contact has a valid address for this channel."""
        ...

    async def dispatch(
        self,
        campaign: CampaignInDb,
        contact: CampaignContactInDb,
        rendered_message: Optional[str],
        attempt_id: UUID,
    ) -> ChannelDispatchResult:
        """Send the outreach. Returns a tracking ID for status tracking."""
        ...

    async def recover_dispatch(
        self,
        campaign: CampaignInDb,
        contact: CampaignContactInDb,
        attempt_id: UUID,
    ) -> ChannelDispatchResult | None:
        """Return a durable provider receipt after a worker restart, if any."""
        ...
