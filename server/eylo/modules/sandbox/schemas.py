"""Request and response shapes for AgentRun objectives and sandbox sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from eylo.common.contracts.sandbox import SandboxAccess, SandboxState
from eylo.modules.sandbox.policy import SandboxWorkspacePolicy
from eylo.modules.sandbox.run_context import OBJECTIVE_MAX_STEPS


class ObjectiveCreate(BaseModel):
    """Starting long-running work.

    Both bounds are here and both are required to have a value, because an
    objective with neither runs until someone notices. `max_steps` stops one
    that loops; `deadline` stops one that is merely slow, and they catch
    different failures.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    goal: str = Field(
        min_length=1,
        description=(
            "What the agent is to achieve, in your words. Kept verbatim — it is "
            "the one thing that must not drift as the work goes on."
        ),
    )
    max_steps: int = Field(ge=1, le=OBJECTIVE_MAX_STEPS)
    deadline: datetime


class SandboxPolicyRead(BaseModel):
    """Flat public policy projection; validation remains with workspace policy."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    endpoint: str
    image: str
    memory_mb: int
    cpu_cores: float
    disk_mb: int
    pids: int
    ttl_seconds: int
    command_timeout_seconds: int
    max_output_bytes: int
    max_sessions: int
    network: Literal[False]
    verified_image_id: str
    grant_max_sessions: int | None


class SandboxSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    provider: str
    image: str
    sandbox_provider_config_id: uuid.UUID
    sandbox_provider_config_revision: int
    grant_id: uuid.UUID | None
    grant_revision: int | None
    effective_policy: SandboxWorkspacePolicy
    state: SandboxState
    agent_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    workspace: str
    expires_at: datetime
    last_used_at: datetime | None
    created_at: datetime
    # Deliberately absent: `vendor_id`. It is the container id, and an operator
    # who has it can reach the workspace outside everything this module
    # enforces. The kill switch is a route here, not a docker command.

    @field_validator("effective_policy", mode="before")
    @classmethod
    def decode_policy(cls, value: object) -> SandboxWorkspacePolicy:
        """Read the persisted flat policy without importing runtime orchestration."""
        if isinstance(value, SandboxWorkspacePolicy):
            return value
        return SandboxWorkspacePolicy.from_storage(value)

    @field_serializer("effective_policy")
    def encode_policy(self, value: SandboxWorkspacePolicy) -> SandboxPolicyRead:
        """Preserve flat JSON and named fields in the generated API contract."""
        config = value.config
        return SandboxPolicyRead(
            endpoint=config.endpoint,
            image=config.image,
            memory_mb=config.memory_mb,
            cpu_cores=config.cpu_cores,
            disk_mb=config.disk_mb,
            pids=config.pids,
            ttl_seconds=config.ttl_seconds,
            command_timeout_seconds=config.command_timeout_seconds,
            max_output_bytes=config.max_output_bytes,
            max_sessions=config.max_sessions,
            network=config.network,
            verified_image_id=value.verified_image_id,
            grant_max_sessions=value.grant_max_sessions,
        )


class SandboxGrantCreate(BaseModel):
    """Bind an agent to one explicit ready no-egress sandbox config."""

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    sandbox_provider_config_id: uuid.UUID
    access: Literal[SandboxAccess.RUN]
    max_sessions: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=100,
        description=(
            "How many workspaces this agent may hold at once. Narrows the "
            "organization's limit; it cannot exceed it."
        ),
    )


class SandboxGrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    access: SandboxAccess
    sandbox_provider_config_id: uuid.UUID
    sandbox_provider_config_revision: int
    revision: int
    max_sessions: int | None
    created_at: datetime
