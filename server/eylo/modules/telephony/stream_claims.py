"""Signed media-stream claims owned by telephony, independent of carrier wire formats."""

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from eylo.modules.telephony.provider_config_domain import TelephonyProvider
from eylo.modules.telephony.schemas import CallDirection


class MediaStreamClaims(BaseModel):
    """Authenticated token body; serialization preserves the existing signature format."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    provider: TelephonyProvider
    call_id: str
    organization_id: str
    agent_id: str
    agent_revision: int = Field(gt=0)
    provider_config_id: str
    provider_config_revision: int = Field(gt=0)
    direction: CallDirection
    call_sid: str = ""
    initial_message: str = Field(default="", repr=False)
    exp: int

    @field_validator("direction", mode="before")
    @classmethod
    def _parse_direction(cls, value: object) -> CallDirection:
        if isinstance(value, CallDirection):
            return value
        if isinstance(value, str):
            return CallDirection(value.lower())
        raise ValueError("Media stream direction must be inbound or outbound.")

    @field_serializer("direction")
    def _serialize_direction(self, value: CallDirection) -> str:
        return value.value.upper()
