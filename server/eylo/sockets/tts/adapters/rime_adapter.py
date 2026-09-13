"""Translate Rime JSON synthesis into ordered raw audio with owned streams."""

import asyncio
import logging
from collections.abc import AsyncIterator

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK
from websockets.frames import CloseCode

from eylo.sockets.tts.adapters.rime_tts_wire import (
    MAX_EVENT_BYTES,
    MAX_TEXT_CHARACTERS,
    PCM_SAMPLE_BYTES,
    RimeAudioFormat,
    RimeChunk,
    RimeEndInput,
    RimeError,
    RimeOutputError,
    RimeStreamState,
    RimeTTSConfig,
    RimeText,
    parse_output,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import (
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)

logger = logging.getLogger(__name__)


class _RimeConnect(connect):
    """Pin credential-bearing handshakes; websockets otherwise follows redirects."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


class RimeTTSAdapter(TTSVendorAdapter):
    """One native stream per turn; completion and interruption retire its socket.

    A batch done is not proof that all input was synthesized. Flush sends EOS
    and waits for the normal native close after all audio, including an already
    empty final buffer. The next turn opens the same operator configuration.
    """

    def __init__(self, config: RimeTTSConfig) -> None:
        self._config = RimeTTSConfig.model_validate(config)
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.RIME,
                model=self._config.model,
                voice=self._config.voice,
                sample_rate=self._config.sample_rate,
                encoding=self._config.audio_format.value,
            )
        )
        self._ws: ClientConnection | None = None
        self._state = RimeStreamState.DISCONNECTED
        self._completion_error: TTSConnectionFailed | None = None
        self._stream_available = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()
        self._pcm_tail = b""
        self._received_audio = False

    async def connect(self) -> ClientConnection:
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self._ws
            await self._finish_closing()
            return await self._open_stream()

    async def _open_stream(self) -> ClientConnection:
        """Publish only an acquired socket; callers hold the lifecycle lock."""
        try:
            ws = await _RimeConnect(
                self._config.query().url(),
                additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
                open_timeout=self._retry_options.timeout_seconds,
                close_timeout=self._retry_options.timeout_seconds,
                max_size=MAX_EVENT_BYTES,
            )
        except asyncio.CancelledError:
            self._state = RimeStreamState.DISCONNECTED
            self._stream_available.set()
            raise
        except Exception:
            error = TTSConnectionFailed("Rime connection failed.")
            self._state = RimeStreamState.FAILED
            self._completion_error = error
            self._stream_available.set()
            raise error from None
        self._ws = ws
        self._state = RimeStreamState.READY
        self._completion_error = None
        self._pcm_tail = b""
        self._received_audio = False
        self._stream_available.set()
        return ws

    def _start_close(self, ws: ClientConnection) -> asyncio.Task[None]:
        task = asyncio.create_task(ws.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closed)
        return task

    def _closed(self, task: asyncio.Task[None]) -> None:
        self._closing_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Rime connection cleanup failed")

    async def _finish_closing(self) -> None:
        if self._closing_tasks:
            closing = asyncio.gather(*self._closing_tasks, return_exceptions=True)
            await asyncio.shield(closing)

    async def _close(self, ws: ClientConnection) -> None:
        """Retain cleanup ownership even if the caller is cancelled again."""
        task = self._start_close(ws)
        try:
            await asyncio.shield(task)
        except Exception:
            # The callback consumes the error without replacing the original one.
            pass

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            self._state = RimeStreamState.DISCONNECTED
            self._stream_available.set()
            ws, self._ws = self._ws, None
            self._pcm_tail = b""
            if ws is not None:
                await self._close(ws)
            await self._finish_closing()

    async def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._state = RimeStreamState.FAILED
            self._completion_error = error
            self._pcm_tail = b""
            self._stream_available.set()
        await self._close(ws)

    async def _send(self, message: RimeText | RimeEndInput) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionClosed("Rime TTS is not connected.")
        try:
            await ws.send(message.model_dump_json())
        except asyncio.CancelledError:
            await self._fail(ws, TTSConnectionFailed("Rime send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Rime send failed.")
            await self._fail(ws, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        if not text or not text.strip():
            return
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is RimeStreamState.DISCONNECTED:
                raise TTSConnectionClosed("Rime TTS is not connected.")
            if self._state is RimeStreamState.DRAINING:
                raise TTSConnectionFailed("Rime previous turn is still draining.")
            if self._ws is None:
                await self._finish_closing()
                await self._open_stream()
            self._state = RimeStreamState.STREAMING
            for offset in range(0, len(text), MAX_TEXT_CHARACTERS):
                await self._send(
                    RimeText(text=text[offset : offset + MAX_TEXT_CHARACTERS])
                )

    async def flush(self) -> None:
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is RimeStreamState.STREAMING:
                self._state = RimeStreamState.DRAINING
                await self._send(RimeEndInput())

    async def receive_audio(self) -> bytes | None:
        """Pull with transport backpressure; cancellation of recv is safe."""
        if self._state is RimeStreamState.DISCONNECTED:
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
            event = parse_output(raw)
            if isinstance(event, RimeError):
                raise RimeOutputError("Rime rejected synthesis input.")
            if not isinstance(event, RimeChunk):
                return None
            audio = event.audio_bytes()
            if self._config.audio_format is RimeAudioFormat.PCM:
                audio = self._pcm_tail + audio
                aligned = len(audio) - len(audio) % PCM_SAMPLE_BYTES
                self._pcm_tail = audio[aligned:]
                audio = audio[:aligned]
            self._received_audio = self._received_audio or bool(audio)
            return audio or None
        except ConnectionClosedOK as closed:
            if self._ws is not ws:
                return None
            if (
                self._state is RimeStreamState.DRAINING
                and closed.rcvd is not None
                and closed.rcvd.code == CloseCode.NORMAL_CLOSURE
                and not self._pcm_tail
                and self._received_audio
            ):
                self._ws = None
                self._state = RimeStreamState.COMPLETE
                self._stream_available.clear()
                self._start_close(ws)
                return None
            error = RimeOutputError("Rime closed before delivering a complete turn.")
        except ConnectionClosed:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Rime stream closed unexpectedly.")
        except RimeOutputError as invalid_output:
            error = invalid_output
        except Exception:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Rime receive failed.")
        await self._fail(ws, error)
        raise error from None

    async def handle_interruption(self) -> None:
        """Close the old stream so late audio cannot enter a subsequent turn."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            self._state = RimeStreamState.COMPLETE
            self._stream_available.clear()
            self._pcm_tail = b""
            ws, self._ws = self._ws, None
            if ws is not None:
                await self._close(ws)

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Metadata events are not EOF; drain until the owned turn completes."""
        if not text or not text.strip():
            return
        await self.send_text(text)
        await self.flush()
        while not self.is_turn_complete:
            audio = await self.receive_audio()
            if audio is not None:
                yield audio

    async def keepalive(self) -> None:
        # websockets owns bounded ping/pong keepalive for each open connection.
        return None

    @property
    def is_connected(self) -> bool:
        return self._state not in (
            RimeStreamState.DISCONNECTED,
            RimeStreamState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._state is RimeStreamState.COMPLETE

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def provider(self) -> str:
        return TTSProvider.RIME.value

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def capabilities(self) -> TTSCapabilities:
        """Expose implemented behavior, not unused vendor-native features."""
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED, sample_rates=(self.sample_rate,)
        )
