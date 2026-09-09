"""Own Transcribe SDK tasks and partial streams without cancelling CRT futures."""

from __future__ import annotations

import asyncio

from aws_sdk_transcribe_streaming.client import TranscribeStreamingClient
from aws_sdk_transcribe_streaming.config import Config
from aws_sdk_transcribe_streaming.models import (
    AudioEvent,
    AudioStream,
    AudioStreamAudioEvent,
    StartStreamTranscriptionInput,
    StartStreamTranscriptionOutput,
    TranscriptResultStream,
)
from smithy_core.aio.eventstream import DuplexEventStream
from smithy_core.aio.interfaces.eventstream import EventReceiver
from smithy_core.interceptors import InputContext, Interceptor
from smithy_http.aio.interfaces import HTTPRequest, HTTPResponse

from eylo.sockets.stt.adapters.amazon_transcribe_transport import (
    AmazonTranscribeHTTP2Transport,
)
from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionClosed,
)

_CLEANUP_TIMEOUT_SECONDS = 5.0
_GRACEFUL_CLOSE_SECONDS = 2.0

type TranscribeDuplexStream = DuplexEventStream[
    AudioStream, TranscriptResultStream, StartStreamTranscriptionOutput
]


def _observe_completion[T](task: asyncio.Future[T]) -> None:
    """Retrieve late failures without dropping the owner's task handle."""
    if not task.cancelled():
        task.exception()


class _RequestObserver(
    Interceptor[
        StartStreamTranscriptionInput,
        StartStreamTranscriptionOutput,
        HTTPRequest,
        HTTPResponse,
    ]
):
    """Observe the SDK's hidden request task through its public interceptor hook.

    smithy-core 0.6.0 can fail before fulfilling duplex_stream's request future.
    Observe that failure so startup does not hang or leave an unobserved exception.
    A per-call plugin installs this instance after the SDK deep-copies its config.
    """

    def __init__(self) -> None:
        self.failure: asyncio.Future[BaseException] = (
            asyncio.get_running_loop().create_future()
        )

    def install(self, config: Config) -> None:
        config.interceptors.append(self)

    def read_before_execution(
        self, context: InputContext[StartStreamTranscriptionInput]
    ) -> None:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Transcribe execution requires an asyncio task.")
        task.add_done_callback(self._completed)

    def _completed[T](self, task: asyncio.Future[T]) -> None:
        error = asyncio.CancelledError() if task.cancelled() else task.exception()
        if error is not None and not self.failure.done():
            self.failure.set_result(error)


