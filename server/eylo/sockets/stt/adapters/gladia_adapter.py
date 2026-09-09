"""Translate native Gladia hypotheses and retain terminal output through shutdown."""

from __future__ import annotations

import asyncio

from eylo.common.contracts.speech_runtime import SpeechOptionState
from eylo.sockets.stt.adapters.connection_errors import (
    close_failed_websocket_connection,
)
from eylo.sockets.stt.adapters.gladia_events import gladia_stt_event
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    STTConnectionClosed,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTCapabilitySupport,
    STTEvent,
    STTProvider,
)
from eylo.sockets.voice.vendors.gladia.stt import GladiaSTT, GladiaSTTStream
from eylo.sockets.voice.vendors.gladia.wire import GladiaConfig

_RESPONSE_QUEUE_CAPACITY = 1000
_FINAL_FORWARD_TIMEOUT_SECONDS = 2.0
_MILLISECONDS_PER_SECOND = 1000


class GladiaAdapter(STTVendorAdapter):
    """Own canonical output and one native attempt; no dictionary event bridge."""

    def __init__(self, config: object) -> None:
        self._config = GladiaConfig.model_validate(config)
        self._stt = GladiaSTT(self._config)
        self._stream: GladiaSTTStream | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[STTEvent] = asyncio.Queue(
            maxsize=_RESPONSE_QUEUE_CAPACITY
        )
        self._stream_error: Exception | None = None
        self._disconnect_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def connect(self) -> GladiaAdapter:
        async with self._lifecycle_lock:
            if self._receive_task is not None and not self._receive_task.done():
                return self
            await self._disconnect()
            if self._stream is not None and not self._stream.can_replace:
                raise STTConnectionRetryUnsafe(
                    "Gladia's previous session outcome is unresolved; replacement is refused."
                )
            self._disconnect_task = None
            self._stream_error = None
            self._response_queue = asyncio.Queue(maxsize=_RESPONSE_QUEUE_CAPACITY)
            self._stream = self._stt.stream()
            try:
                await self._stream.start()
            except BaseException as error:
                await close_failed_websocket_connection(error, self._disconnect)
            self._receive_task = asyncio.create_task(self._receive_events())
            return self

    async def _receive_events(self) -> None:
        stream = self._stream
        if stream is None:
            raise STTConnectionClosed("Gladia stream is unavailable.")
        try:
            async for native in stream:
                if (
                    not native.data.is_final
                    and self._config.interim_results is SpeechOptionState.DISABLED
                ):
                    continue
                event = gladia_stt_event(native)
                if event.transcript:
                    await self._response_queue.put(event)
        except Exception as error:
            self._stream_error = error

    async def send_audio(self, audio_data: bytes) -> None:
        stream = self._stream
        if stream is None or self._disconnect_task is not None:
            raise STTConnectionClosed("Gladia STT is not accepting audio.")
        await stream.send_audio(audio_data)

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        if not self._response_queue.empty():
            return self._response_queue.get_nowait()
        if self._stream_error is not None:
            error = self._stream_error
            self._stream_error = None
            raise error
        if not self.is_connected:
            raise STTConnectionClosed("Gladia STT stream ended.")
        try:
            return await asyncio.wait_for(
                self._response_queue.get(), timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._close())
            self._disconnect_task.add_done_callback(_observe_task)
        await asyncio.shield(self._disconnect_task)

    async def _close(self) -> None:
        stream, receiver = self._stream, self._receive_task
        finalization_error: Exception | None = None
        try:
            if stream is not None:
                try:
                    await stream.aclose()
                except STTFinalizationFailed as error:
                    finalization_error = error
            if receiver is not None:
                try:
                    async with asyncio.timeout(_FINAL_FORWARD_TIMEOUT_SECONDS):
                        await asyncio.shield(receiver)
                except Exception as error:
                    finalization_error = error
        finally:
            if receiver is not None:
                if not receiver.done():
                    receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
                self._receive_task = None
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Gladia closed before final output was forwarded."
            ) from finalization_error

    @property
    def is_connected(self) -> bool:
        return (
            self._stream_error is not None
            or not self._response_queue.empty()
            or (self._receive_task is not None and not self._receive_task.done())
        )

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def provider(self) -> str:
        return STTProvider.GLADIA.value

    @property
    def model(self) -> str:
        return ""

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
        )

    async def keepalive(self) -> None:
        """WebSocket ping/pong is transport-owned; it is not an audio frame."""
        return None

    async def flush(self) -> None:
        """Stopping recording is terminal; no in-stream flush command is invented."""
        return None


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
