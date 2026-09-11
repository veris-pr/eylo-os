"""Linear-native webhook metadata; authentication precedes payload validation."""

import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from eylo.sor.shared.contracts import (
    SorWebhookPayloadError,
    SorWebhookVerificationError,
)

LINEAR_SIGNATURE_HEX_LENGTH = 64
LINEAR_WEBHOOK_REPLAY_WINDOW_MS = 60_000
LINEAR_MILLISECONDS_PER_SECOND = 1_000
LINEAR_WEBHOOK_ID_MAX_LENGTH = 512
LINEAR_WEBHOOK_LABEL_MAX_LENGTH = 256
LINEAR_DOCUMENT_STREAM = "documents"


class LinearWebhookHeader(StrEnum):
    """Native header names, compared case-insensitively by the adapter."""

    SIGNATURE = "linear-signature"
    TIMESTAMP = "linear-timestamp"
    DELIVERY = "linear-delivery"


class LinearWebhookEntity(StrEnum):
    """Recognized routing names, not a restriction on future vendor events."""

    ISSUE = "Issue"
    COMMENT = "Comment"
    PROJECT = "Project"
    ISSUE_RELATION = "IssueRelation"
    ISSUE_LABEL = "IssueLabel"
    CYCLE = "Cycle"
    USER = "User"
    DOCUMENT = "Document"


class LinearWebhookModel(BaseModel):
    """Keep only consumed metadata; never retain actor or document content."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
    )


class LinearWebhookTimestamp(LinearWebhookModel):
    """Authenticated delivery time in milliseconds; booleans are not integers."""

    webhook_timestamp: int = Field(alias="webhookTimestamp")


LinearWebhookId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=LINEAR_WEBHOOK_ID_MAX_LENGTH
    ),
]
LinearWebhookLabel = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=LINEAR_WEBHOOK_LABEL_MAX_LENGTH
    ),
]


class LinearWebhookRecord(LinearWebhookModel):
    """Identity hint for refetch; missing identity is valid only for unknown events."""

    id: LinearWebhookId | None = None


def _creation_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Linear creation time must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _fallback_timestamp(value: object) -> int | None:
    # Authentication independently requires this integer. Parsing keeps the
    # established precedence: a valid createdAt does not need the fallback.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class LinearWebhookPayload(LinearWebhookModel):
    """Routing metadata; event/action names stay open for unsupported event kinds."""

    organization_id: LinearWebhookLabel = Field(alias="organizationId")
    action: LinearWebhookLabel
    type: LinearWebhookLabel
    data: LinearWebhookRecord | None = None
    created_at: Annotated[AwareDatetime | None, BeforeValidator(_creation_time)] = (
        Field(default=None, alias="createdAt")
    )
    webhook_timestamp: Annotated[int | None, BeforeValidator(_fallback_timestamp)] = (
        Field(default=None, alias="webhookTimestamp")
    )

    @property
    def occurred_at(self) -> datetime:
        """Prefer vendor event time; malformed date strings never fall back."""
        if self.created_at is not None:
            return self.created_at
        if self.webhook_timestamp is None:
            raise SorWebhookPayloadError("Linear webhook timestamp is invalid.")
        try:
            return datetime.fromtimestamp(
                self.webhook_timestamp / LINEAR_MILLISECONDS_PER_SECOND, tz=timezone.utc
            )
        except (OverflowError, OSError, ValueError) as error:
            raise SorWebhookPayloadError(
                "Linear webhook timestamp is invalid."
            ) from error


def parse_linear_webhook_model[Model: BaseModel](
    body: bytes,
    model: type[Model],
    *,
    error_type: type[SorWebhookVerificationError] | type[SorWebhookPayloadError],
) -> Model:
    """Decode at the wire boundary, preserving safe verification/payload errors."""
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise error_type("Linear webhook body is not valid JSON.") from error
    if not isinstance(value, dict):
        raise error_type("Linear webhook body must be an object.")
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise error_type("Linear webhook metadata is invalid.") from error
