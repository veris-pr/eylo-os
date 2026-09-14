"""Vendor-neutral reranking types.

Retrieval embeds a query and a document independently. A reranker scores the
pair together, so it reorders over-fetched retrieval candidates rather than
replacing retrieval.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RankingState(StrEnum):
    NOT_REQUESTED = "not_requested"
    APPLIED = "applied"
    DEGRADED = "degraded"


class RankingReason(StrEnum):
    """Content-free explanations owned by the retrieval pipeline."""

    CANDIDATE_BUDGET_EXCEEDED = "candidate_budget_exceeded"
    CANDIDATE_CONTENT_BUDGET_EXCEEDED = "candidate_content_budget_exceeded"
    CONFIGURATION_UNAVAILABLE = "configuration_unavailable"
    NO_CANDIDATES = "no_candidates"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_AUTHENTICATION_FAILED = "provider_authentication_failed"
    PROVIDER_REJECTED_REQUEST = "provider_rejected_request"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"


class RerankingErrorCode(StrEnum):
    """Normalized adapter failures, separate from each vendor's native codes."""

    PROVIDER_ERROR = "provider_error"
    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    CANDIDATE_LIMIT = "candidate_limit"


class RerankingRecovery(StrEnum):
    """Whether another invocation may recover; this does not schedule a retry."""

    TERMINAL = "terminal"
    RETRY = "retry"


class RerankingTruncation(StrEnum):
    """The adapter's established handling of overlong candidate text."""

    ALLOWED = "allowed"
    DISABLED = "disabled"


class RankingMetadata(BaseModel):
    """Visible outcome of the optional reranking stage."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    state: RankingState
    comparable: bool
    reason: RankingReason | None = None
    provider: str | None = None
    provider_config_id: UUID | None = None
    provider_config_revision: int | None = Field(default=None, gt=0)
    candidate_count: int = Field(ge=0)
    returned_count: int = Field(ge=0)


class RerankResult(BaseModel):
    """One candidate's placement.

    Carries the **index into the caller's list**, not the text. The caller
    already holds the full objects — content, source, scope, which
    knowledgebase it came from — and shuttling those through a vendor and back
    would mean reconstructing them by string matching on the way out.
    """

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True,
    )

    index: int = Field(ge=0)
    score: float = Field(allow_inf_nan=False)


class RerankingCapabilities(BaseModel):
    """What a vendor actually does, stated rather than discovered."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )

    max_documents: int = Field(gt=0)
    truncation: RerankingTruncation

    @property
    def truncates(self) -> bool:
        """Compatibility predicate; adapters declare the named policy."""
        return self.truncation is RerankingTruncation.ALLOWED


class RerankingConfig(BaseModel):
    """What a vendor needs to run."""

    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always",
        hide_input_in_errors=True,
    )

    model: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=1, max_length=8192, repr=False, exclude=True)
    base_url: str | None = Field(default=None, max_length=2048)

    @field_validator("model", "api_key")
    @classmethod
    def validate_single_line(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(character in normalized for character in "\x00\r\n"):
            raise ValueError("Value must be a non-empty single-line string.")
        return normalized


class RerankingError(Exception):
    """Normalized failure; optional reranking still falls back without retrying."""

    def __init__(
        self,
        message: str,
        *,
        code: RerankingErrorCode = RerankingErrorCode.PROVIDER_ERROR,
        vendor: str | None = None,
        recovery: RerankingRecovery = RerankingRecovery.TERMINAL,
    ) -> None:
        if not isinstance(code, RerankingErrorCode):
            raise TypeError("Reranking error code must be a RerankingErrorCode.")
        if not isinstance(recovery, RerankingRecovery):
            raise TypeError("Reranking recovery must be a RerankingRecovery.")
        super().__init__(message)
        self.code = code
        self.vendor = vendor
        self.recovery = recovery

    @property
    def retryable(self) -> bool:
        """Read-only compatibility projection of the recovery policy."""
        return self.recovery is RerankingRecovery.RETRY
