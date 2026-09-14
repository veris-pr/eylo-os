"""Translate ElevenLabs native WebSocket messages into the TTS audio contract."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from eylo.sockets.tts.adapters.elevenlabs_wire import (
    ElevenLabsEndInput,
    ElevenLabsInitialize,
    ElevenLabsInput,
    ElevenLabsOutputError,
    ElevenLabsStreamState,
    ElevenLabsText,
    ElevenLabsVoiceSettings,
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

PROVIDER = TTSProvider.ELEVENLABS
# PCM is a transport fact. No model or voice is supplied by the platform.
OUTPUT_FORMAT = "pcm_16000"
SAMPLE_RATE = 16000
_STREAM_URL = "wss://api.elevenlabs.io/v1/text-to-speech"
_CONTROL_TEXT = " "


class ElevenLabsTTSAdapter(TTSVendorAdapter):
    """Own one initialized stream, its validated native input and late cleanup."""

    def __init__(
        self,
        config: TTSConfig,
        retry_options: RetryOptions | None = None,
    ) -> None:
        self._input = ElevenLabsInput.from_config(config)
        contract = config.model_copy(
            update={"sample_rate": SAMPLE_RATE, "encoding": "pcm_s16le"}
        )
        super().__init__(contract, retry_options)
        self._ws: ClientConnection | None = None
        self._state = ElevenLabsStreamState.DISCONNECTED
        self._stream_available = asyncio.Event()
        self._turn_complete = False
        self._completion_error: TTSConnectionFailed | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()

    def voice_settings(self) -> ElevenLabsVoiceSettings:
        return self._input.options.voice_settings()

    @property
    def config(self) -> TTSConfig:
        return self._contract_config

    def query_params(self) -> dict[str, str]:
        params = {"output_format": OUTPUT_FORMAT, "model_id": self._input.model}
        if self._input.language is not None:
            params["language_code"] = self._input.language
        return params

    @property
    def provider(self) -> str:
        return PROVIDER.value

    @property
    def model(self) -> str:
        return self._input.model

    @property
    def sample_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def capabilities(self) -> TTSCapabilities:
        """Interruption drops the stream; it is not a native cancellation frame."""
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.UNSUPPORTED,
            native_interruption=TTSCapabilitySupport.UNSUPPORTED,
            aligned_transcript=TTSCapabilitySupport.SUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.SUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.UNSUPPORTED,
        )

    @property
    def is_connected(self) -> bool:
        """The adapter session can accept input, including after a completed turn."""
        return self._state not in (
            ElevenLabsStreamState.DISCONNECTED,
            ElevenLabsStreamState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._turn_complete

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    def url(self) -> str:
        voice_id = quote(self._input.voice, safe="")
        return f"{_STREAM_URL}/{voice_id}/stream-input?{urlencode(self.query_params())}"

    def initial_message(self) -> ElevenLabsInitialize:
        settings = self.voice_settings()
        return ElevenLabsInitialize(
            xi_api_key=self._input.options.api_key,
            voice_settings=settings if settings.model_dump(exclude_none=True) else None,
        )

    async def connect(self) -> ClientConnection:
        """Publish readiness only after initialization; close failed acquisitions."""
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self._ws
            ws = await self._open_stream()
            self._state = ElevenLabsStreamState.READY
            self._turn_complete = False
            self._completion_error = None
            return ws

    async def _open_stream(self) -> ClientConnection:
        """Called under the lifecycle lock; never replay text after failure."""
        ws: ClientConnection | None = None
        try:
            ws = await connect(
                self.url(),
                open_timeout=self._retry_options.timeout_seconds,
                close_timeout=self._retry_options.timeout_seconds,
            )
            await ws.send(self.initial_message().to_wire_json())
        except asyncio.CancelledError:
            self._state = ElevenLabsStreamState.DISCONNECTED
            self._stream_available.set()
            if ws is not None:
                await self._close(ws)
            raise
        except Exception:
            error = TTSConnectionFailed("ElevenLabs connection failed.")
            self._completion_error = error
            self._state = ElevenLabsStreamState.FAILED
            self._stream_available.set()
            if ws is not None:
                await self._close(ws)
            raise error from None
        self._ws = ws
        self._stream_available.set()
        logger.info("ElevenLabs TTS connected")
        return ws

    async def disconnect(self) -> None:
        """Detach before awaiting close; late frames cannot affect a new stream."""
        async with self._lifecycle_lock:
            self._state = ElevenLabsStreamState.DISCONNECTED
            self._stream_available.set()
            ws, self._ws = self._ws, None
            if ws is not None:
                await self._close(ws)
            if self._closing_tasks:
                closing = asyncio.gather(*self._closing_tasks, return_exceptions=True)
                await asyncio.shield(closing)

    def _start_close(self, ws: ClientConnection) -> asyncio.Task[None]:
        # Native close is bounded by close_timeout. Keep ownership if this caller
        # is cancelled while the TCP/closing handshake is still completing.
        task = asyncio.create_task(ws.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closed)
        return task

    async def _close(self, ws: ClientConnection) -> None:
        task = self._start_close(ws)
        try:
            await asyncio.shield(task)
        except Exception:
            # The callback consumes/logs the failure. Do not replace an original
            # receive/send failure or cancellation with a close exception.
            pass

    def _closed(self, task: asyncio.Task[None]) -> None:
        self._closing_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("ElevenLabs close failed")

    async def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._completion_error = error
            self._state = ElevenLabsStreamState.FAILED
            self._stream_available.set()
        await self._close(ws)

    async def _send(self, message: ElevenLabsText | ElevenLabsEndInput) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionClosed("ElevenLabs TTS is not connected.")
        try:
            await ws.send(message.model_dump_json(exclude_none=True))
        except asyncio.CancelledError:
            # Sending cancellation may leave a partially emitted frame; retire it.
            await self._fail(ws, TTSConnectionFailed("ElevenLabs send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("ElevenLabs send failed.")
            await self._fail(ws, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        message = ElevenLabsText(text=text)
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is ElevenLabsStreamState.DISCONNECTED:
                raise TTSConnectionClosed("ElevenLabs TTS is not connected.")
            if self._state is ElevenLabsStreamState.DRAINING:
                raise TTSConnectionFailed("ElevenLabs previous turn is still draining.")
            if self._ws is None:
                await self._open_stream()
            self._state = ElevenLabsStreamState.STREAMING
            self._turn_complete = False
            await self._send(message)

    async def flush(self) -> None:
        """End this native stream's input; wait for its final audio before reuse."""
        async with self._lifecycle_lock:
            if self._state is ElevenLabsStreamState.STREAMING:
                self._state = ElevenLabsStreamState.DRAINING
                await self._send(ElevenLabsEndInput())

    async def keepalive(self) -> None:
        async with self._lifecycle_lock:
            if self._ws is not None and self._state in (
                ElevenLabsStreamState.READY,
                ElevenLabsStreamState.STREAMING,
            ):
                await self._send(ElevenLabsText(text=_CONTROL_TEXT))

    async def receive_audio(self) -> bytes | None:
        """Validate before state changes; retain audio even on a final frame."""
        if self._state is ElevenLabsStreamState.DISCONNECTED:
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
            audio = message.audio_bytes()
            if message.is_final is True:
                self._turn_complete = True
                self._state = ElevenLabsStreamState.READY
                self._ws = None
                self._stream_available.clear()
                self._start_close(ws)
            return audio
        except ConnectionClosed:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("ElevenLabs stream ended before completion.")
            await self._fail(ws, error)
            raise error from None
        except ElevenLabsOutputError as error:
            await self._fail(ws, error)
            raise
        except Exception:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("ElevenLabs receive failed.")
            await self._fail(ws, error)
            raise error from None
        # Cancelling recv is safe in websockets 15 and is used by the manager's
        # polling timeout. It must not cancel the connection or clear turn state.

    async def handle_interruption(self) -> None:
        """Retire current audio; the next turn opens its own configured stream."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            self._state = ElevenLabsStreamState.READY
            self._stream_available.clear()
            ws, self._ws = self._ws, None
            self._turn_complete = True
            if ws is not None:
                await self._close(ws)
