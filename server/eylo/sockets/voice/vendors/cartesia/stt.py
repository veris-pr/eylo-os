"""Own Cartesia STT connection, PCM sending and validated response delivery."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import NoReturn

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from eylo.sockets.voice.audio import AudioByteStream
from eylo.sockets.voice.vendors.cartesia.stt_wire import (
    CartesiaSTTCommand,
    CartesiaSTTDone,
    CartesiaSTTError,
    CartesiaSTTEvent,
    CartesiaSTTQuery,
    parse_cartesia_stt_event,
)

DEFAULT_BASE_URL = "https://api.cartesia.ai"
_CONNECT_TIMEOUT_SECONDS = 10.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_HEARTBEAT_SECONDS = 30.0
_AUDIO_CHUNK_SECONDS = 0.05
_OUTPUT_QUEUE_CAPACITY = 1000


class STTOptions(BaseModel):
    """Immutable native material; the API key is never serialized or represented."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", hide_input_in_errors=True, validate_default=True
    )

    query: CartesiaSTTQuery
    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)
    base_url: HttpUrl = HttpUrl(DEFAULT_BASE_URL)


class CartesiaSTTState(StrEnum):
    """Lifecycle of one connection; reconnecting creates a new stream."""

    NEW = "new"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class CartesiaSTTStreamError(RuntimeError):
    """A closed or failed native stream cannot accept more input."""


