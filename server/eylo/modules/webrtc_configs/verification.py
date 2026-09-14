"""WebRTC provider verification contracts shared with pipeline composition."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from eylo.modules.webrtc_configs.catalog import WebRTCProviders
from eylo.modules.webrtc_configs.domain import WebRTCProviderConfig


class WebRTCVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class WebRTCProviderVerification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: WebRTCProviders


class WebRTCVerificationResult(WebRTCProviderVerification):
    revision: int = Field(gt=0)
    verified_at: datetime


class WebRTCProviderVerifier(Protocol):
    """Port for one runtime-equivalent external provider check."""

    async def verify(
        self,
        config: WebRTCProviderConfig,
    ) -> WebRTCProviderVerification: ...
