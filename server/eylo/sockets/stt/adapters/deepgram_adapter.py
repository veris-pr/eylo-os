"""Translate Deepgram Listen v1 objects into platform-neutral recognition events."""

from __future__ import annotations

import asyncio

from pydantic import ConfigDict, Field, SecretStr, field_validator

from eylo.sockets.stt.adapters.connection_errors import (
    close_failed_websocket_connection,
)
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import STTConnectionClosed
from eylo.sockets.stt.schemas import (
    RecognitionUsage,
    STTCapabilities,
    STTCapabilitySupport,
    STTEncoding,
    STTEvent,
    STTEventType,
    STTProvider,
    STTTranscriptForm,
    TimedWord,
)
from eylo.sockets.voice.audio import AudioFrame
from eylo.sockets.voice.vendors.deepgram.stt import DeepgramSTT, DeepgramSTTStream
from eylo.sockets.voice.vendors.deepgram.stt_wire import (
    DeepgramEncoding,
    DeepgramEvent,
    DeepgramListenQuery,
    DeepgramMetadata,
    DeepgramSpeechStarted,
    DeepgramUtteranceEnd,
)

_MILLISECONDS_PER_SECOND = 1000
_PCM_BYTES_PER_SAMPLE = 2


class DeepgramAdapterConfig(DeepgramListenQuery):
    """Select consumed native settings; unrelated common config fields remain outside."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)

    @field_validator("encoding", mode="before")
    @classmethod
    def translate_pcm_encoding(cls, value: object) -> object:
        if value == STTEncoding.PCM_S16LE:
            return DeepgramEncoding.LINEAR16
        return value


class DeepgramAdapter(STTVendorAdapter):
    """Native stream owns I/O; factory owns retry and pipelines own conversational policy."""

    def __init__(self, config: object) -> None:
        super().__init__()
        self._config = DeepgramAdapterConfig.model_validate(config)
        self._stream: DeepgramSTTStream | None = None
        self._is_connected = False
        self._lifecycle_lock = asyncio.Lock()
        self._stt = DeepgramSTT(
            model=self._config.model,
            language=self._config.language,
            api_key=self._config.api_key.get_secret_value(),
            sample_rate=self._config.sample_rate,
            interim_results=self._config.interim_results,
            punctuate=self._config.punctuate,
            smart_format=self._config.smart_format,
            vad_events=self._config.vad_events,
            endpointing=self._config.endpointing,
            utterance_end_ms=self._config.utterance_end_ms,
        )

    async def connect(self) -> DeepgramAdapter:
        async with self._lifecycle_lock:
            if self.is_connected:
                return self
            if self._stream is not None:
                await self._close_stream()
            self._stream = self._stt.stream()
            try:
                await self._stream.connect()
            except BaseException as error:
                await close_failed_websocket_connection(error, self._close_stream)
            self._is_connected = True
            return self

    def _convert_event(self, event: DeepgramEvent) -> STTEvent | None:
        """Preserve native finality, segment boundaries, audio clocks and reported usage."""
        session_id = self._stream.session_id if self._stream is not None else ""
        request_id = self._stream.request_id if self._stream is not None else None
        if isinstance(event, DeepgramMetadata):
            return STTEvent(
                type=STTEventType.RECOGNITION_USAGE,
                provider=STTProvider.DEEPGRAM,
                model=self.model,
                session_id=session_id,
                provider_request_id=event.request_id,
                usage=RecognitionUsage(audio_duration=event.duration),
            )
        if isinstance(event, DeepgramSpeechStarted):
            return STTEvent(
                type=STTEventType.SPEECH_START,
                provider=STTProvider.DEEPGRAM,
                model=self.model,
                session_id=session_id,
                provider_request_id=request_id,
                audio_start_ms=round(event.timestamp * _MILLISECONDS_PER_SECOND),
            )
        if isinstance(event, DeepgramUtteranceEnd):
            return STTEvent(
                type=STTEventType.SPEECH_END,
                provider=STTProvider.DEEPGRAM,
                model=self.model,
                session_id=session_id,
                provider_request_id=request_id,
                audio_end_ms=round(event.last_word_end * _MILLISECONDS_PER_SECOND),
            )
        alternative = (
            event.channel.alternatives[0] if event.channel.alternatives else None
        )
        transcript = alternative.transcript if alternative is not None else ""
        ended = event.is_final and event.speech_final
        if not transcript and not ended:
            return None
        if ended:
            event_type = STTEventType.END_OF_TURN
        elif event.is_final:
            event_type = STTEventType.TRANSCRIPT_FINAL
        else:
            event_type = STTEventType.TRANSCRIPT_PARTIAL
        words = (
            tuple(
                TimedWord(
                    word=word.word,
                    start_time=word.start,
                    end_time=word.end,
                    confidence=word.confidence,
                    speaker_id=str(word.speaker) if word.speaker is not None else None,
                )
                for word in alternative.words
            )
            if alternative is not None
            else ()
        )
        speakers = {word.speaker_id for word in words if word.speaker_id is not None}
        if event.metadata is not None:
            request_id = event.metadata.request_id or request_id
        return STTEvent(
            type=event_type,
            provider=STTProvider.DEEPGRAM,
            model=self.model,
            session_id=session_id,
            provider_request_id=request_id,
            transcript=transcript,
            transcript_form=STTTranscriptForm.SEGMENT,
            confidence=alternative.confidence if alternative is not None else None,
            language=alternative.languages[0]
            if alternative is not None and len(alternative.languages) == 1
            else self._config.language,
            words=words,
            speaker_id=next(iter(speakers)) if len(speakers) == 1 else None,
            audio_start_ms=round(event.start * _MILLISECONDS_PER_SECOND),
            audio_end_ms=round(
                (event.start + event.duration) * _MILLISECONDS_PER_SECOND
            ),
            vendor_metadata=event.model_dump(
                mode="json",
                include={
                    "metadata",
                    "channel_index",
                    "is_final",
                    "speech_final",
                    "from_finalize",
                },
                exclude_none=True,
            ),
        )

    async def send_audio(self, audio_data: bytes) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Deepgram stream is not connected.")
        frame = AudioFrame(
            data=audio_data,
            sample_rate=self.sample_rate,
            num_channels=1,
            samples_per_channel=len(audio_data) // _PCM_BYTES_PER_SAMPLE,
        )
        try:
            await self._stream.push_audio(frame)
        except BaseException:
            self._is_connected = False
            raise

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        if self._stream is None:
            raise STTConnectionClosed("Deepgram stream is not connected.")
        try:
            event = await asyncio.wait_for(
                anext(self._stream), timeout=timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None
        except StopAsyncIteration as error:
            self._is_connected = False
            raise STTConnectionClosed("Deepgram stream ended.") from error
        except Exception:
            self._is_connected = False
            raise
        return self._convert_event(event)

    async def flush(self) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Deepgram stream is not connected.")
        try:
            await self._stream.flush()
        except BaseException:
            self._is_connected = False
            raise

    async def keepalive(self) -> None:
        """The native stream owns periodic JSON KeepAlive messages."""

    async def _close_stream(self) -> None:
        self._is_connected = False
        stream, self._stream = self._stream, None
        try:
            if stream is not None:
                await stream.aclose()
        finally:
            await self._stt.aclose()

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            await self._close_stream()

    @property
    def is_connected(self) -> bool:
        """Keep already-received terminal output readable after the socket closes."""
        return self._is_connected

    @property
    def sample_rate(self) -> int:
        return self._stt.sample_rate

    @property
    def provider(self) -> str:
        return self._stt.provider

    @property
    def model(self) -> str:
        return self._stt.model

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            vad_events=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            punctuation=STTCapabilitySupport.SUPPORTED,
        )
