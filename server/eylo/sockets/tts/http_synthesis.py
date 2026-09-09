"""Ordered bearer-authenticated HTTP speech; vendors own request and audio contracts."""

import asyncio
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator, Coroutine, Iterator
from enum import StrEnum
from http import HTTPStatus
from typing import ClassVar, Self

import aiohttp
from pydantic import BaseModel

from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSConfig

logger = logging.getLogger(__name__)

_QUEUE_SIZE = 500
_RECEIVE_POLL_SECONDS = 0.1
_VERIFY_TIMEOUT_SECONDS = 10
_SYNTHESIS_TIMEOUT_SECONDS = 30
_VERIFICATION_TEXT = "."


class HttpSpeechTurnState(StrEnum):
    IDLE = "idle"
    STREAMING = "streaming"
    DRAINING = "draining"
    COMPLETE = "complete"
    FAILED = "failed"


def split_speech_text(text: str, maximum_characters: int) -> Iterator[str]:
    """Partition without truncation; keep whitespace and order at the native limit."""
    if maximum_characters < 1:
        raise ValueError("Speech text limit must be positive.")
    while len(text) > maximum_characters:
        boundary = text.rfind(" ", 0, maximum_characters)
        end = boundary + 1 if boundary >= 0 else maximum_characters
        yield text[:end]
        text = text[end:]
    if text:
        yield text


