"""Pinned sandbox policy shared by session reads and workspace execution."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from eylo.common.contracts.sandbox import SandboxError
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