class CartesiaSTT:
    """Build isolated streams from configured material; own only acquired HTTP sessions."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        language: str | None = None,
        encoding: str = "pcm_s16le",
        sample_rate: int = 16000,
        base_url: str = DEFAULT_BASE_URL,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._opts = STTOptions(
            query=CartesiaSTTQuery(
                model=model,
                language=language,
                encoding=encoding,
                sample_rate=sample_rate,
            ),
            api_key=api_key,
            base_url=base_url,
        )
        self._session = http_session
        self._owns_session = http_session is None

    @property
    def model(self) -> str:
        return self._opts.query.model

    @property
    def provider(self) -> str:
        return "Cartesia"

    @property
    def sample_rate(self) -> int:
        return self._opts.query.sample_rate

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    def stream(self) -> CartesiaSTTStream:
        """Create an unopened stream; its connect method proves WebSocket acquisition."""
        return CartesiaSTTStream(opts=self._opts, http_session=self._ensure_session())

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            session, self._session = self._session, None
            await session.close()


class CartesiaSTTStream:
    """Serialize binary/control writes; one reader owns responses and terminal failure."""

    def __init__(
        self, *, opts: STTOptions, http_session: aiohttp.ClientSession
    ) -> None:
        self._opts = opts
        self._session = http_session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._state = CartesiaSTTState.NEW
        self._failure: Exception | None = None
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._output_queue: asyncio.Queue[CartesiaSTTEvent | None] = asyncio.Queue(
            maxsize=_OUTPUT_QUEUE_CAPACITY
        )
        self._output_closed = False
        self._audio = AudioByteStream(
            sample_rate=opts.query.sample_rate,
            num_channels=1,
            samples_per_channel=max(
                1, round(opts.query.sample_rate * _AUDIO_CHUNK_SECONDS)
            ),
        )

    @property
    def is_connected(self) -> bool:
        return self._state is CartesiaSTTState.OPEN and self._failure is None

    async def connect(self) -> None:
        """Report readiness only after authenticated WebSocket upgrade, not task creation."""
        async with self._lifecycle_lock:
            if self.is_connected:
                return
            if self._state is not CartesiaSTTState.NEW:
                raise CartesiaSTTStreamError("Cartesia stream cannot be reopened.")
            base = str(self._opts.base_url).rstrip("/")
            ws_base = base.replace("https://", "wss://", 1).replace(
                "http://", "ws://", 1
            )
            url = f"{ws_base}/stt/websocket?{self._opts.query.query_string()}"
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                    self._ws = await self._session.ws_connect(
                        url,
                        headers={"X-API-Key": self._opts.api_key.get_secret_value()},
                        heartbeat=_HEARTBEAT_SECONDS,
                    )
            except BaseException:
                self._state = CartesiaSTTState.CLOSED
                self._finish_output()
                raise
            self._state = CartesiaSTTState.OPEN
            self._task = asyncio.create_task(self._read(self._ws))

    def _require_open(self) -> aiohttp.ClientWebSocketResponse:
        if self._failure is not None:
            raise self._failure
        if not self.is_connected or self._ws is None:
            raise CartesiaSTTStreamError("Cartesia stream is not open.")
        return self._ws

    async def push_audio(self, audio_data: bytes) -> None:
        """Await socket acceptance; no detached, unbounded audio-input queue."""
        async with self._send_lock:
            ws = self._require_open()
            try:
                for chunk in self._audio.write(audio_data):
                    await ws.send_bytes(chunk.data)
            except BaseException:
                self._failure = CartesiaSTTStreamError("Cartesia audio send failed.")
                raise

    async def flush(self) -> None:
        """Send buffered PCM before finalize; keep the sender usable for the next turn."""
        async with self._send_lock:
            ws = self._require_open()
            try:
                await self._flush_audio(ws)
                await ws.send_str(CartesiaSTTCommand.FINALIZE.value)
            except BaseException:
                self._failure = CartesiaSTTStreamError("Cartesia finalize failed.")
                raise

    async def _flush_audio(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        for chunk in self._audio.flush():
            await ws.send_bytes(chunk.data)

    def __aiter__(self) -> CartesiaSTTStream:
        return self

    async def __anext__(self) -> CartesiaSTTEvent:
        if self._output_closed and self._output_queue.empty():
            self._raise_terminal()
        event = await self._output_queue.get()
        self._output_queue.task_done()
        if event is not None:
            return event
        if self._failure is not None:
            raise self._failure
        raise StopAsyncIteration

    def _raise_terminal(self) -> NoReturn:
        if self._failure is not None:
            raise self._failure
        raise StopAsyncIteration

    def _finish_output(self) -> None:
        if not self._output_closed:
            self._output_closed = True
            try:
                self._output_queue.put_nowait(None)
            except asyncio.QueueFull:
                # Existing output remains ordered; the next empty read observes closure.
                pass

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            while True:
                message = await ws.receive()
                if message.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.ERROR,
                }:
                    raise CartesiaSTTStreamError(
                        "Cartesia ended without a done acknowledgement."
                    )
                if message.type is not aiohttp.WSMsgType.TEXT:
                    continue
                event = parse_cartesia_stt_event(message.data)
                if event is None:
                    continue
                await self._output_queue.put(event)
                if isinstance(event, (CartesiaSTTDone, CartesiaSTTError)):
                    return
        except Exception as error:
            self._failure = error
        finally:
            self._state = CartesiaSTTState.CLOSED
            try:
                await self._close_socket()
            finally:
                self._finish_output()

    async def _close_socket(self) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await self._ws.close()
            except Exception as error:
                if self._failure is None:
                    self._failure = error

    async def aclose(self) -> None:
        """Flush/close with bounded draining, then cancel/join and wake every reader."""
        async with self._lifecycle_lock:
            try:
                if self.is_connected:
                    self._state = CartesiaSTTState.CLOSING
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                            async with self._send_lock:
                                if self._ws is not None:
                                    await self._flush_audio(self._ws)
                                    await self._ws.send_str(
                                        CartesiaSTTCommand.CLOSE.value
                                    )
                            if self._task is not None:
                                await asyncio.shield(self._task)
                    except TimeoutError:
                        if self._failure is None:
                            self._failure = CartesiaSTTStreamError(
                                "Cartesia close acknowledgement timed out."
                            )
                    except Exception as error:
                        if self._failure is None:
                            self._failure = error
            finally:
                if self._task is not None:
                    if not self._task.done():
                        self._task.cancel()
                    await asyncio.gather(self._task, return_exceptions=True)
                await self._close_socket()
                self._state = CartesiaSTTState.CLOSED
                self._finish_output()
