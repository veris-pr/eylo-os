"""Typed call-audio observations, serialized only for logs and canonical storage."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt

from eylo.pipelines.voice.stt import STTRuntimeMetrics
from eylo.sockets.telephony.base import CallEndedReason
from eylo.sockets.tts.schemas import TTSMetricsSnapshot


class CarrierAudioMetrics(BaseModel):
    """Transport-owned counts; absent metrics are not reported as measured zeros."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    carrier_audio_chunks: StrictInt = Field(ge=0)
    carrier_audio_bytes: StrictInt = Field(ge=0)
    comfort_audio_chunks: StrictInt = Field(ge=0)
    comfort_audio_bytes: StrictInt = Field(ge=0)


class CallAudioMetrics(BaseModel):
    """Detached observations; optional branches retain the existing storage shape."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    stt: STTRuntimeMetrics | None = None
    tts: TTSMetricsSnapshot | None = None
    transport: CarrierAudioMetrics | None = None
    termination_reason: CallEndedReason | None = None

    def to_payload(self) -> dict[str, JsonValue]:
        """Omit unavailable branches, retaining null values inside observed snapshots."""
        absent = {
            name for name in type(self).model_fields if getattr(self, name) is None
        }
        return self.model_dump(mode="json", exclude=absent)
