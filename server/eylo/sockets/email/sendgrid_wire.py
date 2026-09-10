"""SendGrid v3 wire contracts; native field names stop at the email adapter."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)

SENDGRID_MAIL_SEND_SCOPE = "mail.send"
_WEBHOOK_JSON = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(allow_inf_nan=False)
)


class SendGridContentType(StrEnum):
    TEXT = "text/plain"
    HTML = "text/html"


class SendGridEventKind(StrEnum):
    DELIVERED = "delivered"
    BOUNCE = "bounce"
    DROPPED = "dropped"
    DEFERRED = "deferred"
    PROCESSED = "processed"
    OPEN = "open"
    CLICK = "click"
    SPAM_REPORT = "spamreport"
    UNSUBSCRIBE = "unsubscribe"
    GROUP_UNSUBSCRIBE = "group_unsubscribe"
    GROUP_RESUBSCRIBE = "group_resubscribe"


class _SendGridRequest(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_by_name=True,
        validate_by_alias=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class SendGridAddress(_SendGridRequest):
    email: EmailStr
    name: str | None = None


class SendGridCustomArguments(_SendGridRequest):
    eylo_attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class SendGridPersonalization(_SendGridRequest):
    to: tuple[SendGridAddress, ...] = Field(min_length=1)
    custom_args: SendGridCustomArguments
    cc: tuple[SendGridAddress, ...] | None = None
    bcc: tuple[SendGridAddress, ...] | None = None
    headers: dict[str, str] | None = None


class SendGridContent(_SendGridRequest):
    type: SendGridContentType
    value: str = Field(min_length=1)


class SendGridAttachment(_SendGridRequest):
    content: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    type: str = Field(min_length=1)
    disposition: Literal["attachment"] = "attachment"


class SendGridMailRequest(_SendGridRequest):
    """Executable mail-send subset; omit absent optional fields on the wire."""

    personalizations: tuple[SendGridPersonalization, ...] = Field(min_length=1)
    sender: Annotated[SendGridAddress, Field(alias="from")]
    subject: str = Field(min_length=1)
    content: tuple[SendGridContent, ...] = Field(min_length=1)
    reply_to: SendGridAddress | None = None
    attachments: tuple[SendGridAttachment, ...] | None = None


class SendGridScopesResponse(BaseModel):
    """Only scope names are consumed; unrelated vendor additions are ignored."""

    model_config = ConfigDict(strict=True, frozen=True, extra="ignore")

    scopes: list[str] = Field(default_factory=list)


class SendGridWebhookPayload(BaseModel):
    """One parsed event, not an authenticated HTTP webhook or batch envelope.

    Optional vendor fields/custom arguments remain JSON, not arbitrary Python
    objects. Callers must authenticate the original request before using it.
    """

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="allow",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    event: SendGridEventKind
    email: EmailStr
    timestamp: int = Field(ge=0)
    sg_message_id: str = ""
    reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_json_payload(cls, value: object) -> dict[str, JsonValue]:
        """Validate extensions before Pydantic retains unknown vendor keys."""
        return _WEBHOOK_JSON.validate_python(value, strict=True)

    @field_validator("event", mode="before")
    @classmethod
    def decode_event(cls, value: object) -> object:
        return SendGridEventKind(value) if isinstance(value, str) else value
