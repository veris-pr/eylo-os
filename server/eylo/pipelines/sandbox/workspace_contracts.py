"""Typed workspace transfer values with an explicit, compatible storage boundary."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.modules.sandbox.policy import SandboxWorkspacePolicy
from eylo.modules.sandbox_configs.catalog import SandboxProviders


class WorkspaceExport(BaseModel):
    """Private archive transfer; raw bytes never enter generic snapshots or repr."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    session_id: UUID
    agent_run_id: UUID
    provider: SandboxProviders
    image: str = Field(min_length=1)
    sandbox_provider_config_id: UUID
    sandbox_provider_config_revision: int = Field(gt=0)
    grant_id: UUID | None
    grant_revision: int | None = Field(gt=0)
    effective_policy: SandboxWorkspacePolicy
    workspace_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive: bytes = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def require_paired_authority(self) -> WorkspaceExport:
        """A retained grant reference always identifies a specific revision."""
        if (self.grant_id is None) != (self.grant_revision is None):
            raise ValueError("Workspace grant identity and revision must be paired.")
        if self.image != self.effective_policy.verified_image_id:
            raise ValueError("Workspace image differs from its pinned policy.")
        return self
