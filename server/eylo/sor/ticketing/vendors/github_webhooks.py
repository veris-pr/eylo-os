"""GitHub repository-webhook wire contracts, separate from canonical ticketing tools."""

import json
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_serializer,
)

from eylo.sor.shared.contracts import (
    SorRecoveryPolicy,
    SorVendorErrorCode,
    SorVendorOperationError,
    SorWebhookPayloadError,
    SorWebhookVerificationError,
)
from eylo.sor.shared.json_values import SorJsonValue

GITHUB_WEBHOOK_PAGE_SIZE = 100
GITHUB_WEBHOOK_FIRST_PAGE = 1
GITHUB_WEBHOOK_RECOVERY_MAX_PAGES = 10
GITHUB_WEBHOOK_EVENT_HEADER = "x-github-event"
GITHUB_WEBHOOK_DELIVERY_HEADER = "x-github-delivery"
GITHUB_WEBHOOK_SIGNATURE_HEADER = "x-hub-signature-256"
GITHUB_WEBHOOK_HEADER_MAX_LENGTH = 512
GITHUB_WEBHOOK_NO_ACTION = "received"


class GitHubWebhookEvent(StrEnum):
    ISSUE_COMMENT = "issue_comment"
    ISSUES = "issues"
    LABEL = "label"
    MILESTONE = "milestone"
    REPOSITORY = "repository"


class GitHubWebhookName(StrEnum):
    WEB = "web"


class GitHubWebhookContentType(StrEnum):
    JSON = "json"


class GitHubWebhookTlsMode(StrEnum):
    VERIFY = "0"


class GitHubWebhookWire(BaseModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="ignore", hide_input_in_errors=True
    )


class GitHubWebhookRepository(GitHubWebhookWire):
    full_name: str | None = None


class GitHubWebhookIssue(GitHubWebhookWire):
    number: int | None = None
    updated_at: str | None = None
    pull_request: GitHubWebhookWire | None = None

    @property
    def is_pull_request(self) -> bool:
        """Presence, including JSON null, excludes pull requests from issue sync."""
        return "pull_request" in self.model_fields_set

    @model_serializer
    def serialize_identity(self) -> dict[str, SorJsonValue]:
        """Keep absence distinct from null during snapshot restoration."""
        result: dict[str, SorJsonValue] = {
            "number": self.number,
            "updated_at": self.updated_at,
        }
        if self.is_pull_request:
            result["pull_request"] = {} if self.pull_request is not None else None
        return result


class GitHubWebhookComment(GitHubWebhookWire):
    id: int | None = None
    updated_at: str | None = None


class GitHubWebhookLabel(GitHubWebhookWire):
    name: str | None = None


class GitHubWebhookMilestone(GitHubWebhookWire):
    number: int | None = None
    updated_at: str | None = None


class GitHubWebhookDelivery(GitHubWebhookWire):
    """Routing projection only; actions remain open to future vendor additions."""

    action: str | None = None
    repository: GitHubWebhookRepository | None = None
    issue: GitHubWebhookIssue | None = None
    comment: GitHubWebhookComment | None = None
    label: GitHubWebhookLabel | None = None
    milestone: GitHubWebhookMilestone | None = None


def parse_github_webhook_body[Model: GitHubWebhookWire](
    body: bytes,
    model: type[Model],
    *,
    error_type: type[SorWebhookPayloadError] | type[SorWebhookVerificationError] = (
        SorWebhookPayloadError
    ),
) -> Model:
    """Decode after HMAC verification; structural metadata errors retain their category."""
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, ValueError) as error:
        raise error_type("GitHub webhook payload is invalid.") from error
    if not isinstance(value, dict):
        raise error_type("GitHub webhook payload is invalid.")
    return parse_github_webhook_response(value, model)


class GitHubWebhookConfig(GitHubWebhookWire):
    url: str
    content_type: GitHubWebhookContentType = GitHubWebhookContentType.JSON
    insecure_ssl: GitHubWebhookTlsMode = GitHubWebhookTlsMode.VERIFY
    secret: str = Field(repr=False, exclude=True)

    def to_vendor_payload(self) -> dict[str, SorJsonValue]:
        """Only the explicit outbound serialization may reveal the signing secret."""
        return self.model_dump(mode="json") | {"secret": self.secret}


class GitHubWebhookCreateRequest(GitHubWebhookWire):
    name: GitHubWebhookName = GitHubWebhookName.WEB
    # Native GitHub API predicate, not a platform capability switch.
    active: bool = True
    events: tuple[GitHubWebhookEvent, ...]
    config: GitHubWebhookConfig

    def to_vendor_payload(self) -> dict[str, SorJsonValue]:
        return self.model_dump(mode="json") | {
            "config": self.config.to_vendor_payload()
        }


class GitHubWebhookListQuery(GitHubWebhookWire):
    per_page: int = GITHUB_WEBHOOK_PAGE_SIZE
    page: int = Field(default=GITHUB_WEBHOOK_FIRST_PAGE, ge=GITHUB_WEBHOOK_FIRST_PAGE)


class GitHubWebhookLocation(GitHubWebhookWire):
    url: str | None = None


class GitHubWebhookRecord(GitHubWebhookWire):
    id: int | None = None
    active: bool | None = None
    events: list[str] | None = None
    config: GitHubWebhookLocation | None = None


class GitHubWebhookList(RootModel[list[GitHubWebhookRecord]]):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)


def parse_github_webhook_response[Model: BaseModel](
    value: object, model: type[Model]
) -> Model:
    """Structural errors never retain or echo the remote response."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise SorVendorOperationError(
            SorVendorErrorCode.VENDOR_RESPONSE_INVALID,
            "GitHub webhook response metadata is invalid.",
            recovery=SorRecoveryPolicy.TERMINAL,
        ) from error
