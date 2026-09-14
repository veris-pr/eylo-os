"""Validated PCM16 frames and buffering independent of vendor SDKs.

Buffering patterns originated in LiveKit Agents' audio utilities. Frames are
platform-owned values; buffers own mutable bytes and are not data contracts.
"""

import io
import wave
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBytes,
    StrictInt,
    StrictStr,
    model_validator,
)

PCM_SAMPLE_BYTES = 2
_BITS_PER_BYTE = 8


class _AudioFrameLayout(BaseModel):
    """Shared frame dimensions; validate before allocating or buffering bytes."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True
    )

    sample_rate: StrictInt = Field(gt=0)
    num_channels: StrictInt = Field(gt=0)
    samples_per_channel: StrictInt = Field(ge=0)

    @property
    def size_bytes(self) -> int:
        return self.samples_per_channel * self.num_channels * PCM_SAMPLE_BYTES


class AudioFrame(_AudioFrameLayout):
    """Immutable PCM16 data with exact dimensions; raw content stays private.

    Optional JSON metadata is a mutable sidecar, not frame geometry. It is excluded
    from snapshots along with PCM bytes. Metadata keys belong to their producers.
    """

    data: StrictBytes = Field(repr=False, exclude=True)
    userdata: dict[StrictStr, JsonValue] = Field(
        default_factory=dict, repr=False, exclude=True
    )

    @model_validator(mode="after")
    def validate_pcm_size(self) -> Self:
        if len(self.data) != self.size_bytes:
            raise ValueError("PCM16 byte count does not match frame dimensions.")
        return self

    @property
    def duration(self) -> float:
        """Duration of this audio frame in seconds."""
        return self.samples_per_channel / self.sample_rate

    def to_wav_bytes(self) -> bytes:
        """Convert audio frame to WAV-formatted byte stream.

        Returns:
            bytes: Audio data encoded in WAV format with proper headers

        Example:
            >>> frame = AudioFrame(data=audio_bytes, sample_rate=16000, num_channels=1, samples_per_channel=1600)
            >>> wav_data = frame.to_wav_bytes()
            >>> with open("output.wav", "wb") as f:
            ...     f.write(wav_data)

        """
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.num_channels)
            wav_file.setsampwidth(PCM_SAMPLE_BYTES)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.data)
        return buffer.getvalue()

    @classmethod
    def from_wav_bytes(cls, wav_bytes: bytes) -> "AudioFrame":
        """Create AudioFrame from WAV-formatted bytes.

        Args:
            wav_bytes: WAV file data as bytes

        Returns:
            AudioFrame: Parsed audio frame

        Raises:
            ValueError: If WAV data is invalid or unsupported format

        Example:
            >>> with open("input.wav", "rb") as f:
            ...     wav_data = f.read()
            >>> frame = AudioFrame.from_wav_bytes(wav_data)

        """
        buffer = io.BytesIO(wav_bytes)
        with wave.open(buffer, "rb") as wav_file:
            # Validate format
            if wav_file.getsampwidth() != PCM_SAMPLE_BYTES:
                raise ValueError(
                    f"Only 16-bit PCM is supported, got {wav_file.getsampwidth() * _BITS_PER_BYTE}-bit"
                )

            num_channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            audio_data = wav_file.readframes(wav_file.getnframes())
            samples_per_channel = len(audio_data) // (num_channels * PCM_SAMPLE_BYTES)

            return cls(
                data=audio_data,
                sample_rate=sample_rate,
                num_channels=num_channels,
                samples_per_channel=samples_per_channel,
            )

    @classmethod
    def create(
        cls, sample_rate: int, num_channels: int, samples_per_channel: int
    ) -> "AudioFrame":
        """Create empty AudioFrame with zeroed data.

        Args:
            sample_rate: Sample rate in Hz
            num_channels: Number of channels (1=mono, 2=stereo)
            samples_per_channel: Number of samples per channel

        Returns:
            AudioFrame: New frame with zero-initialized data

        Example:
            >>> frame = AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=320)
            >>> len(frame.data)
            640

        """
        layout = _AudioFrameLayout(
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
        )
        return cls(
            data=bytes(layout.size_bytes),
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
        )


class AudioBuffer:
    """Buffer for collecting audio frames.

    Useful for accumulating variable-sized audio chunks before processing.

    Example:
        buffer = AudioBuffer()
        buffer.append(frame1)
        buffer.append(frame2)
        total_duration = buffer.duration()  # Get total buffered time
        buffer.clear()  # Reset buffer

    """

    def __init__(self) -> None:
        self._frames: list[AudioFrame] = []

    def append(self, frame: AudioFrame) -> None:
        """Add frame to buffer."""
        self._frames.append(frame)

    def clear(self) -> None:
        """Clear all buffered frames."""
        self._frames.clear()

    def duration(self) -> float:
        """Total duration of buffered audio in seconds."""
        return sum(f.duration for f in self._frames)

    def frames(self) -> list[AudioFrame]:
        """Get all buffered frames (returns copy)."""
        return self._frames.copy()

    def __len__(self) -> int:
        """Number of frames in buffer."""
        return len(self._frames)


class AudioByteStream:
    """Convert variable-size audio bytes to fixed-size chunks."""

    def __init__(
        self,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        """Initialize audio byte stream.

        Args:
            sample_rate: Sample rate in Hz (e.g., 16000, 48000)
            num_channels: Number of channels (1=mono, 2=stereo)
            samples_per_channel: Target samples per chunk

        """
        self._layout = _AudioFrameLayout(
            sample_rate=sample_rate,
            num_channels=num_channels,
            samples_per_channel=samples_per_channel,
        )
        if self._layout.samples_per_channel == 0:
            raise ValueError("Audio byte streams require a positive chunk size.")
        self._chunk_size = self._layout.size_bytes
        self._buffer = bytearray()

    @property
    def sample_rate(self) -> int:
        return self._layout.sample_rate

    @property
    def num_channels(self) -> int:
        return self._layout.num_channels

    @property
    def samples_per_channel(self) -> int:
        return self._layout.samples_per_channel

    def write(self, data: bytes) -> list[AudioFrame]:
        """Write audio bytes, returns completed chunks.

        Args:
            data: Raw audio bytes to buffer

        Returns:
            List of completed AudioFrame chunks (may be empty if not enough data)

        """
        self._buffer.extend(data)

        frames: list[AudioFrame] = []
        while len(self._buffer) >= self._chunk_size:
            chunk_data = bytes(self._buffer[: self._chunk_size])
            self._buffer = self._buffer[self._chunk_size :]

            frames.append(
                AudioFrame(
                    data=chunk_data,
                    sample_rate=self.sample_rate,
                    num_channels=self.num_channels,
                    samples_per_channel=self.samples_per_channel,
                )
            )

        return frames

    def flush(self) -> list[AudioFrame]:
        """Return complete remaining PCM samples; retain bytes if the tail is invalid."""
        if not self._buffer:
            return []

        # Get remaining data
        remaining = bytes(self._buffer)
        # Calculate actual samples
        bytes_per_sample = PCM_SAMPLE_BYTES * self.num_channels
        actual_samples = len(remaining) // bytes_per_sample
        frame = AudioFrame(
            data=remaining,
            sample_rate=self.sample_rate,
            num_channels=self.num_channels,
            samples_per_channel=actual_samples,
        )
        self._buffer.clear()
        return [frame]

    def pending_bytes(self) -> int:
        """Number of bytes currently buffered."""
        return len(self._buffer)
