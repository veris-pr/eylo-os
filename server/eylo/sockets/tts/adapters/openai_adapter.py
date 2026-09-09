"""OpenAI native PCM synthesis over the ordered HTTP speech lifecycle."""

from collections.abc import AsyncIterator

from aiohttp import StreamReader

from eylo.sockets.tts.adapters.openai_tts_wire import (
    OPENAI_PCM_ENCODING,
    OPENAI_SAMPLE_RATE,
    OPENAI_TEXT_LIMIT,
    OpenAISpeechRequest,
    OpenAITTSConfig,
    speech_pcm,
)
from eylo.sockets.tts.http_synthesis import OrderedHttpSpeechAdapter
from eylo.sockets.tts.schemas import TTSCapabilities, TTSConfig, TTSProvider


class OpenAITTSAdapter(OrderedHttpSpeechAdapter[OpenAISpeechRequest]):
    """Keep native request validation and PCM decoding inside the vendor boundary."""

    text_limit = OPENAI_TEXT_LIMIT

    def __init__(self, config: OpenAITTSConfig) -> None:
        self._config = OpenAITTSConfig.model_validate(config)
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.OPENAI,
                model=self._config.model,
                voice=self._config.voice,
                sample_rate=OPENAI_SAMPLE_RATE,
                encoding=OPENAI_PCM_ENCODING,
            ),
            endpoint=f"{self._config.base_url.rstrip('/')}/audio/speech",
            api_key=self._config.api_key,
        )

    def speech_request(self, text: str) -> OpenAISpeechRequest:
        return self._config.request(text)

    def decode_audio(self, stream: StreamReader) -> AsyncIterator[bytes]:
        return speech_pcm(stream)

    @property
    def sample_rate(self) -> int:
        return OPENAI_SAMPLE_RATE

    @property
    def provider(self) -> str:
        return TTSProvider.OPENAI.value

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=True,
            batch_synthesize=False,
            native_interruption=False,
            aligned_transcript=False,
            emotion_control=False,
            speed_control=True,
            voice_cloning=False,
            context_continuity=False,
            sample_rates=(OPENAI_SAMPLE_RATE,),
        )
