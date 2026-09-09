"""Own Deepgram Listen v1 acquisition, bounded output, PCM writes and terminal drain."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import NoReturn
from uuid import uuid4

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from eylo.sockets.voice.audio import AudioByteStream, AudioFrame
from eylo.sockets.voice.vendors.deepgram.stt_wire import (
    DeepgramControl,
    DeepgramEvent,
    DeepgramListenQuery,
    DeepgramMessage,
    DeepgramMetadata,
    DeepgramResults,
    parse_deepgram_event,
)

DEFAULT_BASE_URL = "wss://api.deepgram.com/v1/listen"
SAMPLE_RATE = 16000
_CONNECT_TIMEOUT_SECONDS = 10.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_KEEPALIVE_SECONDS = 4.0
_AUDIO_CHUNK_SECONDS = 0.05
_OUTPUT_QUEUE_CAPACITY = 1000
_PCM_BYTES_PER_SAMPLE = 2


class STTOptions(BaseModel):
    """Immutable native material; credentials never enter repr, query or serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    query: DeepgramListenQuery
    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)


class DeepgramStreamState(StrEnum):
    """A failed stream is terminal; the STT factory owns bounded recovery."""

    NEW = "new"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class DeepgramStreamError(RuntimeError):
    """Native recognition or transport failed without an implicit reconnect."""


