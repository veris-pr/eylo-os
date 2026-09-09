"""Own Deepgram Aura streams and translate native output into TTS turn state."""

import asyncio
import logging
from typing import Self
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from eylo.sockets.tts.adapters.deepgram_tts_wire import (
    DEEPGRAM_AUTH_HEADER,
    DeepgramClear,
    DeepgramCleared,
    DeepgramFlush,
    DeepgramFlushed,
    DeepgramSpeak,
    DeepgramTTSConfig,
    DeepgramTTSOutputError,
    DeepgramTTSState,
    DeepgramTTSWarning,
    parse_control,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSCapabilities, TTSConfig, TTSProvider

logger = logging.getLogger(__name__)


class _DeepgramConnect(connect):
    """Keep the API key on its configured endpoint; never follow redirects.

    websockets 15.0.1 forwards additional headers on redirected handshakes.
    Its redirect hook returns the original error to refuse that extra request.
    """

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


class DeepgramTTSAdapter(TTSVendorAdapter):
    """The manager owns receiving; no detached queue can hide EOF or failure."""

    def __init__(self, config: DeepgramTTSConfig) -> None:
        self._config = DeepgramTTSConfig.model_validate(config)
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.DEEPGRAM,
                model=self._config.model,
                sample_rate=self._config.sample_rate.value,
                encoding=self._config.encoding.value,
            )
        )
        self._ws: ClientConnection | None = None
        self._state = DeepgramTTSState.DISCONNECTED
        self._turn_complete = False
        self._completion_error: TTSConnectionFailed | None = None
        self._stream_available = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()

    def _build_ws_url(self) -> str:
        query = urlencode(
            {
                "model": self._config.model,
                "encoding": self._config.encoding.value,
                "container": "none",
                "sample_rate": self._config.sample_rate.value,
            }
        )
        separator = "&" if "?" in self._config.ws_url else "?"
        return f"{self._config.ws_url}{separator}{query}"

    async def connect(self) -> Self:
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self
            await self._open_stream()
            self._state = DeepgramTTSState.READY
            self._completion_error = None
            self._turn_complete = False
            return self

    async def _open_stream(self) -> None:
        """The WebSocket library owns cleanup until acquisition returns."""
        try:
            ws = await _DeepgramConnect(
                self._build_ws_url(),
                additional_headers={
                    DEEPGRAM_AUTH_HEADER: f"Token {self._config.api_key}"
                },
                open_timeout=self._retry_options.timeout_seconds,
                close_timeout=self._retry_options.timeout_seconds,
            )
        except asyncio.CancelledError:
            self._state = DeepgramTTSState.DISCONNECTED
            self._stream_available.set()
            raise
        except Exception:
            error = TTSConnectionFailed("Deepgram TTS connection failed.")
            self._completion_error = error
            self._state = DeepgramTTSState.FAILED
            self._stream_available.set()
            raise error from None
        self._ws = ws
        self._stream_available.set()

    def _start_close(self, ws: ClientConnection) -> asyncio.Task[None]:
        task = asyncio.create_task(ws.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closed)
        return task

    def _closed(self, task: asyncio.Task[None]) -> None:
        self._closing_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Deepgram TTS close failed")

    async def _close(self, ws: ClientConnection) -> None:
        # close_timeout bounds native teardown, which survives caller cancellation.
        task = self._start_close(ws)
        try:
            await asyncio.shield(task)
        except Exception:
            pass

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            self._state = DeepgramTTSState.DISCONNECTED
            self._stream_available.set()
            ws, self._ws = self._ws, None
            if ws is not None:
                # A protocol close does not request more synthesis via Flush/Close.
                await self._close(ws)
            if self._closing_tasks:
                closing = asyncio.gather(*self._closing_tasks, return_exceptions=True)
                await asyncio.shield(closing)

    async def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._completion_error = error
            self._turn_complete = False
            self._state = DeepgramTTSState.FAILED
            self._stream_available.set()
        await self._close(ws)

    async def _send(
        self, message: DeepgramSpeak | DeepgramFlush | DeepgramClear
    ) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionClosed("Deepgram TTS is not connected.")
        try:
            await ws.send(message.model_dump_json())
        except asyncio.CancelledError:
            await self._fail(ws, TTSConnectionFailed("Deepgram TTS send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Deepgram TTS send failed.")
            await self._fail(ws, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        message = DeepgramSpeak(text=text)
        if not text.strip():
            return
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is DeepgramTTSState.DISCONNECTED:
                raise TTSConnectionClosed("Deepgram TTS is not connected.")
            if self._state is DeepgramTTSState.DRAINING:
                raise TTSConnectionFailed(
                    "Deepgram TTS previous turn is still draining."
                )
            if self._ws is None:
                await self._open_stream()
            self._state = DeepgramTTSState.STREAMING
            self._turn_complete = False
            await self._send(message)

    async def flush(self) -> None:
        async with self._lifecycle_lock:
            if self._state is DeepgramTTSState.STREAMING:
                self._state = DeepgramTTSState.DRAINING
                await self._send(DeepgramFlush())

    async def keepalive(self) -> None:
        """WebSocket ping/pong owns liveness; Flush spends synthesis quota."""

    async def receive_audio(self) -> bytes | None:
        """Only Flushed completes a turn; polling, warnings and EOF do not."""
        if self._state is DeepgramTTSState.DISCONNECTED:
            return None
        await self._stream_available.wait()
        ws = self._ws
        if ws is None:
            if self._completion_error is not None:
                raise self._completion_error
            return None
        try:
            raw = await ws.recv()
            if self._ws is not ws:
                return None
            if isinstance(raw, bytes):
                if self._state not in (
                    DeepgramTTSState.STREAMING,
                    DeepgramTTSState.DRAINING,
                ):
                    raise DeepgramTTSOutputError(
                        "Deepgram TTS audio has no active turn."
                    )
                return raw
            message = parse_control(raw)
            if isinstance(message, DeepgramFlushed):
                if self._state is not DeepgramTTSState.DRAINING:
                    raise DeepgramTTSOutputError(
                        "Deepgram TTS completed before input was finalized."
                    )
                self._turn_complete = True
                self._state = DeepgramTTSState.READY
                self._ws = None
                self._stream_available.clear()
                self._start_close(ws)
            elif isinstance(message, DeepgramCleared):
                # Clear is sent only while retiring a stream, never a new turn.
                raise DeepgramTTSOutputError(
                    "Unexpected Deepgram TTS clear acknowledgement."
                )
            elif isinstance(message, DeepgramTTSWarning):
                logger.warning("Deepgram TTS provider warning")
            return None
        except ConnectionClosed:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Deepgram TTS stream ended before completion.")
            await self._fail(ws, error)
            raise error from None
        except DeepgramTTSOutputError as error:
            await self._fail(ws, error)
            raise
        except Exception:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Deepgram TTS receive failed.")
            await self._fail(ws, error)
            raise error from None
        # Cancelled recv is safe in websockets 15; polling retains stream ownership.

    async def handle_interruption(self) -> None:
        """Clear native work and retire its untagged audio before accepting input."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            ws = self._ws
            if ws is not None:
                # Detach before sending Clear: receive may wake on a late frame
                # while send awaits I/O. That frame has already lost authority.
                self._ws = None
                self._stream_available.clear()
                self._state = DeepgramTTSState.READY
                self._turn_complete = True
                try:
                    await ws.send(DeepgramClear().model_dump_json())
                except asyncio.CancelledError:
                    self._state = DeepgramTTSState.DISCONNECTED
                    self._stream_available.set()
                    raise
                except Exception:
                    error = TTSConnectionFailed("Deepgram TTS interruption failed.")
                    self._completion_error = error
                    self._state = DeepgramTTSState.FAILED
                    self._turn_complete = False
                    self._stream_available.set()
                    raise error from None
                finally:
                    await self._close(ws)

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate.value

    @property
    def provider(self) -> str:
        return TTSProvider.DEEPGRAM.value

    @property
    def is_connected(self) -> bool:
        return self._state not in (
            DeepgramTTSState.DISCONNECTED,
            DeepgramTTSState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._turn_complete

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def capabilities(self) -> TTSCapabilities:
        """Interruption is transport-isolated, not persistent native context reuse."""
        return TTSCapabilities(
            streaming=True,
            batch_synthesize=False,
            native_interruption=False,
            aligned_transcript=False,
            emotion_control=False,
            speed_control=False,
            voice_cloning=False,
            context_continuity=False,
        )
