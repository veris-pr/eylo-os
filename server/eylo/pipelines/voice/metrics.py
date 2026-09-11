"""Browser voice observations and their operator-selected storage projection."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue

from eylo.common.contracts.voice import BrowserVoiceTerminationReason
from eylo.pipelines.voice.stt import STTRuntimeMetrics
from eylo.sockets.tts.schemas import TTSMetricsSnapshot


class VendorLatencyProjection(StrEnum):
    """Whether vendor latency measurements belong in the exported observation."""

    INCLUDE = "include"
    OMIT = "omit"


class BrowserAudioMetrics(BaseModel):
    """Absent providers stay absent; missing measurements inside snapshots stay null."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    stt: STTRuntimeMetrics | None = None
    tts: TTSMetricsSnapshot | None = None
    termination_reason: BrowserVoiceTerminationReason | None = None

    def to_payload(
        self, *, latency: VendorLatencyProjection = VendorLatencyProjection.INCLUDE
    ) -> dict[str, JsonValue]:
        """Project without mutating the manager snapshots retained for teardown."""
        payload: dict[str, JsonValue] = {}
        if self.stt is not None:
            payload["stt"] = self.stt.model_dump(mode="json")
        if self.tts is not None:
            excluded = (
                {"first_audio_latency_seconds"}
                if latency is VendorLatencyProjection.OMIT
                else set()
            )
            payload["tts"] = self.tts.model_dump(mode="json", exclude=excluded)
        if self.termination_reason is not None:
            payload["termination_reason"] = self.termination_reason.value
        return payload
