"""Shared validation mechanics for adapter-owned synthesis configuration.

Native fields remain on each vendor's model. Only the canonical runtime envelope
is removed during projection; unknown vendor options must fail validation.
"""

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.exceptions import TTSConfigurationError
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider


class TTSAdapterConfig(BaseModel):
    """Validated native input with private credentials and no mutable fields."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        validate_default=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    provider: ClassVar[TTSProvider]
    api_key: SpeechText = Field(repr=False, exclude=True)

    @classmethod
    def from_runtime(cls, config: TTSConfig) -> Self:
        """Remove only known envelope fields; preserve native defaults when absent."""
        if config.vendor != cls.provider:
            raise TTSConfigurationError("TTS config belongs to another provider.")
        values = config.to_adapter_config()
        for field in TTSConfig.model_fields.keys() - cls.model_fields.keys():
            values.pop(field, None)
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise TTSConfigurationError("Invalid TTS provider configuration.") from None
