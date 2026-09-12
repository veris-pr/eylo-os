"""Validated carrier callback values; raw signed input is never reconstructed."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.common.contracts.telephony import CallStatus


class CallbackIdentity(BaseModel):
    """Only the carrier call reference is inspected before authentication."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    call_sid: str = Field(min_length=1)

    @field_validator("call_sid")
    @classmethod
    def _nonblank_reference(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Provider call reference must not be blank.")
        return value


class StatusCallback(CallbackIdentity):
    """Normalized carrier observation, not authority to update a call."""

    status: CallStatus | None
    provider_status: str
    duration_seconds: int | None = Field(default=None, ge=0)


class CallbackFields(CallbackIdentity):
    """Consumed status fields; vendor schemas declare their wire aliases."""

    provider_status: str = ""
    duration_seconds: int | None = Field(default=None, ge=0)

    @field_validator("duration_seconds", mode="before")
    @classmethod
    def _seconds(cls, value: object) -> object:
        """Form seconds may be decimal text; never truncate a float or a flag."""
        if value == "":
            return None
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value

    def normalized(self, status: CallStatus | None) -> StatusCallback:
        return StatusCallback(
            call_sid=self.call_sid,
            status=status,
            provider_status=self.provider_status,
            duration_seconds=self.duration_seconds,
        )