class OrderedHttpSpeechAdapter[Request: BaseModel](TTSVendorAdapter):
    """Own FIFO requests, bounded audio, turn failure and cancellation cleanup.

    Only bearer-authenticated JSON speech endpoints share this implementation.
    A vendor supplies its validated request and raw-audio decoder. The decoder
    owns no HTTP resource; this class closes the enclosing response on every exit.
    """

    text_limit: ClassVar[int]

    def __init__(self, config: TTSConfig, *, endpoint: str, api_key: str) -> None:
        super().__init__(config)
        self._endpoint = endpoint
        self._api_key = api_key
        self._text_queue: asyncio.Queue[tuple[int, Request]] = asyncio.Queue(
            maxsize=_QUEUE_SIZE
        )
        self._response_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._session: aiohttp.ClientSession | None = None
        self._worker: asyncio.Task[None] | None = None
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._lifecycle_lock = asyncio.Lock()
        self._connected = False
        self._synthesizing = False
        self._generation = 0
        self._turn_state = HttpSpeechTurnState.IDLE
        self._completion_error: TTSConnectionFailed | None = None

    async def connect(self) -> Self:
        async with self._lifecycle_lock:
            await self._wait_cleanup()
            if self._connected:
                return self
            session = aiohttp.ClientSession()
            try:
                await self._request(
                    session,
                    self.speech_request(_VERIFICATION_TEXT),
                    generation=None,
                    timeout=_VERIFY_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                await self._close_session(session)
                raise
            except Exception:
                await self._close_session(session)
                raise
            self._session = session
            self._connected = True
            self._completion_error = None
            self._turn_state = HttpSpeechTurnState.IDLE
            self._worker = asyncio.create_task(self._synthesis_loop())
            return self

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            await self._wait_cleanup()
            self._connected = False
            session, self._session = self._session, None
            self._generation += 1
            # Cleanup remains owned if the caller is cancelled again during teardown.
            task = self._own_cleanup(self._dispose(session))
            await asyncio.shield(task)

    async def _dispose(self, session: aiohttp.ClientSession | None) -> None:
        try:
            await self._stop_worker()
        finally:
            self._drain_queue(self._text_queue)
            self._drain_queue(self._response_queue)
            self._turn_state = HttpSpeechTurnState.COMPLETE
            if session is not None:
                await session.close()

    def _own_cleanup(
        self, operation: Coroutine[object, object, None]
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(operation)
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_done)
        return task

    async def _close_session(self, session: aiohttp.ClientSession) -> None:
        task = self._own_cleanup(session.close())
        await asyncio.shield(task)

    async def _wait_cleanup(self) -> None:
        if self._cleanup_tasks:
            pending = asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
            await asyncio.shield(pending)

    def _cleanup_done(self, task: asyncio.Task[None]) -> None:
        self._cleanup_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning(f"{self.provider} TTS resource cleanup failed.")

    async def send_text(self, text: str) -> None:
        await self._wait_cleanup()
        if not self._connected or self._session is None:
            raise TTSConnectionClosed(f"{self.provider} TTS is not connected.")
        if self._completion_error is not None:
            raise self._completion_error
        if not text or not text.strip():
            return
        generation = self._generation
        self._turn_state = HttpSpeechTurnState.STREAMING
        for fragment in split_speech_text(text, self.text_limit):
            await self._text_queue.put((generation, self.speech_request(fragment)))
            if generation != self._generation or not self._connected:
                raise TTSConnectionClosed(f"{self.provider} TTS input was interrupted.")

    async def _synthesis_loop(self) -> None:
        while True:
            generation, request = await self._text_queue.get()
            try:
                if generation != self._generation or self._completion_error is not None:
                    continue
                session = self._session
                if session is None:
                    raise TTSConnectionClosed(f"{self.provider} TTS is not connected.")
                self._synthesizing = True
                await self._request(
                    session,
                    request,
                    generation=generation,
                    timeout=_SYNTHESIS_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._completion_error = (
                    error
                    if isinstance(error, TTSConnectionFailed)
                    else TTSConnectionFailed(f"{self.provider} TTS synthesis failed.")
                )
                self._turn_state = HttpSpeechTurnState.FAILED
                logger.warning(f"{self.provider} TTS synthesis failed.")
            finally:
                self._synthesizing = False
                self._text_queue.task_done()

    async def _request(
        self,
        session: aiohttp.ClientSession,
        request: Request,
        *,
        generation: int | None,
        timeout: float,
    ) -> None:
        try:
            async with session.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=request.model_dump(mode="json"),
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=False,
            ) as response:
                if response.status != HTTPStatus.OK:
                    # Never load arbitrary error bodies or copy upstream text/secrets.
                    raise TTSConnectionFailed(
                        f"{self.provider} TTS request failed with HTTP {response.status}."
                    )
                async for chunk in self.decode_audio(response.content):
                    if generation is None:
                        continue
                    if generation != self._generation or not self._connected:
                        return
                    await self._response_queue.put(chunk)
        except TTSConnectionFailed:
            raise
        except Exception:
            raise TTSConnectionFailed(f"{self.provider} TTS request failed.") from None

    async def receive_audio(self) -> bytes | None:
        if self._completion_error is not None:
            raise self._completion_error
        try:
            chunk = await asyncio.wait_for(
                self._response_queue.get(), timeout=_RECEIVE_POLL_SECONDS
            )
        except asyncio.TimeoutError:
            if self._completion_error is not None:
                raise self._completion_error
            return None
        self._response_queue.task_done()
        return chunk

    async def flush(self) -> None:
        if self._completion_error is not None:
            raise self._completion_error
        self._turn_state = HttpSpeechTurnState.DRAINING

    @property
    def is_turn_complete(self) -> bool:
        if (
            self._turn_state is HttpSpeechTurnState.DRAINING
            and not self._synthesizing
            and self._text_queue.empty()
            and self._response_queue.empty()
        ):
            self._turn_state = HttpSpeechTurnState.COMPLETE
        return self._turn_state is HttpSpeechTurnState.COMPLETE

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    async def _stop_worker(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def handle_interruption(self) -> None:
        async with self._lifecycle_lock:
            await self._wait_cleanup()
            self._generation += 1
            task = self._own_cleanup(self._interrupt())
            await asyncio.shield(task)

    async def _interrupt(self) -> None:
        await self._stop_worker()
        self._drain_queue(self._text_queue)
        self._drain_queue(self._response_queue)
        self._completion_error = None
        self._turn_state = HttpSpeechTurnState.COMPLETE
        if self._connected:
            self._worker = asyncio.create_task(self._synthesis_loop())

    @staticmethod
    def _drain_queue[T](queue: asyncio.Queue[T]) -> None:
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                return

    @abstractmethod
    def speech_request(self, text: str) -> Request:
        """Validate one bounded native request; credentials are not part of its JSON."""

    @abstractmethod
    def decode_audio(self, stream: aiohttp.StreamReader) -> AsyncIterator[bytes]:
        """Yield validated raw PCM; the surrounding HTTP scope owns stream closure."""

    async def keepalive(self) -> None:
        """HTTP synthesis has no protocol keepalive."""

    @property
    def is_connected(self) -> bool:
        return self._connected
