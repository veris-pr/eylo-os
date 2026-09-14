"""Campaign-owned channel settings; provider secrets stay outside product values."""

from typing import Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from eylo.products.campaigns.constants import CampaignChannel


class EmptyCampaignChannelConfig(BaseModel):
    """Voice and widget take authority from the agent, not per-campaign settings."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    def to_storage(self) -> dict[str, JsonValue]:
        return {}


class EmailCampaignChannelConfig(BaseModel):
    """Draft settings may be incomplete; dispatch requires an exact provider pair."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    provider_config_id: UUID | None = None
    provider_config_revision: int | None = Field(default=None, ge=1)
    subject_template: str | None = None
    body_template: str | None = None

    @field_validator("provider_config_id", mode="before")
    @classmethod
    def decode_provider_id(cls, value: object) -> object:
        if isinstance(value, str):
            return UUID(value)
        return value

    def to_storage(self) -> dict[str, JsonValue]:
        """Serialize only supplied keys, with UUIDs represented as JSON strings."""
        return self.model_dump(mode="json", exclude_unset=True)


type CampaignChannelConfig = EmptyCampaignChannelConfig | EmailCampaignChannelConfig


def decode_campaign_channel_config(
    channel: CampaignChannel | str, value: object
) -> CampaignChannelConfig:
    """The owning channel selects the model; unrelated settings cannot select it."""
    channel = CampaignChannel(channel)
    if isinstance(value, (EmptyCampaignChannelConfig, EmailCampaignChannelConfig)):
        value = value.to_storage()
    if value is None:
        value = {}
    if channel is CampaignChannel.EMAIL:
        return EmailCampaignChannelConfig.model_validate(value)
    return EmptyCampaignChannelConfig.model_validate(value)


class CampaignChannelFields(BaseModel):
    """A complete campaign projection validates config against its owning channel."""

    channel: CampaignChannel = CampaignChannel.VOICE
    channel_config: CampaignChannelConfig = Field(
        default_factory=EmptyCampaignChannelConfig
    )

    @model_validator(mode="after")
    def validate_channel_settings(self) -> Self:
        self.channel_config = decode_campaign_channel_config(
            self.channel, self.channel_config
        )
        return self
