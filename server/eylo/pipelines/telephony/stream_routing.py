"""Untrusted query routing decoded before telephony's signed authority checks."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.sockets.telephony.base import TelephonyCallDirection


class RoutingQueryKey(StrEnum):
    ORGANIZATION = "org_id"
    CALL = "call_id"
    AGENT = "agent_id"
    AGENT_REVISION = "agent_revision"
    PROVIDER_CONFIG = "provider_config_id"
    PROVIDER_CONFIG_REVISION = "provider_config_revision"
    DIRECTION = "direction"
    INITIAL_MESSAGE = "initial_message"


class MediaStreamRouting(BaseModel):
    """Transport values only; a valid shape does not authorize any referenced row."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    organization_id: UUID | None = Field(default=None, validation_alias="org_id")
    call_id: UUID | None = None
    agent_id: UUID | None = None
    agent_revision: int | None = Field(default=None, gt=0, strict=True)
    provider_config_id: UUID | None = None
    provider_config_revision: int | None = Field(default=None, gt=0, strict=True)
    direction: TelephonyCallDirection | None = None
    initial_message: str | None = Field(default=None, repr=False, exclude=True)
    stream_token: str | None = Field(default=None, repr=False, exclude=True)

    @field_validator(
        "organization_id",
        "call_id",
        "agent_id",
        "agent_revision",
        "provider_config_id",
        "provider_config_revision",
        "direction",
        mode="before",
    )
    @classmethod
    def _empty_identifier(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("direction", mode="before")
    @classmethod
    def _direction(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("agent_revision", "provider_config_revision", mode="before")
    @classmethod
    def _revision(cls, value: object) -> object:
        if isinstance(value, str):
            return int(value) if value else None
        return value
