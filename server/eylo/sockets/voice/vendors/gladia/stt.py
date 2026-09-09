"""Own one Gladia Live v2 session, buffered audio, final output and socket cleanup."""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import AsyncIterator
from enum import StrEnum

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from eylo.sockets.stt.exceptions import (
    STTConfigurationError,
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.voice.vendors.gladia.session import (
    create_gladia_session,
    gladia_http_failure_kind,
)
from eylo.sockets.voice.vendors.gladia.wire import (
    PCM_SAMPLE_BYTES,
    GladiaConfig,
    GladiaEvent,
    GladiaLiveSession,
    GladiaMessageType,
    GladiaStopRecording,
    GladiaTranscript,
    parse_gladia_event,
)

_FINAL_RESULT_TIMEOUT_SECONDS = 2.0
_SOCKET_CLOSE_TIMEOUT_SECONDS = 2.0
_CLEANUP_TIMEOUT_SECONDS = 5.0
_NATIVE_QUEUE_CAPACITY = 16


class _AttemptState(StrEnum):
    NEW = "new"
    CREATING = "creating"
    CREATED = "created"
    READY = "ready"
    ENDED = "ended"
    FAILED = "failed"


class _PinnedConnect(connect):
    """Keep the token on the validated URL; verified against websockets 15.0.1."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


def _startup_failure_kind(error: Exception) -> STTConnectionFailureKind:
    if isinstance(error, InvalidStatus):
        return gladia_http_failure_kind(error.response.status_code)
    if isinstance(error, ssl.SSLError):
        return STTConnectionFailureKind.TLS
    if isinstance(error, TimeoutError):
        return STTConnectionFailureKind.TIMEOUT
    if isinstance(error, OSError):
        return STTConnectionFailureKind.NETWORK
    return STTConnectionFailureKind.PROTOCOL


class GladiaSTTStream(AsyncIterator[GladiaTranscript]):
    """The adapter owns the reader; this attempt owns POST uncertainty and disposal."""

    def __init__(self, *, config: GladiaConfig) -> None:
        self._config = config
        self._state = _AttemptState.NEW
        self._session: GladiaLiveSession | None = None
        self._ws: ClientConnection | None = None
        self._buffer = bytearray()
        self._send_lock = asyncio.Lock()
        self._finished = asyncio.Event()
        self._physical_close_started = asyncio.Event()
        self._stop_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def can_replace(self) -> bool:
        """Only an acknowledged session end establishes a clean new-session boundary."""
        return self._state is _AttemptState.ENDED

    async def start(self) -> None:
        if self._state is not _AttemptState.NEW or self._close_task is not None:
            raise STTConnectionRetryUnsafe(
                "Gladia session creation cannot be repeated for this attempt."
            )
        self._state = _AttemptState.CREATING
        self._session = await create_gladia_session(
            self._config.live_request(), api_key=self._config.api_key
        )
        self._state = _AttemptState.CREATED
        try:
            self._ws = await _PinnedConnect(
                self._session.url.get_secret_value(),
                close_timeout=_SOCKET_CLOSE_TIMEOUT_SECONDS,
                max_queue=_NATIVE_QUEUE_CAPACITY,
            )
            event = await self._receive_native()
        except (ConnectionClosed, InvalidHandshake, OSError, TimeoutError) as error:
            raise STTConnectionRetryUnsafe(
                "Gladia session could not start.",
                kind=_startup_failure_kind(error),
            ) from None
        if event.type is not GladiaMessageType.START_SESSION:
            raise STTConnectionRetryUnsafe(
                "Gladia did not acknowledge session startup.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
        self._state = _AttemptState.READY

    async def _receive_native(self) -> GladiaEvent:
        ws, session = self._ws, self._session
        if ws is None or session is None:
            raise STTConnectionClosed("Gladia session is unavailable.")
        try:
            event = parse_gladia_event(await ws.recv())
        except ValidationError:
            raise STTConnectionRetryUnsafe(
                "Gladia returned an invalid or failed event.",
                kind=STTConnectionFailureKind.PROTOCOL,
            ) from None
        if event.session_id != session.id:
            raise STTConnectionRetryUnsafe(
                "Gladia event belongs to a different session.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
        return event

    async def send_audio(self, audio: bytes) -> None:
        async with self._send_lock:
            if (
                self._state is not _AttemptState.READY
                or self._close_task is not None
                or self._finished.is_set()
            ):
                raise STTConnectionClosed("Gladia STT is not accepting audio.")
            if len(audio) % PCM_SAMPLE_BYTES:
                raise STTConfigurationError(
                    "Gladia audio must contain whole PCM16 samples."
                )
            self._buffer.extend(audio)
            if len(self._buffer) >= self._config.buffer_threshold:
                await self._send_buffer()

    async def _send_buffer(self) -> None:
        ws = self._ws
        if ws is None:
            raise STTConnectionClosed("Gladia socket is unavailable.")
        if not self._buffer:
            return
        try:
            await ws.send(bytes(self._buffer))
        except BaseException as error:
            # Cancellation may arrive after the socket accepted these bytes.
            # A failed send must never be replayed by shutdown's tail flush.
            self._state = _AttemptState.FAILED
            self._finished.set()
            if isinstance(error, ConnectionClosed):
                raise STTConnectionRetryUnsafe(
                    "Gladia audio transport closed; the write outcome is unknown.",
                    kind=STTConnectionFailureKind.PROTOCOL,
                ) from None
            raise
        self._buffer.clear()

    async def __anext__(self) -> GladiaTranscript:
        while not self._finished.is_set():
            try:
                event = await self._receive_native()
            except Exception as error:
                self._state = _AttemptState.FAILED
                self._finished.set()
                if isinstance(error, ConnectionClosed):
                    if self._physical_close_started.is_set():
                        # Forced local close wakes recv; the close owner retains
                        # the original finalization failure instead of replacing it.
                        raise StopAsyncIteration from None
                    raise STTConnectionRetryUnsafe(
                        "Gladia closed without a complete session end.",
                        kind=STTConnectionFailureKind.PROTOCOL,
                    ) from None
                raise
            if isinstance(event, GladiaTranscript):
                return event
            if event.type is GladiaMessageType.END_SESSION:
                self._finished.set()
                if self._stop_task is None:
                    self._state = _AttemptState.FAILED
                    raise STTConnectionRetryUnsafe(
                        "Gladia ended the session before recording was stopped.",
                        kind=STTConnectionFailureKind.PROTOCOL,
                    )
                self._state = _AttemptState.ENDED
                break
            if event.type is GladiaMessageType.START_SESSION:
                self._state = _AttemptState.FAILED
                self._finished.set()
                raise STTConnectionRetryUnsafe(
                    "Gladia repeated its session acknowledgement.",
                    kind=STTConnectionFailureKind.PROTOCOL,
                )
        raise StopAsyncIteration

    async def _stop_recording(self, ws: ClientConnection) -> None:
        async with self._send_lock:
            await self._send_buffer()
            await ws.send(GladiaStopRecording().model_dump_json())

    async def aclose(self) -> None:
        """A cancelled caller cannot abandon the cleanup task or replace its attempt."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(_observe_task)
        try:
            async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                await asyncio.shield(self._close_task)
        except TimeoutError as error:
            raise STTConnectionCleanupFailed(
                "Gladia socket cleanup did not complete."
            ) from error

    async def _close(self) -> None:
        ws = self._ws
        if ws is None:
            return
        finalization_error: Exception | None = None
        try:
            if self._state is _AttemptState.READY and not self._finished.is_set():
                try:
                    async with asyncio.timeout(_FINAL_RESULT_TIMEOUT_SECONDS):
                        self._stop_task = asyncio.create_task(self._stop_recording(ws))
                        self._stop_task.add_done_callback(_observe_task)
                        await asyncio.shield(self._stop_task)
                        await self._finished.wait()
                except Exception as error:
                    finalization_error = error
        finally:
            try:
                self._physical_close_started.set()
                await ws.close()
                await ws.wait_closed()
            except Exception as error:
                raise STTConnectionCleanupFailed(
                    "Gladia socket cleanup failed."
                ) from error
            finally:
                stop = self._stop_task
                if stop is not None:
                    if not stop.done():
                        stop.cancel()
                    await asyncio.gather(stop, return_exceptions=True)
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Gladia closed before final output completed."
            ) from finalization_error


class GladiaSTT:
    """Construct one resource owner from frozen resolved settings."""

    def __init__(self, config: GladiaConfig) -> None:
        self.config = GladiaConfig.model_validate(config)

    def stream(self) -> GladiaSTTStream:
        return GladiaSTTStream(config=self.config)


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
