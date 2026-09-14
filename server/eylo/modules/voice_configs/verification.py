"""Voice provider verification contracts shared with pipeline composition."""

from __future__ import annotations

from typing import Protocol, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from eylo.modules.voice_configs.catalog import (
    RealtimeProviders,
    STTProviders,
    TTSProviders,
    VoiceKind,
)
from eylo.modules.voice_configs.domain import (
    InvalidVoiceConfig,
    VoiceProvider,
    VoiceProviderConfig,
    validate_voice_provider_kind,
)


class VoiceVerificationError(Exception):
    """Raised when a provider cannot complete bounded live verification."""


class VoiceProviderVerification(BaseModel):
    """Validated probe identity without credentials or provider-generated content."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    kind: VoiceKind
    provider: VoiceProvider

    @field_validator("provider", mode="before")
    @classmethod
    def _json_provider(cls, value: object, info: ValidationInfo) -> object:
        """Shared vendor spellings require the capability when decoding JSON."""
        if info.mode == "json" and isinstance(value, str):
            kind = info.data.get("kind")
            if kind is VoiceKind.STT:
                return STTProviders(value)
            if kind is VoiceKind.TTS:
                return TTSProviders(value)
            if kind is VoiceKind.REALTIME:
                return RealtimeProviders(value)
        return value

    @model_validator(mode="after")
    def _provider_kind(self) -> Self:
        try:
            validate_voice_provider_kind(self.provider, self.kind)
        except InvalidVoiceConfig as error:
            raise ValueError(str(error)) from None
        return self


class VoiceVerificationResult(VoiceProviderVerification):
    """Verification identity after the selected DB revision was marked verified."""

    revision: int = Field(ge=1)
    verified_at: AwareDatetime


class VoiceProviderVerifier(Protocol):
    """Port for one runtime-equivalent external provider check."""

    async def verify(
        self,
        config: VoiceProviderConfig,
    ) -> VoiceProviderVerification: ...
