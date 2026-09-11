"""Typed workspace transfer values with an explicit, compatible storage boundary."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from eylo.common.contracts.sandbox import SandboxError
from eylo.modules.sandbox_configs.catalog import SandboxProviders
from eylo.modules.sandbox_configs.domain import (
    InvalidSandboxConfig,
    SandboxExecutionSettings,
)


class SandboxWorkspacePolicy(BaseModel):
    """Pinned execution settings plus the currently authorized grant ceiling."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    config: SandboxExecutionSettings
    verified_image_id: str = Field(min_length=1)
    grant_max_sessions: int | None = Field(default=None, ge=1, le=100)

    @classmethod
    def from_storage(cls, value: object) -> SandboxWorkspacePolicy:
        """Restore the historical flat JSON shape without coercing policy limits."""
        if not isinstance(value, dict):
            raise SandboxError("Sandbox workspace policy must be an object.")
        fields = dict(value)
        verified_image_id = fields.pop("verified_image_id", None)
        grant_max_sessions = fields.pop("grant_max_sessions", None)
        try:
            return cls.model_validate(
                {
                    "config": fields,
                    "verified_image_id": verified_image_id,
                    "grant_max_sessions": grant_max_sessions,
                }
            )
        except (ValueError, InvalidSandboxConfig) as error:
            raise SandboxError("Sandbox workspace policy is invalid.") from error

    def to_storage(self) -> dict[str, JsonValue]:
        """Keep existing checkpoint/session JSON fields stable for stored runs."""
        return {
            **self.config.to_storage(),
            "verified_image_id": self.verified_image_id,
            "grant_max_sessions": self.grant_max_sessions,
        }


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
