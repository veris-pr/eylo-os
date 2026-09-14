"""Typed tool pauses shared by runner observations and continuation snapshots."""

from enum import Enum
from typing import Literal

from pydantic import ConfigDict

from .approval import ApprovalRequest
from .common import FrameworkMetadata, FrozenFrameworkModel
from .durable import InputRequestDetails
from .tool import ToolIdentity


class ToolContinuationKind(str, Enum):
    """Reason the same tool invocation must resume after a human response."""

    APPROVAL = "tool_approval"
    INPUT = "tool_input"


class ToolApprovalContinuation(FrozenFrameworkModel):
    """Resume identity for an approval-gated call, not a new invocation."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    type: Literal[ToolContinuationKind.APPROVAL] = ToolContinuationKind.APPROVAL
    tool_call_id: ToolIdentity


class ToolInputContinuation(FrozenFrameworkModel):
    """Resume identity for a call awaiting information."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    type: Literal[ToolContinuationKind.INPUT] = ToolContinuationKind.INPUT
    tool_call_id: ToolIdentity


class ToolInputRequestMetadata(FrameworkMetadata):
    """Executor-produced question; the runner adds the exact continuation."""

    input_request: InputRequestDetails


class RunApprovalInterruption(FrameworkMetadata):
    """Approval request and exact continuation, with no live runtime resources."""

    model_config = ConfigDict(
        extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    approval_request: ApprovalRequest
    continuation: ToolApprovalContinuation


class RunInputInterruption(FrameworkMetadata):
    """Input request and exact continuation, before product persistence adds IDs."""

    model_config = ConfigDict(
        extra="forbid", revalidate_instances="always", hide_input_in_errors=True
    )

    input_request: InputRequestDetails
    continuation: ToolInputContinuation
