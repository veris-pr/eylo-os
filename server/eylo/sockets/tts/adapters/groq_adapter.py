"""Groq native requests and WAV decoding over the ordered HTTP speech lifecycle."""

from collections.abc import AsyncIterator

from aiohttp import StreamReader

from eylo.sockets.tts.adapters.groq_tts_wire import (
    GROQ_PCM_ENCODING,
    GROQ_SAMPLE_RATE,
    GROQ_TEXT_LIMIT,
    GroqSpeechRequest,
    GroqTTSConfig,
    wave_pcm,
)
from eylo.sockets.tts.http_synthesis import OrderedHttpSpeechAdapter
from eylo.sockets.tts.schemas import (
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)


class GroqTTSAdapter(OrderedHttpSpeechAdapter[GroqSpeechRequest]):
    """Validate Orpheus input and expose only mono PCM16 at the native rate."""

    text_limit = GROQ_TEXT_LIMIT

    def __init__(self, config: GroqTTSConfig) -> None:
        self._config = GroqTTSConfig.model_validate(config)
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.GROQ,
                model=self._config.model.value,
                voice=self._config.voice,
                sample_rate=GROQ_SAMPLE_RATE,
                encoding=GROQ_PCM_ENCODING,
            ),
            endpoint=f"{self._config.base_url.rstrip('/')}/audio/speech",
            api_key=self._config.api_key,
        )

    def speech_request(self, text: str) -> GroqSpeechRequest:
        return self._config.request(text)

    def decode_audio(self, stream: StreamReader) -> AsyncIterator[bytes]:
        return wave_pcm(stream)

    @property
    def sample_rate(self) -> int:
        return GROQ_SAMPLE_RATE

    @property
    def provider(self) -> str:
        return TTSProvider.GROQ.value

    @property
    def model(self) -> str:
        return self._config.model.value

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.UNSUPPORTED,
            native_interruption=TTSCapabilitySupport.UNSUPPORTED,
            aligned_transcript=TTSCapabilitySupport.UNSUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.UNSUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.UNSUPPORTED,
            sample_rates=(GROQ_SAMPLE_RATE,),
        )
