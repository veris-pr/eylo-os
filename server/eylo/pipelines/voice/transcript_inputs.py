"""Live transcript inputs; carrier controls are never provider STT metadata."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eylo.sockets.stt.schemas import STTEvent, STTTranscriptForm
from eylo.sockets.telephony.dtmf import DTMFCompletion


class DTMFInput(BaseModel):
    """A completed carrier digit sequence with optional live-buffer correlation."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    digits: str = Field(min_length=1, pattern=r"^[0-9*#]+$", repr=False)
    completed_by: DTMFCompletion
    live_buffer_sequence: int | None = Field(default=None, strict=True, gt=0)

    @property
    def transcript(self) -> str:
        return f"DTMF digits: {self.digits}"


class FinalTranscriptBatch(BaseModel):
    """Debounced final segments, preserving each segment's identity and timing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: tuple[STTEvent, ...] = Field(min_length=1, repr=False)

    @model_validator(mode="after")
    def require_final_segments(self) -> "FinalTranscriptBatch":
        if any(not event.is_final for event in self.segments):
            raise ValueError("Only final STT segments may form a transcript batch.")
        return self

    @property
    def transcript(self) -> str:
        parts: list[str] = []
        previous: STTEvent | None = None
        for event in self.segments:
            contiguous_delta = (
                previous is not None
                and previous.transcript_form is STTTranscriptForm.DELTA
                and event.transcript_form is STTTranscriptForm.DELTA
                and previous.provider is event.provider
                and previous.session_id == event.session_id
                and bool(event.session_id)
            )
            if previous is not None and not contiguous_delta:
                parts.append(" ")
            parts.append(event.transcript)
            previous = event
        text = "".join(parts)
        if self.segments[0].transcript_form is STTTranscriptForm.SEGMENT:
            text = text.lstrip()
        if self.segments[-1].transcript_form is STTTranscriptForm.SEGMENT:
            text = text.rstrip()
        return text


VoiceTranscriptInput = STTEvent | DTMFInput | FinalTranscriptBatch
