"""Canonical result projections joining framework outcomes to product runs."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from eylo.common.contracts.background_task import ParallelTaskKind
from eylo.common.contracts.messages import RequestStatus
from eylo.framework.agents.model import ModelUsage
from eylo.framework.agents.result import RunStatus


class AgentRunResultKind(StrEnum):
    """Stable wire names of the non-conversation result envelopes."""

    OBJECTIVE = "objective"
    SCHEDULED = "scheduled_agent"
    PARALLEL_TASK = "parallel_task"


class ObjectiveRunSummary(BaseModel):
    """One framework turn's objective output, before canonical storage."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[AgentRunResultKind.OBJECTIVE] = AgentRunResultKind.OBJECTIVE
    agent_run_id: UUID
    framework_run_id: UUID
    framework_status: RunStatus
    output: JsonValue = Field(repr=False)
    usage: ModelUsage

    @field_validator("output")
    @classmethod
    def require_finite_output(cls, value: JsonValue) -> JsonValue:
        """Refuse non-finite nested values before a serializer can alter them."""
        json.dumps(value, allow_nan=False)
        return value


class ObjectiveExhaustionSummary(BaseModel):
    """Bounds reached before a framework turn exists; no invented usage or ID."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[AgentRunResultKind.OBJECTIVE] = AgentRunResultKind.OBJECTIVE
    output: None = None
    agent_run_id: UUID


class ScheduledRunSummary(BaseModel):
    """Framework result for the exact immutable schedule occurrence."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[AgentRunResultKind.SCHEDULED] = AgentRunResultKind.SCHEDULED
    schedule_run_id: UUID
    framework_run_id: UUID
    framework_status: RunStatus
    output: str | None = Field(repr=False)
    usage: ModelUsage


class ParallelTaskRunSummary(BaseModel):
    """Worker outcome with message identities; no framework turn is invented."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", hide_input_in_errors=True
    )

    kind: Literal[AgentRunResultKind.PARALLEL_TASK] = AgentRunResultKind.PARALLEL_TASK
    task_message_id: UUID
    task_status: Literal[RequestStatus.COMPLETED, RequestStatus.SKIPPED]
    worker_type: ParallelTaskKind
    model_used: str
    iterations_used: int = Field(ge=0)
    output: str = Field(repr=False)
    task_result_message_id: UUID | None = None

    def with_result_message(self, message_id: UUID) -> ParallelTaskRunSummary:
        """Bind the newly persisted message through validated reconstruction."""
        return ParallelTaskRunSummary(
            task_message_id=self.task_message_id,
            task_status=self.task_status,
            worker_type=self.worker_type,
            model_used=self.model_used,
            iterations_used=self.iterations_used,
            output=self.output,
            task_result_message_id=message_id,
        )
