"""Translate validated AssemblyAI events into canonical recognition outcomes."""

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
    RecognitionUsage,
    STTCapabilities,
    STTCapabilitySupport,
    STTEncoding,
    STTError,
    STTEvent,
    STTEventType,
    STTProvider,
    TimedWord,
)
from eylo.sockets.voice.vendors.assemblyai import AssemblyAISTT
from eylo.sockets.voice.vendors.assemblyai.events import (
    AssemblyAIBegin,
    AssemblyAIError,
    AssemblyAIEvent,
    AssemblyAISpeechStarted,
    AssemblyAITermination,
    AssemblyAITurn,
)
from eylo.sockets.voice.vendors.assemblyai.stt import (
    AssemblyAIEncoding,
    AssemblyAISTTStream,
)

_MILLISECONDS_PER_SECOND = 1000
_HANDSHAKE_TIMEOUT_SECONDS = 10.0


class AssemblyAIAdapterConfig(BaseModel):
    """Select consumed vendor settings; unrelated shared STT settings stay outside."""

    model_config = ConfigDict(
        frozen=True, extra="ignore", hide_input_in_errors=True, allow_inf_nan=False
    )

    api_key: SecretStr
    model: str = Field(min_length=1)
    sample_rate: int = Field(default=16000, strict=True, gt=0)
    encoding: AssemblyAIEncoding = AssemblyAIEncoding.PCM_S16LE
    end_of_turn_confidence_threshold: float = Field(
        default=0.6, strict=True, ge=0, le=1
    )
    min_end_of_turn_silence_when_confident: int = Field(default=500, strict=True, ge=0)
    max_turn_silence: int = Field(default=1500, strict=True, gt=0)
    format_turns: StrictBool = True
    keyterms_prompt: tuple[str, ...] | None = Field(default=None, max_length=100)
    buffer_size_seconds: float = Field(default=0.05, strict=True, gt=0, le=1)

    @field_validator("encoding", mode="before")
    @classmethod
    def translate_pcm_encoding(cls, value: object) -> object:
        if value == STTEncoding.LINEAR16:
            return AssemblyAIEncoding.PCM_S16LE
        return value


