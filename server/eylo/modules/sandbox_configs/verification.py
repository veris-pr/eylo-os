"""Sandbox verification contracts shared with pipeline composition."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from eylo.modules.sandbox_configs.catalog import SandboxProviders
from eylo.modules.sandbox_configs.domain import SandboxProviderConfig


class SandboxVerificationError(Exception):
    """The selected sandbox runtime failed bounded verification."""


class SandboxVerificationEvidence(BaseModel):
    """Bounded runtime identity produced only after both verification probes."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    verified_image_id: str = Field(min_length=1, max_length=512)
    docker_server_version: str = Field(min_length=1, max_length=512)


class SandboxVerificationResult(BaseModel):
    """The exact config revision successfully verified by the use case."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    provider: SandboxProviders
    revision: int = Field(gt=0)
    verified_at: datetime


class SandboxProviderVerifier(Protocol):
    async def verify(
        self,
        *,
        config: SandboxProviderConfig,
    ) -> SandboxVerificationEvidence: ...