class AmazonTranscribeStream:
    """One attempt owns startup, native I/O and cleanup until they settle.

    Cancellation stops the Eylo waiter, not CRT's callback-owned futures. Cleanup
    signals input completion before waiting for native reads. If disposal cannot
    finish within the bound, its task and stream stay owned; reconnect must fail.
    Each attempt installs an owned HTTP/2 transport. Graceful event-stream close
    has a short grace period, then physical shutdown unblocks outstanding I/O.
    """

    def __init__(self) -> None:
        self._transport = AmazonTranscribeHTTP2Transport()
        self._stream: TranscribeDuplexStream | None = None
        self._output: EventReceiver[TranscriptResultStream] | None = None
        self._response: StartStreamTranscriptionOutput | None = None
        self._startup: asyncio.Task[None] | None = None
        self._read: asyncio.Task[TranscriptResultStream | None] | None = None
        self._send: asyncio.Task[None] | None = None
        self._input_finish: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._drain: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._stream_available = asyncio.Event()

    @property
    def request_id(self) -> str | None:
        return self._response.request_id if self._response is not None else None

    @property
    def session_id(self) -> str | None:
        return self._response.session_id if self._response is not None else None

    async def open(
        self,
        client: TranscribeStreamingClient,
        request: StartStreamTranscriptionInput,
    ) -> None:
        if self._cleanup is not None:
            raise STTConnectionClosed("Transcribe stream is closing.")
        if self._startup is None:
            self._startup = asyncio.create_task(self._open(client, request))
            self._startup.add_done_callback(_observe_completion)
        await asyncio.shield(self._startup)

    async def _open(
        self,
        client: TranscribeStreamingClient,
        request: StartStreamTranscriptionInput,
    ) -> None:
        observer = _RequestObserver()
        start = asyncio.create_task(
            client.start_stream_transcription(
                request, plugins=[observer.install, self._transport.install]
            )
        )
        try:
            await asyncio.wait(
                (start, observer.failure), return_when=asyncio.FIRST_COMPLETED
            )
            if not start.done():
                # The request task is already terminal. Only the orphaned SDK waiter
                # is cancelled; no transport callback is waiting on that future.
                start.cancel()
                await asyncio.gather(start, return_exceptions=True)
                raise observer.failure.result()
            self._stream = start.result()
        finally:
            self._stream_available.set()
        self._response, self._output = await self._stream.await_output()

    async def send_audio(self, data: bytes) -> None:
        async with self._send_lock:
            if (
                self._stream is None
                or self._cleanup is not None
                or self._input_finish is not None
            ):
                raise STTConnectionClosed("Transcribe stream is not writable.")
            if self._send is not None:
                await asyncio.shield(self._send)
            self._send = asyncio.create_task(
                self._stream.input_stream.send(
                    AudioStreamAudioEvent(value=AudioEvent(audio_chunk=data))
                )
            )
            self._send.add_done_callback(_observe_completion)
            await asyncio.shield(self._send)

    async def receive(self) -> TranscriptResultStream | None:
        if self._output is None or self._cleanup is not None:
            raise STTConnectionClosed("Transcribe stream is not readable.")
        if self._read is None:
            self._read = asyncio.create_task(self._output.receive())
            self._read.add_done_callback(_observe_completion)
        result = await asyncio.shield(self._read)
        self._read = None
        return result

    async def finish_input(self) -> None:
        """Send signed EOF once; keep output readable for final transcription."""
        if self._input_finish is None:
            self._input_finish = asyncio.create_task(self._finish_input())
            self._input_finish.add_done_callback(_observe_completion)
        await asyncio.shield(self._input_finish)

    async def _finish_input(self) -> None:
        await self._settle(self._send)
        if self._startup is not None:
            await self._stream_available.wait()
        if self._stream is not None:
            await self._stream.input_stream.close()

    async def close(self) -> None:
        """Report incomplete cleanup; repeated calls await the same owned operation."""
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._close())
            self._cleanup.add_done_callback(_observe_completion)
        try:
            async with asyncio.timeout(_CLEANUP_TIMEOUT_SECONDS):
                await asyncio.shield(self._cleanup)
        except Exception as error:
            raise STTConnectionCleanupFailed(
                "Amazon Transcribe stream cleanup did not complete."
            ) from error

    async def _close(self) -> None:
        self._drain = asyncio.create_task(self._close_events())
        self._drain.add_done_callback(_observe_completion)
        try:
            async with asyncio.timeout(_GRACEFUL_CLOSE_SECONDS):
                await asyncio.shield(self._drain)
        except TimeoutError:
            # Do not cancel native reads/writes. Closing the owned connection is
            # the mechanism that wakes them after the grace period expires.
            pass
        finally:
            await self._transport.close()
        await self._drain
        self._stream = None
        self._output = None
        self._response = None
        self._read = None
        self._send = None
        self._startup = None

    async def _close_events(self) -> None:
        # A cancelled sender may still own a native write. Do not close its writer
        # concurrently; the bounded caller retains ownership if it cannot settle.
        await self._settle(self._send)
        failures: list[Exception] = []
        if self._startup is not None:
            await self._stream_available.wait()
        if self._stream is not None:
            try:
                await self.finish_input()
            except Exception as error:
                failures.append(error)
        await self._settle(self._startup)
        await self._settle(self._read)
        if self._output is not None:
            try:
                await self._output.close()
            except Exception as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup(
                "Amazon Transcribe event-stream cleanup failed.", failures
            )

    @staticmethod
    async def _settle[T](task: asyncio.Future[T] | None) -> None:
        """Existing operation failures are not cleanup failures; disposal continues."""
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
