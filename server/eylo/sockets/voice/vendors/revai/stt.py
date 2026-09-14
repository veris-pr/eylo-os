"""Own one Rev AI WebSocket attempt from connected acknowledgement through EOS."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import websockets
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode

from eylo.sockets.stt.exceptions import (
    STTConfigurationError,
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.voice.vendors.revai.wire import (
    RevAICloseCode,
    RevAIConfig,
    RevAIConnected,
    RevAIControl,
    RevAIFinal,
    RevAIPartial,
    parse_revai_event,
)

_PCM_SAMPLE_BYTES = 2
_FINAL_RESULT_TIMEOUT_SECONDS = 2.0
_SOCKET_CLOSE_TIMEOUT_SECONDS = 2.0
_CLEANUP_TIMEOUT_SECONDS = 5.0
_NATIVE_QUEUE_CAPACITY = 16
_CLOSE_FAILURES: dict[int, STTConnectionFailureKind] = {
    RevAICloseCode.UNAUTHORIZED: STTConnectionFailureKind.AUTHENTICATION,
    RevAICloseCode.BAD_REQUEST: STTConnectionFailureKind.REQUEST_REJECTED,
    RevAICloseCode.INSUFFICIENT_CREDITS: STTConnectionFailureKind.QUOTA_EXCEEDED,
    RevAICloseCode.SERVER_SHUTTING_DOWN: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    RevAICloseCode.NO_INSTANCE_AVAILABLE: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    RevAICloseCode.TOO_MANY_REQUESTS: STTConnectionFailureKind.RATE_LIMITED,
}


def revai_connection_error(error: ConnectionClosed) -> STTConnectionRetryUnsafe:
    """Close codes carry meaning; vendor reason text is never a public failure message."""
    code = error.rcvd.code if error.rcvd is not None else CloseCode.ABNORMAL_CLOSURE
    return STTConnectionRetryUnsafe(
        "Rev AI STT stream closed.",
        kind=_CLOSE_FAILURES.get(code, STTConnectionFailureKind.PROTOCOL),
    )


class RevAISTTStream(AsyncIterator[RevAIPartial | RevAIFinal]):
    """The adapter owns the reader; this owner closes the socket without discarding it."""

    def __init__(self, *, config: RevAIConfig) -> None:
        self._config = config
        self._ws: ClientConnection | None = None
        self.connection_id: str | None = None
        self._finished = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._eos_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """The factory bounds handshake/acknowledgement and disposes failed attempts."""
        if self._close_task is not None:
            raise STTConnectionClosed("Rev AI STT stream is closing.")
        if self._ws is not None:
            raise STTConnectionClosed("Rev AI STT attempt has already started.")
        self._ws = await websockets.connect(
            self._config.websocket_url(),
            close_timeout=_SOCKET_CLOSE_TIMEOUT_SECONDS,
            max_queue=_NATIVE_QUEUE_CAPACITY,
        )
        try:
            event = parse_revai_event(await self._ws.recv())
        except ConnectionClosed as error:
            self._finished.set()
            raise revai_connection_error(error) from error
        except ValidationError:
            raise STTConnectionRetryUnsafe(
                "Rev AI STT returned an invalid acknowledgement.",
                kind=STTConnectionFailureKind.PROTOCOL,
            ) from None
        if not isinstance(event, RevAIConnected):
            raise STTConnectionRetryUnsafe(
                "Rev AI STT did not acknowledge the connection.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
        self.connection_id = event.id

    async def send_audio(self, audio: bytes) -> None:
        """Await transport backpressure; only whole PCM16 samples precede EOS."""
        async with self._send_lock:
            ws = self._ws
            if (
                ws is None
                or self.connection_id is None
                or self._close_task is not None
                or self._finished.is_set()
            ):
                raise STTConnectionClosed("Rev AI STT is not accepting audio.")
            if len(audio) % _PCM_SAMPLE_BYTES:
                raise STTConfigurationError(
                    "Rev AI audio must contain whole PCM16 samples."
                )
            if not audio:
                return
            try:
                await ws.send(audio)
            except ConnectionClosed as error:
                raise revai_connection_error(error) from error

    async def __anext__(self) -> RevAIPartial | RevAIFinal:
        ws = self._ws
        if ws is None or self._finished.is_set():
            raise StopAsyncIteration
        try:
            event = parse_revai_event(await ws.recv())
        except ConnectionClosed as error:
            self._finished.set()
            if (
                self._eos_task is not None
                and error.rcvd is not None
                and error.rcvd.code == CloseCode.NORMAL_CLOSURE
            ):
                raise StopAsyncIteration from None
            raise revai_connection_error(error) from error
        except ValidationError:
            self._finished.set()
            raise STTConnectionRetryUnsafe(
                "Rev AI STT returned an invalid hypothesis.",
                kind=STTConnectionFailureKind.PROTOCOL,
            ) from None
        if isinstance(event, RevAIConnected):
            self._finished.set()
            raise STTConnectionRetryUnsafe(
                "Rev AI STT repeated its connection acknowledgement.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
        return event

    async def _send_eos(self, ws: ClientConnection) -> None:
        async with self._send_lock:
            await ws.send(RevAIControl.END_OF_STREAM.value)

    async def aclose(self) -> None:
        """Retain cleanup across caller cancellation; report incomplete final output."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(_observe_task)
        try:
            async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                await asyncio.shield(self._close_task)
        except TimeoutError as error:
            raise STTConnectionCleanupFailed(
                "Rev AI STT cleanup did not complete."
            ) from error

    async def _close(self) -> None:
        ws = self._ws
        if ws is None:
            return
        finalization_error: Exception | None = None
        try:
            if self.connection_id is not None and not self._finished.is_set():
                try:
                    async with asyncio.timeout(_FINAL_RESULT_TIMEOUT_SECONDS):
                        self._eos_task = asyncio.create_task(self._send_eos(ws))
                        self._eos_task.add_done_callback(_observe_task)
                        await asyncio.shield(self._eos_task)
                        await self._finished.wait()
                except Exception as error:
                    finalization_error = error
        finally:
            try:
                await ws.close()
                await ws.wait_closed()
            except Exception as error:
                raise STTConnectionCleanupFailed(
                    "Rev AI socket cleanup failed."
                ) from error
            finally:
                eos = self._eos_task
                if eos is not None:
                    if not eos.done():
                        eos.cancel()
                    await asyncio.gather(eos, return_exceptions=True)
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Rev AI STT closed before final output completed."
            ) from finalization_error


class RevAISTT:
    """Create native attempts from validated settings, without opening a connection."""

    def __init__(self, config: RevAIConfig) -> None:
        self.config = RevAIConfig.model_validate(config)

    def stream(self) -> RevAISTTStream:
        return RevAISTTStream(config=self.config)


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
