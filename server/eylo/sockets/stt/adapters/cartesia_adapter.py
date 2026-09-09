"""Project native Cartesia STT responses without fabricated speech or confidence."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

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
from eylo.sockets.voice.vendors.cartesia.stt import CartesiaSTT, CartesiaSTTStream
from eylo.sockets.voice.vendors.cartesia.stt_wire import (
    CartesiaSTTDone,
    CartesiaSTTEncoding,
    CartesiaSTTError,
    CartesiaSTTEvent,
    CartesiaSTTFlushDone,
)

_MILLISECONDS_PER_SECOND = 1000


class CartesiaAdapterConfig(BaseModel):
    """Select consumed settings; unrelated shared STT settings are not native fields."""

    model_config = ConfigDict(frozen=True, extra="ignore", hide_input_in_errors=True)

    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)
    model: str = Field(min_length=1)
    language: str | None = None
    sample_rate: int = Field(default=16000, strict=True, gt=0)
    encoding: CartesiaSTTEncoding = CartesiaSTTEncoding.PCM_S16LE

    @field_validator("encoding", mode="before")
    @classmethod
    def translate_pcm_encoding(cls, value: object) -> object:
        if value == STTEncoding.LINEAR16:
            return CartesiaSTTEncoding.PCM_S16LE
        return value


class CartesiaAdapter(STTVendorAdapter):
    """One native connection owns authentication, response correlation and cleanup."""

    def __init__(self, config: object) -> None:
        super().__init__()
        self._config = CartesiaAdapterConfig.model_validate(config)
        self._stream: CartesiaSTTStream | None = None
        self._session_id: str | None = None
        self._is_connected = False
        self._stt = CartesiaSTT(
            api_key=self._config.api_key.get_secret_value(),
            model=self._config.model,
            language=self._config.language,
            sample_rate=self._config.sample_rate,
            encoding=self._config.encoding,
        )

    async def connect(self) -> CartesiaAdapter:
        if self.is_connected:
            return self
        if self._stream is not None:
            await self.disconnect()
        self._session_id = None
        self._stream = self._stt.stream()
        try:
            await self._stream.connect()
        except BaseException as error:
            await close_failed_websocket_connection(error, self.disconnect)
        self._is_connected = True
        return self

    def _convert_event(self, event: CartesiaSTTEvent) -> STTEvent | None:
        """The vendor request ID identifies the connection, not a deduplication key."""
        if event.request_id is not None:
            if self._session_id is not None and event.request_id != self._session_id:
                raise ValueError("Cartesia changed the active connection identity.")
            self._session_id = event.request_id
        if isinstance(event, CartesiaSTTError):
            return STTEvent(
                type=STTEventType.ERROR,
                provider=STTProvider.CARTESIA,
                model=self.model,
                session_id=self._session_id or "",
                provider_request_id=event.request_id,
                error=STTError(
                    message=event.message,
                    code=event.error_code or str(event.status_code),
                    recoverable=False,
                ),
                vendor_metadata={"status_code": event.status_code},
            )
        if isinstance(event, (CartesiaSTTFlushDone, CartesiaSTTDone)):
            return None
        if not event.text:
            return None
        return STTEvent(
            type=STTEventType.TRANSCRIPT_FINAL
            if event.is_final
            else STTEventType.TRANSCRIPT_PARTIAL,
            provider=STTProvider.CARTESIA,
            model=self.model,
            session_id=event.request_id,
            provider_request_id=event.request_id,
            transcript=event.text,
            transcript_form=STTTranscriptForm.DELTA,
            language=event.language,
            words=tuple(
                TimedWord(word=word.word, start_time=word.start, end_time=word.end)
                for word in event.words
            ),
            audio_start_ms=round(event.words[0].start * _MILLISECONDS_PER_SECOND)
            if event.words
            else None,
            audio_end_ms=round(event.words[-1].end * _MILLISECONDS_PER_SECOND)
            if event.words
            else None,
            vendor_metadata=event.model_dump(
                mode="json", include={"duration"}, exclude_none=True
            ),
        )

    async def send_audio(self, audio_data: bytes) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Cartesia stream is not connected.")
        try:
            await self._stream.push_audio(audio_data)
        except BaseException:
            self._is_connected = False
            raise

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        if self._stream is None:
            raise STTConnectionClosed("Cartesia stream is not connected.")
        try:
            event = await asyncio.wait_for(
                anext(self._stream), timeout=timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None
        except StopAsyncIteration as error:
            self._is_connected = False
            raise STTConnectionClosed("Cartesia stream ended.") from error
        except Exception:
            self._is_connected = False
            raise
        return self._convert_event(event)

    async def flush(self) -> None:
        if self._stream is None:
            raise STTConnectionClosed("Cartesia stream is not connected.")
        try:
            await self._stream.flush()
        except BaseException:
            self._is_connected = False
            raise

    async def keepalive(self) -> None:
        """The native aiohttp connection owns WebSocket ping/pong heartbeats."""

    async def disconnect(self) -> None:
        self._is_connected = False
        stream, self._stream = self._stream, None
        try:
            if stream is not None:
                await stream.aclose()
        finally:
            await self._stt.aclose()

    @property
    def is_connected(self) -> bool:
        """Remain readable through queued terminal output, even after native close."""
        return self._is_connected

    @property
    def model(self) -> str:
        return self._stt.model

    @property
    def provider(self) -> str:
        return self._stt.provider

    @property
    def sample_rate(self) -> int:
        return self._stt.sample_rate

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            interim_results=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
        )
