"""Translate Sarvam synthesis streams into typed audio and turn completion."""

import asyncio
import logging
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from eylo.sockets.tts.adapters.sarvam_tts_wire import (
    SARVAM_KEY_HEADER,
    SARVAM_PCM_ENCODING,
    SARVAM_STREAM_URL,
    SarvamAudio,
    SarvamConfigure,
    SarvamFlush,
    SarvamOutputError,
    SarvamPing,
    SarvamStreamState,
    SarvamTTSConfig,
    SarvamText,
    SarvamTextData,
    SarvamTuning,
    parse_output,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import (
    RetryOptions,
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)

logger = logging.getLogger(__name__)


class SarvamContractAdapter(TTSVendorAdapter):
    """Own native streams; interruption retires audio without replaying text."""

    def __init__(
        self, config: TTSConfig, retry_options: RetryOptions | None = None
    ) -> None:
        self._input = SarvamTTSConfig.from_runtime(config)
        contract = TTSConfig(
            vendor=TTSProvider.SARVAM,
            model=self._input.model.value,
            voice=self._input.voice,
            language=self._input.language.value,
            sample_rate=self._input.sample_rate.value,
            encoding=SARVAM_PCM_ENCODING,
            retry=config.retry,
        )
        super().__init__(contract, retry_options)
        self._ws: ClientConnection | None = None
        self._state = SarvamStreamState.DISCONNECTED
        self._turn_complete = False
        self._completion_error: TTSConnectionFailed | None = None
        self._stream_available = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()

    @property
    def config(self) -> TTSConfig:
        return self._contract_config

    @property
    def provider(self) -> str:
        return TTSProvider.SARVAM.value

    @property
    def model(self) -> str:
        return self._input.model.value

    @property
    def sample_rate(self) -> int:
        return self._input.sample_rate.value

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.UNSUPPORTED,
            native_interruption=TTSCapabilitySupport.UNSUPPORTED,
            aligned_transcript=TTSCapabilitySupport.UNSUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.SUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.UNSUPPORTED,
        )

    @property
    def is_connected(self) -> bool:
        """A live adapter session can acquire a new stream after interruption."""
        return self._state not in (
            SarvamStreamState.DISCONNECTED,
            SarvamStreamState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._turn_complete

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    def unsupported_options(self) -> tuple[str, ...]:
        return self._input.unsupported_options()

    def tuning(self) -> SarvamTuning:
        return self._input.tuning()

    def url(self) -> str:
        query = urlencode({"model": self.model, "send_completion_event": "true"})
        return f"{SARVAM_STREAM_URL}?{query}"

    def initial_message(self) -> SarvamConfigure:
        unsupported = self.unsupported_options()
        if unsupported:
            logger.warning(
                "Sarvam model %s ignores configured options: %s",
                self.model,
                ", ".join(unsupported),
            )
        return self._input.initial_message()

    async def connect(self) -> ClientConnection:
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self._ws
            ws = await self._open_stream()
            self._state = SarvamStreamState.READY
            self._turn_complete = False
            self._completion_error = None
            return ws

    async def _open_stream(self) -> ClientConnection:
        """Publish only initialized sockets; a failed acquisition still owns close."""
        ws: ClientConnection | None = None
        try:
            ws = await connect(
                self.url(),
                additional_headers={SARVAM_KEY_HEADER: self._input.api_key},
                open_timeout=self._retry_options.timeout_seconds,
                close_timeout=self._retry_options.timeout_seconds,
            )
            await ws.send(self.initial_message().model_dump_json(exclude_none=True))
        except asyncio.CancelledError:
            self._state = SarvamStreamState.DISCONNECTED
            self._stream_available.set()
            if ws is not None:
                await self._close(ws)
            raise
        except Exception:
            error = TTSConnectionFailed("Sarvam TTS connection failed.")
            self._state = SarvamStreamState.FAILED
            self._completion_error = error
            self._stream_available.set()
            if ws is not None:
                await self._close(ws)
            raise error from None
        self._ws = ws
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
            logger.warning("Sarvam TTS close failed")

    async def _close(self, ws: ClientConnection) -> None:
        # WebSocket close_timeout bounds this task. Keep ownership even if the
        # caller is cancelled; preserve its original error if close also fails.
        task = self._start_close(ws)
        try:
            await asyncio.shield(task)
        except Exception:
            pass

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            self._state = SarvamStreamState.DISCONNECTED
            self._stream_available.set()
            ws, self._ws = self._ws, None
            if ws is not None:
                await self._close(ws)
            if self._closing_tasks:
                closing = asyncio.gather(*self._closing_tasks, return_exceptions=True)
                await asyncio.shield(closing)

    async def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._completion_error = error
            self._state = SarvamStreamState.FAILED
            self._stream_available.set()
        await self._close(ws)

    async def _send(self, message: SarvamText | SarvamFlush | SarvamPing) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionClosed("Sarvam TTS is not connected.")
        try:
            await ws.send(message.model_dump_json())
        except asyncio.CancelledError:
            await self._fail(ws, TTSConnectionFailed("Sarvam TTS send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Sarvam TTS send failed.")
            await self._fail(ws, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        message = SarvamText(data=SarvamTextData(text=text))
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is SarvamStreamState.DISCONNECTED:
                raise TTSConnectionClosed("Sarvam TTS is not connected.")
            if self._state is SarvamStreamState.DRAINING:
                raise TTSConnectionFailed("Sarvam TTS previous turn is still draining.")
            if self._ws is None:
                await self._open_stream()
            self._state = SarvamStreamState.STREAMING
            self._turn_complete = False
            await self._send(message)

    async def flush(self) -> None:
        async with self._lifecycle_lock:
            if self._state is SarvamStreamState.STREAMING:
                self._state = SarvamStreamState.DRAINING
                await self._send(SarvamFlush())

    async def keepalive(self) -> None:
        async with self._lifecycle_lock:
            if self._ws is not None and self._state in (
                SarvamStreamState.READY,
                SarvamStreamState.STREAMING,
            ):
                await self._send(SarvamPing())

    async def receive_audio(self) -> bytes | None:
        """Receive timeout is not completion; stale streams cannot publish audio."""
        if self._state is SarvamStreamState.DISCONNECTED:
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
            message = parse_output(raw)
            if isinstance(message, SarvamAudio):
                return message.data.audio_bytes()
            if self._state is not SarvamStreamState.DRAINING:
                raise SarvamOutputError(
                    "Sarvam TTS completed before input was finalized."
                )
            self._turn_complete = True
            self._state = SarvamStreamState.READY
            self._ws = None
            self._stream_available.clear()
            self._start_close(ws)
            return None
        except ConnectionClosed:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Sarvam TTS stream ended before completion.")
            await self._fail(ws, error)
            raise error from None
        except SarvamOutputError as error:
            await self._fail(ws, error)
            raise
        except Exception:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Sarvam TTS receive failed.")
            await self._fail(ws, error)
            raise error from None
        # websockets.recv cancellation is safe; the manager uses it for polling.

    async def handle_interruption(self) -> None:
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            self._state = SarvamStreamState.READY
            self._stream_available.clear()
            ws, self._ws = self._ws, None
            self._turn_complete = True
            if ws is not None:
                await self._close(ws)
