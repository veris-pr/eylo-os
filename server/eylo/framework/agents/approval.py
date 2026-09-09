"""Human approval contracts for risky framework actions."""

from __future__ import annotations

from enum import Enum
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, JsonValue, StrictStr

from .common import FrozenFrameworkModel, JsonObject


class ApprovalActionKind(str, Enum):
    """Action families that may require approval."""

    TOOL_CALL = "tool_call"
    SANDBOX_COMMAND = "sandbox_command"
    NETWORK_ACCESS = "network_access"
    FILE_WRITE = "file_write"
    EXTERNAL_API_CALL = "external_api_call"
    HANDOFF = "handoff"


class RiskLevel(str, Enum):
    """Risk level assigned by policy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalRequestStatus(str, Enum):
    """Lifecycle of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalDecisionKind(str, Enum):
    """Decision made by a user or admin."""

    APPROVE = "approve"
    REJECT = "reject"


class ApprovalRequest(FrozenFrameworkModel):
    """Permission request for one concrete risky action."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    id: UUID = Field(default_factory=uuid4)
    durable_run_id: UUID
    requested_by_agent_id: UUID | None = None
    action_kind: ApprovalActionKind
    action_summary: StrictStr
    action_payload_redacted: dict[str, JsonValue] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    policy_reason: StrictStr
    expires_at: str | None = None
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    resume_checkpoint_id: UUID | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ApprovalDecision(FrozenFrameworkModel):
    """User/admin decision for an approval request."""

    approval_request_id: UUID
    decided_by: UUID | str
    decision: ApprovalDecisionKind
    comment: str | None = None
    approved_payload_override: JsonObject | None = None
