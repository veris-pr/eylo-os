"""Groq-owned speech requests and bounded RIFF/WAVE response validation."""

import asyncio
import struct
from collections.abc import AsyncIterator
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Self

from aiohttp import StreamReader
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.exceptions import TTSConfigurationError, TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig, TTSProvider

GROQ_SAMPLE_RATE = 48000
GROQ_CHANNELS = 1
GROQ_BYTES_PER_SAMPLE = 2
GROQ_BITS_PER_SAMPLE = 16
GROQ_BYTE_RATE = GROQ_SAMPLE_RATE * GROQ_CHANNELS * GROQ_BYTES_PER_SAMPLE
GROQ_PCM_ENCODING = "pcm_s16le"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_TEXT_LIMIT = 200
GROQ_AUDIO_CHUNK_BYTES = 4096
# One bounded HTTP synthesis response, not a conversation-wide audio budget.
GROQ_MAX_WAVE_BYTES = 32 * 1024 * 1024
_RIFF_HEADER = struct.Struct("<4sI4s")
_CHUNK_HEADER = struct.Struct("<4sI")
_PCM_FORMAT = struct.Struct("<HHIIHH")
_RIFF_ID = b"RIFF"
_WAVE_ID = b"WAVE"
_FORMAT_ID = b"fmt "
_DATA_ID = b"data"
_WORD_BYTES = 2


class GroqSpeechModel(StrEnum):
    ORPHEUS_ENGLISH = "canopylabs/orpheus-v1-english"
    ORPHEUS_ARABIC = "canopylabs/orpheus-arabic-saudi"


class GroqSpeechFormat(StrEnum):
    WAV = "wav"


class GroqWaveEncoding(IntEnum):
    PCM = 1


class GroqTTSConfig(TTSAdapterConfig):
    """Orpheus inputs; the PCM consumer requires mono 16-bit audio at 48 kHz."""

    provider = TTSProvider.GROQ
    model: GroqSpeechModel
    voice: SpeechText
    sample_rate: Annotated[
        StrictInt, Field(ge=GROQ_SAMPLE_RATE, le=GROQ_SAMPLE_RATE)
    ] = GROQ_SAMPLE_RATE
    base_url: SpeechText = GROQ_BASE_URL

    @classmethod
    def from_runtime(cls, config: TTSConfig) -> Self:
        if config.vendor is not cls.provider:
            raise TTSConfigurationError("Groq requires its own provider config.")
        values = config.to_adapter_config()
        if (
            "sample_rate" not in config.model_fields_set
            and "sample_rate" not in config.options
        ):
            values.pop("sample_rate", None)
        for field in TTSConfig.model_fields.keys() - cls.model_fields.keys():
            values.pop(field, None)
        try:
            return cls.model_validate(values)
        except ValidationError:
            raise TTSConfigurationError(
                "Invalid Groq TTS provider configuration."
            ) from None

    def request(self, text: str) -> "GroqSpeechRequest":
        return GroqSpeechRequest(model=self.model, voice=self.voice, input=text)


class GroqSpeechRequest(BaseModel):
    """Only documented Orpheus fields; no credential or transport field is sent."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    model: GroqSpeechModel
    voice: SpeechText
    input: Annotated[StrictStr, Field(min_length=1, max_length=GROQ_TEXT_LIMIT)]
    response_format: Literal[GroqSpeechFormat.WAV] = GroqSpeechFormat.WAV


class GroqWaveFormat(BaseModel):
    """Validated WAV metadata must agree with the adapter's playback contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    format_tag: Literal[GroqWaveEncoding.PCM]
    channels: Annotated[StrictInt, Field(ge=GROQ_CHANNELS, le=GROQ_CHANNELS)]
    sample_rate: Annotated[StrictInt, Field(ge=GROQ_SAMPLE_RATE, le=GROQ_SAMPLE_RATE)]
    byte_rate: Annotated[StrictInt, Field(ge=GROQ_BYTE_RATE, le=GROQ_BYTE_RATE)]
    block_align: Annotated[
        StrictInt, Field(ge=GROQ_BYTES_PER_SAMPLE, le=GROQ_BYTES_PER_SAMPLE)
    ]
    bits_per_sample: Annotated[
        StrictInt, Field(ge=GROQ_BITS_PER_SAMPLE, le=GROQ_BITS_PER_SAMPLE)
    ]


async def _discard(stream: StreamReader, size: int) -> None:
    while size:
        chunk = await stream.readexactly(min(size, GROQ_AUDIO_CHUNK_BYTES))
        size -= len(chunk)


async def wave_pcm(stream: StreamReader) -> AsyncIterator[bytes]:
    """Stream only PCM data; reject truncation, wrong media and ambiguous containers.

    RIFF chunks include word padding and may contain metadata before/after audio.
    Declared sizes bound total work; no full-body buffer or fixed header offset.
    The caller owns the HTTP response and must close it even on cancellation.
    """
    try:
        riff, size, kind = _RIFF_HEADER.unpack(
            await stream.readexactly(_RIFF_HEADER.size)
        )
        if (
            riff != _RIFF_ID
            or kind != _WAVE_ID
            or not len(_WAVE_ID) <= size <= GROQ_MAX_WAVE_BYTES
        ):
            raise ValueError("Invalid RIFF/WAVE envelope.")
        remaining = size - len(_WAVE_ID)
        audio_format: GroqWaveFormat | None = None
        received_audio = False
        while remaining:
            if remaining < _CHUNK_HEADER.size:
                raise ValueError("Truncated WAV chunk header.")
            chunk_id, chunk_size = _CHUNK_HEADER.unpack(
                await stream.readexactly(_CHUNK_HEADER.size)
            )
            remaining -= _CHUNK_HEADER.size
            padding = chunk_size % _WORD_BYTES
            if chunk_size + padding > remaining:
                raise ValueError("WAV chunk exceeds RIFF bounds.")
            if chunk_id == _FORMAT_ID:
                if audio_format is not None or chunk_size < _PCM_FORMAT.size:
                    raise ValueError("Invalid WAV format chunk.")
                tag, channels, rate, byte_rate, align, bits = _PCM_FORMAT.unpack(
                    await stream.readexactly(_PCM_FORMAT.size)
                )
                audio_format = GroqWaveFormat(
                    format_tag=tag,
                    channels=channels,
                    sample_rate=rate,
                    byte_rate=byte_rate,
                    block_align=align,
                    bits_per_sample=bits,
                )
                await _discard(stream, chunk_size - _PCM_FORMAT.size)
            elif chunk_id == _DATA_ID:
                if (
                    audio_format is None
                    or received_audio
                    or not chunk_size
                    or chunk_size % audio_format.block_align
                ):
                    raise ValueError("Invalid WAV audio chunk.")
                received_audio = True
                left = chunk_size
                while left:
                    pcm = await stream.readexactly(min(left, GROQ_AUDIO_CHUNK_BYTES))
                    left -= len(pcm)
                    yield pcm
            else:
                await _discard(stream, chunk_size)
            if padding:
                await stream.readexactly(padding)
            remaining -= chunk_size + padding
        if not received_audio or await stream.read(1):
            raise ValueError("Missing WAV audio or trailing bytes outside RIFF.")
    except (ValueError, asyncio.IncompleteReadError, struct.error):
        raise TTSConnectionFailed(
            "Groq TTS returned invalid or unsupported WAV audio."
        ) from None
