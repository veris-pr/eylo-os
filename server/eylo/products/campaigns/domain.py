"""Campaign definition errors, references, and read-only preparation values."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
)

from eylo.common.contracts.telephony import CallEndedReason
from eylo.common.revisions import DefinitionRef, DefinitionRevisionError
from eylo.products.campaigns.constants import CampaignChannel

RETRY_BACKOFF_MULTIPLIER = 2

_CAMPAIGN_VARIABLES = TypeAdapter(
    dict[str, JsonValue], config=ConfigDict(strict=True, allow_inf_nan=False)
)


def validate_campaign_variables(value: object) -> dict[str, JsonValue]:
    """Copy JSON-only custom variables before storage or template consumption."""
    return _CAMPAIGN_VARIABLES.validate_python(value)


CampaignVariables = Annotated[
    dict[str, JsonValue], BeforeValidator(validate_campaign_variables)
]


class CampaignScheduleConfig(BaseModel):
    """Reserved window settings; V1 stores these but does not enforce a schedule."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    time_window_start: str | None = None
    time_window_end: str | None = None
    timezone: str | None = None

    def to_storage(self) -> dict[str, JsonValue]:
        """Preserve partial/empty settings without inventing runtime defaults."""
        return self.model_dump(mode="json", exclude_unset=True)


def campaign_schedule_config_for_create(
    config: CampaignScheduleConfig | None,
) -> CampaignScheduleConfig:
    """Retain the historical stored create value for omitted/null/empty settings."""
    if config is not None and config.model_fields_set:
        return CampaignScheduleConfig.model_validate(config)
    return CampaignScheduleConfig(
        time_window_start="09:00", time_window_end="18:00", timezone="UTC"
    )


class CampaignRetryPolicy(BaseModel):
    """Pinned retry settings; empty reasons match every unsuccessful outcome."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    max_retries: int = Field(default=0, ge=0)
    backoff_seconds: int = Field(default=0, ge=0)
    retry_on: tuple[str, ...] = ()

    @field_validator("retry_on", mode="before")
    @classmethod
    def decode_stored_reasons(cls, value: object) -> object:
        """JSON lists and legacy null represent the same immutable reason set."""
        if value is None:
            return ()
        if isinstance(value, list):
            return tuple(value)
        return value

    def allows_retry(self, *, attempt_number: int, outcome: str) -> bool:
        """Attempt one is the initial send, not the first retry."""
        return attempt_number <= self.max_retries and (
            not self.retry_on or outcome in self.retry_on
        )

    def delay_seconds(self, *, attempt_number: int) -> int:
        """Keep the existing exponential backoff for the completed attempt."""
        return self.backoff_seconds * (
            RETRY_BACKOFF_MULTIPLIER ** max(attempt_number - 1, 0)
        )

    def to_storage(self) -> dict[str, JsonValue]:
        """Keep the JSONB/wire keys explicit; no runtime model leaks into ORM state."""
        return {
            "max_retries": self.max_retries,
            "backoff_seconds": self.backoff_seconds,
            "retry_on": list(self.retry_on),
        }


def campaign_retry_policy_for_create(
    *, channel: CampaignChannel, policy: CampaignRetryPolicy | None
) -> CampaignRetryPolicy:
    """Preserve create's channel policy for omitted/null/empty config only."""
    if policy is not None and policy.model_fields_set:
        return CampaignRetryPolicy.model_validate(policy)
    if channel is CampaignChannel.VOICE:
        return CampaignRetryPolicy(
            max_retries=2,
            backoff_seconds=300,
            retry_on=(
                CallEndedReason.CUSTOMER_BUSY.value,
                CallEndedReason.CUSTOMER_DID_NOT_ANSWER.value,
                CallEndedReason.VOICEMAIL_DETECTED.value,
                CallEndedReason.ERROR_SYSTEM.value,
                CallEndedReason.ERROR_PROVIDER_DISCONNECTED.value,
            ),
        )
    if channel is CampaignChannel.EMAIL:
        return CampaignRetryPolicy(
            max_retries=1, backoff_seconds=3600, retry_on=("bounced", "deferred")
        )
    if channel is CampaignChannel.WIDGET:
        return CampaignRetryPolicy()
    raise ValueError("Unsupported campaign retry channel.")


class CampaignDefinitionError(DefinitionRevisionError):
    """Base error for immutable campaign definition commands."""


class CampaignConflictError(CampaignDefinitionError):
    """A campaign command conflicts with its current immutable revision."""


class CampaignNotFoundError(CampaignDefinitionError):
    """No campaign or exact revision is reachable in caller scope."""


def campaign_message_template_ref(
    template_id: UUID | None, revision: int | None
) -> DefinitionRef | None:
    """Decode the optional persisted pair without selecting a latest revision."""
    if template_id is None and revision is None:
        return None
    if template_id is None or revision is None:
        raise CampaignDefinitionError(
            "Campaign template identity and revision must be present together."
        )
    return DefinitionRef(definition_id=template_id, revision=revision)


class CampaignPreparationIssueLevel(StrEnum):
    """Whether an issue is informational or prevents new work."""

    WARNING = "warning"
    BLOCKER = "blocker"


class CampaignPreparationIssueCode(StrEnum):
    """Stable UI-facing campaign preparation facts."""

    POLICY_NOT_EVALUATED = "policy_not_evaluated"
    PREFERENCES_NOT_ENFORCED = "preferences_not_enforced"
    INVALID_CHANNEL_ADDRESS = "invalid_channel_address"
    CONTACT_DELETION_PENDING = "contact_deletion_pending"


class CampaignPreparationIssue(BaseModel):
    """One aggregate preparation issue without contact PII."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    code: CampaignPreparationIssueCode
    level: CampaignPreparationIssueLevel
    affected_contacts: int = Field(ge=0)


class CampaignPreparation(BaseModel):
    """Read-only summary; it never selects or filters the audience."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", revalidate_instances="always"
    )

    selected_contacts: int = Field(ge=0)
    issues: tuple[CampaignPreparationIssue, ...]

    @property
    def warning_facts(self) -> int:
        return sum(
            issue.affected_contacts
            for issue in self.issues
            if issue.level is CampaignPreparationIssueLevel.WARNING
        )

    @property
    def blocking_facts(self) -> int:
        return sum(
            issue.affected_contacts
            for issue in self.issues
            if issue.level is CampaignPreparationIssueLevel.BLOCKER
        )


__all__ = [
    "CampaignConflictError",
    "CampaignDefinitionError",
    "CampaignNotFoundError",
    "CampaignPreparation",
    "CampaignPreparationIssue",
    "CampaignPreparationIssueCode",
    "CampaignPreparationIssueLevel",
    "CampaignRetryPolicy",
    "CampaignScheduleConfig",
]
