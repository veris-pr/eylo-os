"""Owned realtime inference values and in-memory connection credentials."""

from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictStr,
    field_validator,
)


class RealtimeEndpointingSensitivity(str, Enum):
    """Normalized endpointing choice used by adapters that implement it."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RealtimeContextCompression(Enum):
    """Compression policy; existing serialized values remain exact booleans."""

    DISABLED = False
    ENABLED = True

    def __bool__(self) -> bool:
        raise TypeError("Compare realtime compression with its explicit enum member.")


class RealtimeInferenceConfig(BaseModel):
    """Immutable scalar settings; provider compatibility belongs to its module."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        allow_inf_nan=False,
        hide_input_in_errors=True,
    )

    model: StrictStr = Field(min_length=1, pattern=r"\S")
    voice: StrictStr = Field(min_length=1, pattern=r"\S")
    temperature: StrictFloat | None = None
    top_p: StrictFloat | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, strict=True, gt=0)
    input_transcription_model: StrictStr | None = Field(
        default=None, min_length=1, pattern=r"\S"
    )
    vad_threshold: StrictFloat | None = Field(default=None, ge=0, le=1)
    vad_silence_ms: int | None = Field(default=None, strict=True, gt=0)
    endpointing_sensitivity: RealtimeEndpointingSensitivity | None = None
    is_context_compression_enabled: RealtimeContextCompression | None = None
    context_compression_trigger_tokens: int | None = Field(
        default=None, strict=True, gt=0
    )

    @field_validator("is_context_compression_enabled", mode="before")
    @classmethod
    def validate_compression(cls, value: object) -> RealtimeContextCompression | None:
        if value is None or isinstance(value, RealtimeContextCompression):
            return value
        if value is True:
            return RealtimeContextCompression.ENABLED
        if value is False:
            return RealtimeContextCompression.DISABLED
        raise ValueError("Realtime compression requires an explicit policy or boolean.")


class RealtimeApiKeyCredentials(BaseModel):
    """Plaintext adapter input, never included in representations or dumps."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    api_key: StrictStr = Field(min_length=1, pattern=r"\S", repr=False, exclude=True)


class RealtimeAWSCredentials(BaseModel):
    """Explicit AWS identity; absence of a session token means long-lived keys."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    access_key_id: StrictStr = Field(
        min_length=1, pattern=r"\S", repr=False, exclude=True
    )
    secret_access_key: StrictStr = Field(
        min_length=1, pattern=r"\S", repr=False, exclude=True
    )
    session_token: StrictStr | None = Field(
        default=None, min_length=1, pattern=r"\S", repr=False, exclude=True
    )


RealtimeCredentials = RealtimeApiKeyCredentials | RealtimeAWSCredentials


@runtime_checkable
class ResolvedRealtimeConfig(Protocol):
    """Structural runtime values without a dependency on the domain model."""

    @property
    def provider_id(self) -> str: ...

    @property
    def region(self) -> str | None: ...

    @property
    def credentials(self) -> RealtimeCredentials: ...
