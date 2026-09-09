"""Translate validated Speechmatics responses into the canonical STT contract."""

from __future__ import annotations

import asyncio

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    field_validator,
)

from eylo.sockets.stt.adapters.connection_errors import (
    close_failed_websocket_connection,
)
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import STTConnectionClosed
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTCapabilitySupport,
    STTEncoding,
    STTError,
    STTEvent,
    STTEventType,
    STTProvider,
    STTTranscriptForm,
    TimedWord,
)
from eylo.sockets.voice.audio import AudioFrame
from eylo.sockets.voice.vendors.speechmatics.stt import (
    SpeechmaticsSTT,
    SpeechmaticsSTTStream,
)
from eylo.sockets.voice.vendors.speechmatics.wire import (
    SpeechmaticsAudioAdded,
    SpeechmaticsDiarization,
    SpeechmaticsEncoding,
    SpeechmaticsEndOfTranscript,
    SpeechmaticsEndOfUtterance,
    SpeechmaticsEntity,
    SpeechmaticsError,
    SpeechmaticsEvent,
    SpeechmaticsMessage,
    SpeechmaticsRecognitionStarted,
    SpeechmaticsResultKind,
    SpeechmaticsToken,
)

_MILLISECONDS_PER_SECOND = 1000
_PCM_BYTES_PER_SAMPLE = 2


class SpeechmaticsAdapterConfig(BaseModel):
    """Select consumed vendor options without importing platform configuration types."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)
    language: str = Field(min_length=1)
    sample_rate: int = Field(default=16000, strict=True, gt=0)
    encoding: SpeechmaticsEncoding = SpeechmaticsEncoding.PCM_S16LE
    enable_partials: StrictBool = True
    enable_entities: StrictBool = False
    max_delay: float = Field(default=2.0, strict=True, ge=0.7, le=4.0)
    diarization: SpeechmaticsDiarization | None = None
    custom_vocabulary: tuple[str, ...] | None = Field(default=None, repr=False)

    @field_validator("encoding", mode="before")
    @classmethod
    def translate_pcm_encoding(cls, value: object) -> object:
        if value == STTEncoding.LINEAR16:
            return SpeechmaticsEncoding.PCM_S16LE
        return value


class SpeechmaticsAdapter(STTVendorAdapter):
    """One native stream owns resources; the factory owns failure recovery."""

    def __init__(self, config: object) -> None:
        super().__init__()
        self._config = SpeechmaticsAdapterConfig.model_validate(config)
        self._stream: SpeechmaticsSTTStream | None = None
        self._is_connected = False
        self._lifecycle_lock = asyncio.Lock()
        self._stt = SpeechmaticsSTT(
            api_key=self._config.api_key.get_secret_value(),
            language=self._config.language,
            sample_rate=self._config.sample_rate,
            enable_partials=self._config.enable_partials,
            enable_entities=self._config.enable_entities,
            max_delay=self._config.max_delay,
            diarization=self._config.diarization,
            custom_vocabulary=self._config.custom_vocabulary,
        )

    async def connect(self) -> SpeechmaticsAdapter:
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

    def _convert_event(self, event: SpeechmaticsEvent) -> STTEvent | None:
        """Use the complete formatted segment, never just its first result/alternative."""
        session_id = self._stream.session_id if self._stream is not None else ""
        request_id = self._stream.recognition_id if self._stream is not None else None
        if isinstance(
            event,
            (
                SpeechmaticsRecognitionStarted,
                SpeechmaticsAudioAdded,
                SpeechmaticsEndOfTranscript,
            ),
        ):
            return None
        if isinstance(event, SpeechmaticsError):
            return STTEvent(
                type=STTEventType.ERROR,
                provider=STTProvider.SPEECHMATICS,
                model=self.model,
                session_id=session_id,
                provider_request_id=request_id,
                error=STTError(
                    message=event.reason, code=event.type.value, recoverable=False
                ),
            )
        if isinstance(event, SpeechmaticsEndOfUtterance):
            return STTEvent(
                type=STTEventType.SPEECH_END,
                provider=STTProvider.SPEECHMATICS,
                model=self.model,
                session_id=session_id,
                provider_request_id=request_id,
                audio_start_ms=round(
                    event.metadata.start_time * _MILLISECONDS_PER_SECOND
                )
                if event.metadata.start_time is not None
                else None,
                audio_end_ms=round(event.metadata.end_time * _MILLISECONDS_PER_SECOND)
                if event.metadata.end_time is not None
                else None,
            )
        if not event.metadata.transcript:
            return None
        is_final = event.message is SpeechmaticsMessage.FINAL
        tokens: list[SpeechmaticsToken] = []
        for result in event.results:
            if isinstance(result, SpeechmaticsEntity):
                tokens.extend(result.written_form)
            else:
                tokens.append(result)
        words = tuple(
            TimedWord(
                word=token.alternatives[0].content,
                start_time=token.start_time,
                end_time=token.end_time,
                confidence=token.alternatives[0].confidence if is_final else None,
                speaker_id=token.alternatives[0].speaker,
            )
            for token in tokens
            if token.type is SpeechmaticsResultKind.WORD and token.alternatives
        )
        speakers = {word.speaker_id for word in words if word.speaker_id is not None}
        return STTEvent(
            type=STTEventType.TRANSCRIPT_FINAL
            if is_final
            else STTEventType.TRANSCRIPT_PARTIAL,
            provider=STTProvider.SPEECHMATICS,
            model=self.model,
            session_id=session_id,
            provider_request_id=request_id,
            transcript=event.metadata.transcript,
            transcript_form=STTTranscriptForm.DELTA,
            language=self._config.language,
            words=words,
            speaker_id=next(iter(speakers)) if len(speakers) == 1 else None,
            audio_start_ms=round(event.metadata.start_time * _MILLISECONDS_PER_SECOND),
            audio_end_ms=round(event.metadata.end_time * _MILLISECONDS_PER_SECOND),
            vendor_metadata=event.model_dump(
                mode="json", include={"results", "forced"}, exclude_defaults=True
            ),
        )

    async def send_audio(self, audio_data: bytes) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Speechmatics stream is not connected.")
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
            raise STTConnectionClosed("Speechmatics stream is not connected.")
        try:
            event = await asyncio.wait_for(
                anext(self._stream), timeout=timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None
        except StopAsyncIteration as error:
            self._is_connected = False
            raise STTConnectionClosed("Speechmatics stream ended.") from error
        except Exception:
            self._is_connected = False
            raise
        return self._convert_event(event)

    async def flush(self) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Speechmatics stream is not connected.")
        try:
            await self._stream.flush()
        except BaseException:
            self._is_connected = False
            raise

    async def keepalive(self) -> None:
        """The native aiohttp connection owns ping/pong heartbeats."""

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
        """Queued terminal output stays readable after the physical socket closes."""
        return self._is_connected

    @property
    def sample_rate(self) -> int:
        return self._stt.sample_rate

    @property
    def provider(self) -> str:
        return self._stt.provider

    @property
    def model(self) -> str:
        """This integration selects the vendor language model through language."""
        return self._stt.language

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            interim_results=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            speaker_labels=STTCapabilitySupport.SUPPORTED,
            custom_vocabulary=STTCapabilitySupport.SUPPORTED,
            punctuation=STTCapabilitySupport.SUPPORTED,
        )