class AssemblyAIAdapter(STTVendorAdapter):
    """Keep session acknowledgement, turn finality and vendor metadata distinct."""

    def __init__(self, config: object) -> None:
        super().__init__()
        self._config = AssemblyAIAdapterConfig.model_validate(config)
        self._is_connected = False
        self._stream: AssemblyAISTTStream | None = None
        self._session_id: str | None = None
        self._last_completed_turn: int | None = None
        self._stt = AssemblyAISTT(
            api_key=self._config.api_key.get_secret_value(),
            speech_model=self._config.model,
            sample_rate=self._config.sample_rate,
            encoding=self._config.encoding,
            end_of_turn_confidence_threshold=self._config.end_of_turn_confidence_threshold,
            min_end_of_turn_silence_when_confident=self._config.min_end_of_turn_silence_when_confident,
            max_turn_silence=self._config.max_turn_silence,
            format_turns=self._config.format_turns,
            keyterms_prompt=list(self._config.keyterms_prompt)
            if self._config.keyterms_prompt is not None
            else None,
            buffer_size_seconds=self._config.buffer_size_seconds,
        )

    async def connect(self) -> AssemblyAIAdapter:
        self._session_id = None
        self._last_completed_turn = None
        self._stream = self._stt.stream()
        try:
            async with asyncio.timeout(_HANDSHAKE_TIMEOUT_SECONDS):
                acknowledgement = await anext(self._stream)
                if not isinstance(acknowledgement, AssemblyAIBegin):
                    raise ValueError("AssemblyAI did not acknowledge the session.")
                self._convert_event(acknowledgement)
        except BaseException as error:
            await close_failed_websocket_connection(error, self.disconnect)
        self._is_connected = True
        return self

    def _convert_event(self, event: AssemblyAIEvent) -> STTEvent | None:
        """Project one vendor turn once; formatting updates cannot duplicate it."""
        if isinstance(event, AssemblyAIBegin):
            if (
                event.configuration is not None
                and event.configuration.model != self.model
            ):
                raise ValueError("AssemblyAI acknowledged a different speech model.")
            self._session_id = event.id
            self._last_completed_turn = None
            return None
        if isinstance(event, AssemblyAIError):
            return STTEvent(
                type=STTEventType.ERROR,
                provider=STTProvider.ASSEMBLYAI,
                model=self.model,
                session_id=self._session_id or "",
                error=STTError(
                    message=event.error, code=str(event.error_code), recoverable=False
                ),
            )
        if isinstance(event, AssemblyAITermination):
            return STTEvent(
                type=STTEventType.RECOGNITION_USAGE,
                provider=STTProvider.ASSEMBLYAI,
                model=self.model,
                session_id=self._session_id or "",
                usage=RecognitionUsage(audio_duration=event.audio_duration_seconds),
                vendor_metadata={
                    "session_duration_seconds": event.session_duration_seconds
                },
            )
        if self._session_id is None:
            raise ValueError(
                "AssemblyAI recognition arrived before session acknowledgement."
            )
        if isinstance(event, AssemblyAISpeechStarted):
            return STTEvent(
                type=STTEventType.SPEECH_START,
                provider=STTProvider.ASSEMBLYAI,
                model=self.model,
                session_id=self._session_id,
                audio_start_ms=event.timestamp,
                confidence=event.confidence,
            )
        return self._convert_turn(event)

    def _convert_turn(self, event: AssemblyAITurn) -> STTEvent | None:
        if (
            self._last_completed_turn is not None
            and event.turn_order <= self._last_completed_turn
        ):
            return None
        if not event.transcript:
            return None
        final = event.end_of_turn and (
            not self._config.format_turns or event.turn_is_formatted
        )
        # The vendor sends unformatted and formatted finals for the same turn
        # when format_turns is enabled. The first remains provisional.
        kind = (
            STTEventType.TRANSCRIPT_FINAL if final else STTEventType.TRANSCRIPT_PARTIAL
        )
        words = tuple(
            TimedWord(
                word=word.text,
                start_time=word.start / _MILLISECONDS_PER_SECOND,
                end_time=word.end / _MILLISECONDS_PER_SECOND,
                confidence=word.confidence,
            )
            for word in event.words
        )
        result = STTEvent(
            type=kind,
            provider=STTProvider.ASSEMBLYAI,
            model=self.model,
            session_id=self._session_id or "",
            provider_request_id=f"{self._session_id}:{event.turn_order}",
            transcript=event.transcript,
            words=words,
            language=event.language_code,
            speaker_id=event.speaker_label,
            audio_start_ms=event.words[0].start if event.words else None,
            audio_end_ms=event.words[-1].end if event.words else None,
            vendor_metadata=event.model_dump(
                mode="json",
                include={
                    "turn_order",
                    "turn_is_formatted",
                    "end_of_turn_confidence",
                    "language_confidence",
                    "words",
                },
                exclude_none=True,
            ),
        )
        if final:
            self._last_completed_turn = event.turn_order
        return result

    async def send_audio(self, audio_data: bytes) -> None:
        if not self._is_connected or self._stream is None:
            raise STTConnectionClosed("AssemblyAI stream is not connected.")
        await self._stream.push_audio(audio_data)

    async def _receive_raw_event(self, timeout_ms: int = 100) -> AssemblyAIEvent | None:
        if self._stream is None:
            raise STTConnectionClosed("AssemblyAI stream is not connected.")
        try:
            return await asyncio.wait_for(
                anext(self._stream), timeout=timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None
        except StopAsyncIteration as error:
            self._is_connected = False
            raise STTConnectionClosed("AssemblyAI stream ended.") from error

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        event = await self._receive_raw_event(timeout_ms)
        if event is None:
            return None
        return self._convert_event(event)

    async def keepalive(self) -> None:
        """No inactivity_timeout is requested; AssemblyAI needs no keepalive."""

    async def disconnect(self) -> None:
        self._is_connected = False
        stream, self._stream = self._stream, None
        try:
            if stream is not None:
                await stream.aclose()
        finally:
            await self._stt.aclose()

    async def flush(self) -> None:
        """Flush buffered PCM then request the current vendor turn's final result."""
        if self._stream is None or not self.is_connected:
            raise STTConnectionClosed("AssemblyAI stream is not connected.")
        await self._stream.flush()

    @property
    def is_connected(self) -> bool:
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
            batch_recognize=STTCapabilitySupport.UNSUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            vad_events=STTCapabilitySupport.UNSUPPORTED,
            turn_detection=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            custom_vocabulary=STTCapabilitySupport.SUPPORTED,
            speaker_labels=STTCapabilitySupport.UNSUPPORTED,
            language_detection=STTCapabilitySupport.UNSUPPORTED,
        )
