"""Incremental Murf PCM/WAVE framing with bounded header and sample retention."""

import struct
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, PrivateAttr, StrictInt

from eylo.sockets.tts.adapters.murf_wire import MurfAudioFormat, MurfOutputError

PCM_SAMPLE_BYTES = 2
PCM_BITS = 16
PCM_CHANNELS = 1
PCM_FORMAT_TAG = 1
MAX_HEADER_BYTES = 64 * 1024
STREAM_SIZE_SENTINEL = 0xFFFFFFFF
RIFF = b"RIFF"
WAVE = b"WAVE"
FORMAT = b"fmt "
DATA = b"data"
RIFF_HEADER = struct.Struct("<4sI4s")
CHUNK_HEADER = struct.Struct("<4sI")
PCM_HEADER = struct.Struct("<HHIIHH")


class MurfWaveState(StrEnum):
    RIFF = "riff"
    CHUNKS = "chunks"
    DATA = "data"
    ENDED = "ended"


class MurfAudioDecoder(BaseModel):
    """One turn's mutable decoder; raw bytes never enter model snapshots.

    WAVE is streamed rather than buffered in full. Known data lengths are enforced;
    zero and all-ones streaming lengths are finalized by the vendor's final event.
    Only mono PCM16 is accepted. Metadata before data is skipped within a fixed
    header budget; trailing content and partial samples are rejected.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    format: MurfAudioFormat
    sample_rate: StrictInt
    _buffer: bytearray = PrivateAttr(default_factory=bytearray)
    _state: MurfWaveState = PrivateAttr(default=MurfWaveState.RIFF)
    _header_bytes: int = PrivateAttr(default=0)
    _format_seen: bool = PrivateAttr(default=False)
    _data_remaining: int | None = PrivateAttr(default=None)
    _sample_tail: bytes = PrivateAttr(default=b"")

    def feed(self, data: bytes) -> bytes:
        """Return only aligned PCM; incomplete headers/samples wait for more data."""
        if self.format is MurfAudioFormat.PCM:
            return self._aligned(data)
        if self._state is MurfWaveState.ENDED:
            if data:
                raise MurfOutputError("Murf WAV contains trailing content.")
            return b""
        self._buffer.extend(data)
        if self._state is MurfWaveState.RIFF:
            if len(self._buffer) < RIFF_HEADER.size:
                return b""
            riff, _, wave = RIFF_HEADER.unpack(self._take(RIFF_HEADER.size))
            if riff != RIFF or wave != WAVE:
                raise MurfOutputError("Murf returned an invalid WAV header.")
            self._state = MurfWaveState.CHUNKS
        while self._state is MurfWaveState.CHUNKS:
            if len(self._buffer) < CHUNK_HEADER.size:
                return b""
            kind, size = CHUNK_HEADER.unpack_from(self._buffer)
            if kind == DATA:
                self._take(CHUNK_HEADER.size)
                if not self._format_seen:
                    raise MurfOutputError("Murf returned an invalid WAV data header.")
                if size not in (0, STREAM_SIZE_SENTINEL) and size % PCM_SAMPLE_BYTES:
                    raise MurfOutputError("Murf WAV data is not sample aligned.")
                self._data_remaining = (
                    None if size in (0, STREAM_SIZE_SENTINEL) else size
                )
                self._state = MurfWaveState.DATA
                break
            total = CHUNK_HEADER.size + size + size % PCM_SAMPLE_BYTES
            if total + self._header_bytes > MAX_HEADER_BYTES:
                raise MurfOutputError("Murf WAV header exceeds the local limit.")
            if len(self._buffer) < total:
                return b""
            self._take(CHUNK_HEADER.size)
            payload = self._take(size)
            if size % PCM_SAMPLE_BYTES:
                self._take(1)
            if kind == FORMAT:
                self._validate_format(payload)
        audio = bytes(self._buffer)
        self._buffer.clear()
        if self._data_remaining is not None:
            if len(audio) > self._data_remaining:
                raise MurfOutputError("Murf WAV contains trailing content.")
            self._data_remaining -= len(audio)
            if not self._data_remaining:
                self._state = MurfWaveState.ENDED
        return self._aligned(audio)

    def _take(self, size: int) -> bytes:
        self._header_bytes += size
        if self._header_bytes > MAX_HEADER_BYTES:
            raise MurfOutputError("Murf WAV header exceeds the local limit.")
        value = bytes(self._buffer[:size])
        del self._buffer[:size]
        return value

    def _validate_format(self, payload: bytes) -> None:
        if self._format_seen or len(payload) < PCM_HEADER.size:
            raise MurfOutputError("Murf returned an invalid WAV format.")
        tag, channels, rate, byte_rate, align, bits = PCM_HEADER.unpack_from(payload)
        if (tag, channels, rate, byte_rate, align, bits) != (
            PCM_FORMAT_TAG,
            PCM_CHANNELS,
            self.sample_rate,
            self.sample_rate * PCM_SAMPLE_BYTES,
            PCM_SAMPLE_BYTES,
            PCM_BITS,
        ):
            raise MurfOutputError("Murf WAV format does not match configured PCM16.")
        self._format_seen = True

    def _aligned(self, data: bytes) -> bytes:
        data = self._sample_tail + data
        aligned = len(data) - len(data) % PCM_SAMPLE_BYTES
        self._sample_tail = data[aligned:]
        return data[:aligned]

    def finish(self) -> None:
        """A final event cannot turn incomplete media into successful output."""
        if self._sample_tail or self._buffer or self._data_remaining:
            raise MurfOutputError("Murf returned truncated audio.")
        if self.format is MurfAudioFormat.WAV and self._state not in (
            MurfWaveState.DATA,
            MurfWaveState.ENDED,
            MurfWaveState.RIFF,
        ):
            raise MurfOutputError("Murf returned an incomplete WAV header.")
