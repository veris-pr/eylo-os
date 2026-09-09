"""OpenAI-owned speech requests and bounded, frame-aligned raw PCM responses."""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Annotated, Literal

from aiohttp import StreamReader
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSProvider

OPENAI_SAMPLE_RATE = 24000
OPENAI_BYTES_PER_SAMPLE = 2
OPENAI_PCM_ENCODING = "pcm_s16le"
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_TEXT_LIMIT = 4096
OPENAI_AUDIO_CHUNK_BYTES = 4096
# Local bound per HTTP response, not a vendor limit or conversation-wide budget.
OPENAI_MAX_PCM_BYTES = 32 * 1024 * 1024
OPENAI_MIN_SPEED = 0.25
OPENAI_MAX_SPEED = 4.0
OPENAI_NORMAL_SPEED = 1.0
OpenAISpeechSpeed = Annotated[
    StrictFloat, Field(ge=OPENAI_MIN_SPEED, le=OPENAI_MAX_SPEED, allow_inf_nan=False)
]


class OpenAISpeechFormat(StrEnum):
    PCM = "pcm"


class OpenAITTSConfig(TTSAdapterConfig):
    """Operator-selected model/voice IDs stay open; only executable fields exist."""

    provider = TTSProvider.OPENAI
    model: SpeechText
    voice: SpeechText
    speed: OpenAISpeechSpeed = OPENAI_NORMAL_SPEED
    base_url: SpeechText = OPENAI_BASE_URL

    def request(self, text: str) -> "OpenAISpeechRequest":
        return OpenAISpeechRequest(
            model=self.model, voice=self.voice, input=text, speed=self.speed
        )


class OpenAISpeechRequest(BaseModel):
    """PCM speech input; credentials and transport options cannot enter the body."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    model: SpeechText
    voice: SpeechText
    input: Annotated[StrictStr, Field(min_length=1, max_length=OPENAI_TEXT_LIMIT)]
    speed: OpenAISpeechSpeed
    response_format: Literal[OpenAISpeechFormat.PCM] = OpenAISpeechFormat.PCM


async def speech_pcm(stream: StreamReader) -> AsyncIterator[bytes]:
    """Preserve PCM16 frames across HTTP chunks; reject empty/truncated output.

    OpenAI supplies headerless mono PCM at 24 kHz. Alignment checks cannot prove
    audible content; the caller owns and closes the surrounding HTTP response.
    """
    pending = b""
    received_bytes = 0
    async for chunk in stream.iter_chunked(OPENAI_AUDIO_CHUNK_BYTES):
        received_bytes += len(chunk)
        if received_bytes > OPENAI_MAX_PCM_BYTES:
            raise TTSConnectionFailed("OpenAI TTS response exceeds the audio bound.")
        data = pending + chunk
        end = len(data) - len(data) % OPENAI_BYTES_PER_SAMPLE
        if end:
            yield data[:end]
        pending = data[end:]
    if not received_bytes or pending:
        raise TTSConnectionFailed("OpenAI TTS returned empty or incomplete PCM audio.")
