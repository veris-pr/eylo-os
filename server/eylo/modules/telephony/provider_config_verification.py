"""Telephony provider verification contracts for pipeline composition."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from eylo.modules.telephony.provider_config_domain import (
    TelephonyProvider,
    TelephonyProviderConfig,
)


class TelephonyVerificationError(Exception):
    """Raised when bounded read-only carrier verification fails."""


ACCOUNT_FINGERPRINT_LENGTH = 16


class TelephonyVerificationOperation(StrEnum):
    READ_ONLY_ACCOUNT_LOOKUP = "read_only_account_lookup"


class TelephonyVerificationMetadata(BaseModel):
    """Non-secret evidence retained for the exact verified configuration revision."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    account_fingerprint: str = Field(
        min_length=ACCOUNT_FINGERPRINT_LENGTH,
        max_length=ACCOUNT_FINGERPRINT_LENGTH,
        pattern=r"^[0-9a-f]+$",
    )
    operation: Literal[TelephonyVerificationOperation.READ_ONLY_ACCOUNT_LOOKUP] = (
        TelephonyVerificationOperation.READ_ONLY_ACCOUNT_LOOKUP
    )


class TelephonyProviderVerification(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    provider: TelephonyProvider
    metadata: TelephonyVerificationMetadata


class TelephonyVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    provider: TelephonyProvider
    revision: int = Field(gt=0)
    verified_at: datetime


class TelephonyProviderVerifier(Protocol):
    async def verify(
        self,
        config: TelephonyProviderConfig,
    ) -> TelephonyProviderVerification: ...