class DeepgramSTT:
    """Create isolated streams; close only the HTTP session acquired by this client."""

    def __init__(
        self,
        *,
        model: str,
        language: str,
        api_key: str,
        sample_rate: int = SAMPLE_RATE,
        interim_results: bool = True,
        punctuate: bool = True,
        smart_format: bool = False,
        vad_events: bool = True,
        endpointing: int | bool | None = None,
        utterance_end_ms: int | None = None,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._opts = STTOptions(
            query=DeepgramListenQuery(
                model=model,
                language=language,
                sample_rate=sample_rate,
                interim_results=interim_results,
                punctuate=punctuate,
                smart_format=smart_format,
                vad_events=vad_events,
                endpointing=endpointing,
                utterance_end_ms=utterance_end_ms,
            ),
            api_key=api_key,
        )
        self._session = http_session
        self._owns_session = http_session is None

    @property
    def model(self) -> str:
        return self._opts.query.model

    @property
    def provider(self) -> str:
        return "Deepgram"

    @property
    def sample_rate(self) -> int:
        return self._opts.query.sample_rate

    def stream(self) -> DeepgramSTTStream:
        """Create an unopened stream; connect awaits the actual WebSocket upgrade."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return DeepgramSTTStream(opts=self._opts, http_session=self._session)

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            session, self._session = self._session, None
            await session.close()


class DeepgramSTTStream:
    """One task group owns reads/KeepAlive; serialized writes preserve PCM/control order."""

    def __init__(
        self, *, opts: STTOptions, http_session: aiohttp.ClientSession
    ) -> None:
        self._opts = opts
        self._session = http_session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._state = DeepgramStreamState.NEW
        self._failure: Exception | None = None
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._output_queue: asyncio.Queue[DeepgramEvent | None] = asyncio.Queue(
            maxsize=_OUTPUT_QUEUE_CAPACITY
        )
        self._output_closed = False
        self.request_id: str | None = None
        # Local correlation remains stable even before native request metadata arrives.
        self.session_id = str(uuid4())
        self._audio = AudioByteStream(
            sample_rate=opts.query.sample_rate,
            num_channels=1,
            samples_per_channel=max(
                1, round(opts.query.sample_rate * _AUDIO_CHUNK_SECONDS)
            ),
        )

    @property
    def is_connected(self) -> bool:
        return self._state is DeepgramStreamState.OPEN and self._failure is None

    async def connect(self) -> None:
        async with self._lifecycle_lock:
            if self.is_connected:
                return
            if self._state is not DeepgramStreamState.NEW:
                raise DeepgramStreamError("Deepgram stream cannot be reopened.")
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                    self._ws = await self._session.ws_connect(
                        DEFAULT_BASE_URL,
                        params=self._opts.query.query_parameters(),
                        headers={
                            "Authorization": f"Token {self._opts.api_key.get_secret_value()}"
                        },
                    )
            except BaseException:
                self._state = DeepgramStreamState.CLOSED
                await self._close_socket()
                self._finish_output()
                raise
            self._state = DeepgramStreamState.OPEN
            self._task = asyncio.create_task(self._run())

    def _require_open(self) -> aiohttp.ClientWebSocketResponse:
        if self._failure is not None:
            raise self._failure
        if not self.is_connected or self._ws is None:
            raise DeepgramStreamError("Deepgram stream is not open.")
        return self._ws

    async def push_audio(self, frame: AudioFrame) -> None:
        """Reject mismatched PCM; socket writes provide backpressure without an input queue."""
        if (
            frame.sample_rate != self._opts.query.sample_rate
            or frame.num_channels != 1
            or len(frame.data) != frame.samples_per_channel * _PCM_BYTES_PER_SAMPLE
        ):
            raise ValueError("Deepgram requires matching mono 16-bit PCM frames.")
        async with self._send_lock:
            ws = self._require_open()
            try:
                for chunk in self._audio.write(frame.data):
                    await ws.send_bytes(chunk.data)
            except BaseException:
                self._failure = DeepgramStreamError("Deepgram audio send failed.")
                raise

    async def _flush_audio(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        for chunk in self._audio.flush():
            await ws.send_bytes(chunk.data)

    async def flush(self) -> None:
        """Finalize buffered audio without closing; a from_finalize reply is not guaranteed."""
        async with self._send_lock:
            ws = self._require_open()
            try:
                await self._flush_audio(ws)
                await ws.send_str(
                    DeepgramControl(type=DeepgramMessage.FINALIZE).model_dump_json()
                )
            except BaseException:
                self._failure = DeepgramStreamError("Deepgram finalization failed.")
                raise

    async def _keepalive(self) -> None:
        """Listen v1 needs JSON KeepAlive frames, not just WebSocket ping/pong."""
        while True:
            await asyncio.sleep(_KEEPALIVE_SECONDS)
            async with self._send_lock:
                if not self.is_connected:
                    return
                await self._require_open().send_str(
                    DeepgramControl(type=DeepgramMessage.KEEP_ALIVE).model_dump_json()
                )

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while True:
            message = await ws.receive()
            if message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            }:
                raise DeepgramStreamError(
                    "Deepgram closed without terminal recognition metadata."
                )
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            event = parse_deepgram_event(message.data)
            if isinstance(event, DeepgramMetadata):
                self.request_id = event.request_id
            elif isinstance(event, DeepgramResults) and event.metadata is not None:
                self.request_id = event.metadata.request_id or self.request_id
            await self._output_queue.put(event)
            if isinstance(event, DeepgramMetadata):
                return

    async def _run(self) -> None:
        try:
            if self._ws is None:
                raise DeepgramStreamError("Deepgram socket was not acquired.")
            async with asyncio.TaskGroup() as group:
                keepalive = group.create_task(self._keepalive())
                try:
                    await self._read(self._ws)
                finally:
                    keepalive.cancel()
        except Exception as error:
            self._failure = error
        finally:
            self._state = DeepgramStreamState.CLOSED
            try:
                await self._close_socket()
            finally:
                self._finish_output()

    def __aiter__(self) -> DeepgramSTTStream:
        return self

    async def __anext__(self) -> DeepgramEvent:
        if self._output_closed and self._output_queue.empty():
            self._raise_terminal()
        event = await self._output_queue.get()
        self._output_queue.task_done()
        if event is not None:
            return event
        self._raise_terminal()

    def _raise_terminal(self) -> NoReturn:
        if self._failure is not None:
            raise self._failure
        raise StopAsyncIteration

    def _finish_output(self) -> None:
        if self._output_closed:
            return
        self._output_closed = True
        try:
            self._output_queue.put_nowait(None)
        except asyncio.QueueFull:
            # Accepted output stays intact; empty reads observe terminal state directly.
            pass

    async def _close_socket(self) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await self._ws.close()
            except Exception as error:
                self._failure = self._failure or error

    async def aclose(self) -> None:
        """Send CloseStream before closing; bounded final-result drain, then join all tasks."""
        async with self._lifecycle_lock:
            try:
                if self.is_connected:
                    self._state = DeepgramStreamState.CLOSING
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                            async with self._send_lock:
                                if self._ws is not None:
                                    await self._flush_audio(self._ws)
                                    await self._ws.send_str(
                                        DeepgramControl(
                                            type=DeepgramMessage.CLOSE_STREAM
                                        ).model_dump_json()
                                    )
                            if self._task is not None:
                                await asyncio.shield(self._task)
                    except TimeoutError:
                        self._failure = self._failure or DeepgramStreamError(
                            "Deepgram terminal metadata timed out."
                        )
                    except Exception as error:
                        self._failure = self._failure or error
            finally:
                if self._task is not None:
                    if not self._task.done():
                        self._task.cancel()
                    await asyncio.gather(self._task, return_exceptions=True)
                try:
                    await self._close_socket()
                finally:
                    self._state = DeepgramStreamState.CLOSED
                    self._finish_output()
