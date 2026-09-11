"""Jira webhook wire contracts; no source authority or HTTP I/O."""

import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorWebhookPayloadError,
    SorWebhookVerificationError,
)

JIRA_WEBHOOK_RECOVERY_PAGE_SIZE = 100
JIRA_WEBHOOK_RECOVERY_START = 0
JIRA_WEBHOOK_IDENTIFIER_MAX_LENGTH = 512
JIRA_WEBHOOK_EVENT_MAX_LENGTH = 256
JIRA_WEBHOOK_DELIVERY_HEADER = "x-atlassian-webhook-identifier"
JIRA_WEBHOOK_TIMESTAMP_MILLISECONDS = 1000
JIRA_WEBHOOK_FUTURE_TOLERANCE = timedelta(minutes=5)


class JiraWebhookEventFamily(StrEnum):
    """Open-ended native event families supported by exact-record resolution."""

    ISSUE = "jira:issue_"
    COMMENT = "comment_"
    SPRINT = "sprint_"


class JiraWebhookEvent(StrEnum):
    """Events requested by this adapter, not a closed list of vendor deliveries."""

    ISSUE_CREATED = "jira:issue_created"
    ISSUE_UPDATED = "jira:issue_updated"
    ISSUE_DELETED = "jira:issue_deleted"
    COMMENT_CREATED = "comment_created"
    COMMENT_UPDATED = "comment_updated"
    COMMENT_DELETED = "comment_deleted"
    SPRINT_CREATED = "sprint_created"
    SPRINT_UPDATED = "sprint_updated"
    SPRINT_CLOSED = "sprint_closed"
    SPRINT_DELETED = "sprint_deleted"
    SPRINT_STARTED = "sprint_started"


class JiraWebhookWire(BaseModel):
    """Validate consumed fields without retaining unknown vendor data."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


def _normalize_delivery_identifier(value: object) -> str:
    """Native IDs may be strings or integers, never JSON booleans."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Webhook identifier must be a string or integer.")
    return str(value).strip()


JiraWebhookIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=JIRA_WEBHOOK_IDENTIFIER_MAX_LENGTH),
    BeforeValidator(_normalize_delivery_identifier),
]


class JiraWebhookRecordReference(JiraWebhookWire):
    id: JiraWebhookIdentifier


class JiraWebhookDelivery(JiraWebhookWire):
    """Only routing metadata is retained; issue bodies and user details are ignored."""

    webhookEvent: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=JIRA_WEBHOOK_EVENT_MAX_LENGTH,
        ),
    ]
    matchedWebhookIds: list[JiraWebhookIdentifier] = Field(min_length=1)
    timestamp: int | float | None = Field(default=None, allow_inf_nan=False)
    issue: JiraWebhookRecordReference | None = None
    comment: JiraWebhookRecordReference | None = None
    sprint: JiraWebhookRecordReference | None = None


def parse_jira_webhook_body[Model: JiraWebhookWire](
    body: bytes,
    model: type[Model],
    *,
    error_type: type[SorWebhookPayloadError] | type[SorWebhookVerificationError] = (
        SorWebhookPayloadError
    ),
) -> Model:
    """Keep JSON parsing at the wire boundary and preserve ingress error categories."""
    try:
        return model.model_validate(json.loads(body))
    except (UnicodeDecodeError, ValueError) as error:
        raise error_type("Jira webhook body is invalid.") from error


class JiraWebhookDetails(JiraWebhookWire):
    events: tuple[JiraWebhookEvent, ...]
    jqlFilter: str


class JiraWebhookRegistrationRequest(JiraWebhookWire):
    url: str
    webhooks: tuple[JiraWebhookDetails, ...]


class JiraWebhookIdsRequest(JiraWebhookWire):
    """IDs are already resolved from the source-owned subscription by the adapter."""

    webhookIds: tuple[int, ...]


class JiraWebhookListQuery(JiraWebhookWire):
    startAt: int = JIRA_WEBHOOK_RECOVERY_START
    maxResults: int = JIRA_WEBHOOK_RECOVERY_PAGE_SIZE


class JiraWebhookRegistrationResult(JiraWebhookWire):
    createdWebhookId: str | int | None = None
    errors: list[str] | None = Field(default=None, repr=False)

    @field_validator("errors")
    @classmethod
    def validate_errors(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            any(not item for item in value) or len(set(value)) != len(value)
        ):
            raise ValueError("Webhook errors must be unique nonempty strings.")
        return value


class JiraWebhookRegistrationResponse(JiraWebhookWire):
    webhookRegistrationResult: list[JiraWebhookRegistrationResult]


class JiraWebhookRecord(JiraWebhookWire):
    """Native metadata; source matching and stale-registration policy stay in the adapter."""

    id: str | int | None = None
    url: str | None = None
    events: list[str] | None = None
    jqlFilter: str | None = None
    expirationDate: str | datetime | None = None

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            any(not item for item in value) or len(set(value)) != len(value)
        ):
            raise ValueError("Webhook events must be unique nonempty strings.")
        return value


class JiraWebhookPage(JiraWebhookWire):
    # Native pagination is an intrinsic predicate, not an Eylo lifecycle mode.
    isLast: bool
    values: list[JiraWebhookRecord]


class JiraWebhookRenewalResponse(JiraWebhookWire):
    expirationDate: str | datetime


def parse_jira_webhook_response[Model: JiraWebhookWire](
    value: object, model: type[Model]
) -> Model:
    """Translate structural failures without exposing vendor payloads or credentials."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "Jira webhook response metadata is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
