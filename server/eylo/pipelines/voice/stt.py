"""Resolved streaming STT runtime construction."""

import asyncio
import logging
from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue

from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.voice import STTState, STTStateEvent
from eylo.pipelines.voice.transcript_inputs import (
    FinalTranscriptBatch,
    VoiceTranscriptInput,
)
from eylo.runtime.tasks import (
    LongRunningTaskFactory,
    monitor_long_running_tasks,
    teardown_long_running_tasks,
)
from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionError,
    STTConnectionFailed,
)
from eylo.sockets.stt.factory import STTFactory, raise_if_stt_task_stopped
from eylo.sockets.stt.schemas import (
    STTConfig,
    STTEvent,
    STTMetricsSnapshot,
    STTProvider,
)

_KEEPALIVE_INTERVAL = 5  # seconds
_MILLISECONDS_PER_SECOND = 1000
_RESPONSE_TASK_NAME = "stt_rt_response"

logger = logging.getLogger(__name__)


class STTRealtime:
    """Own recognition queues, final-text debounce, and STT child-task cleanup."""

    _REQUEST_QUEUE_TIMEOUT = 5  # seconds
    _MAX_QUEUE_SIZE = 100  # Example maximum size for the queues
    _JOIN_TIMEOUT = 10  # seconds
    _HEALTH_CHECK_INTERVAL = 5  # seconds
    _BACKPRESSURE_THRESHOLD = 0.8  # 80% fullness
    _MAX_BUFFER_SEGMENTS = 50  # Safety cap for debouncing

    def __init__(
        self,
        organization_id: UUID,
        session_id: str,
        consumer_queue: asyncio.Queue[VoiceTranscriptInput],
        stt_config: STTConfig | Mapping[str, object] | None = None,
        stt_vendor: str | STTProvider | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        """Retain the factory's validated config; debounce uses milliseconds on input."""
        self._organization_id = organization_id
        self._session_id = session_id

        self._respond_back_queue = consumer_queue

        self._stt_service_results: asyncio.Queue[STTEvent] = asyncio.Queue(
            maxsize=self._MAX_QUEUE_SIZE
        )

        self._transcript_buffer: list[STTEvent] = []
        self._transcript_lock = asyncio.Lock()
        self._wait_task: asyncio.Task[None] | None = None
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._disconnect_task: asyncio.Task[None] | None = None
        self._metrics = STTMetricsSnapshot()

        # Create STT factory
        self._stt_factory = STTFactory(
            organization_id,
            session_id,
            consumer_queue=self._stt_service_results,
            stt_config=stt_config,
            stt_vendor=stt_vendor,
            api_key=api_key,
        )
        self._typed_config = self._stt_factory.config
        self._stt_vendor = self._typed_config.vendor
        self._wait_seconds = self._typed_config.wait_ms / _MILLISECONDS_PER_SECOND

    def _emit_stt_state(
        self, state: STTState, message: str, data: dict[str, JsonValue] | None = None
    ) -> None:
        """Observer failure must not interrupt recognition or expose provider errors."""
        try:
            emit_ephemeral(
                STTStateEvent(
                    state=state,
                    message=message,
                    vendor=self._stt_vendor,
                    session_id=self._session_id,
                    organization_id=self._organization_id,
                    data=data or {},
                )
            )
            logger.debug(f"Emitted STT state event: {state.value}")
        except Exception as error:
            logger.error(
                "STT state event emission failed state=%s error_type=%s",
                state.value,
                type(error).__name__,
            )

    @property
    def is_connected(self) -> bool:
        """Check if the underlying STT service is connected."""
        return self._stt_factory.is_connected

    @property
    def metrics(self) -> dict[str, JsonValue]:
        """Get current lightweight manager metrics."""
        snapshot = self._metrics.as_dict()
        snapshot["factory"] = self._stt_factory.metrics
        return snapshot

    @property
    def _response_task(self) -> asyncio.Task[None] | None:
        return self._active_tasks.get(_RESPONSE_TASK_NAME)

    @staticmethod
    def _is_retryable_send_disconnect(error: Exception) -> bool:
        """Establishment failures and unresolved cleanup never authorize audio replay."""
        if isinstance(error, (STTConnectionFailed, STTConnectionCleanupFailed)):
            return False
        if isinstance(error, STTConnectionError):
            return True
        if isinstance(error, RuntimeError):
            return "not connected" in str(error).lower()
        return False

    async def send_audio(self, audio_data: bytes) -> None:
        """Send audio data to the STT service for speech recognition.

        Args:
            audio_data: Raw audio bytes (typically 16kHz PCM format)

        """
        if self._disconnect_task is not None:
            raise STTConnectionError("STT runtime is closing; audio was not sent.")
        try:
            self._metrics.mark_audio_sent(len(audio_data))
            await self._stt_factory.service.send_audio(audio_data)
        except Exception as error:
            self._metrics.mark_error()
            if not self._is_retryable_send_disconnect(error):
                raise

            logger.warning(
                "STT send path lost connection for session %s (%s). "
                "Reconnecting and retrying once.",
                self._session_id,
                type(error).__name__,
            )
            await self._stt_factory.reconnect()
            self._metrics.mark_reconnect()
            await self._stt_factory.service.send_audio(audio_data)

    async def _await_response(self) -> STTEvent | None:
        """Acquire one result; the forwarding loop owns its acknowledgement."""
        try:
            return await asyncio.wait_for(
                self._stt_service_results.get(),
                self._REQUEST_QUEUE_TIMEOUT,
            )
        except TimeoutError:
            return None

    async def _handle_response_for_consumer(self, event: STTEvent) -> None:
        """Forward typed recognition outcomes; debounce only completed text."""
        self._metrics.mark_event(event.type)
        logger.info(
            "STTRealtime forwarding type=%s final=%s transcript_chars=%d",
            event.type.value,
            event.is_final,
            len(event.transcript),
        )
        if self._wait_seconds <= 0:
            await self._respond_back_queue.put(event)
            return

        if event.is_final and event.transcript:
            await self._cancel_wait_task()
            async with self._transcript_lock:
                self._transcript_buffer.append(event)
                flush_due = len(self._transcript_buffer) >= self._MAX_BUFFER_SEGMENTS
            if flush_due:
                await self._flush_transcript_buffer()
            else:
                self._wait_task = asyncio.create_task(self._run_wait_timer())
            return

        if event.is_speech_start or event.is_speech_end:
            await self._cancel_wait_task()
            if self._transcript_buffer:
                self._wait_task = asyncio.create_task(self._run_wait_timer())
        await self._respond_back_queue.put(event)

    async def initialize(self) -> None:
        """Run STT and surface every fatal startup/runtime failure to the client."""
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._emit_stt_state(
                state=STTState.ERROR,
                message="STT service failed",
                data={"error_type": type(error).__name__},
            )
            logger.error(
                "STT service terminated error_type=%s",
                type(error).__name__,
            )
            raise

    async def _run(self) -> None:
        """Process audio data in real-time through the STT service.

        This method establishes a connection to the STT service and sets up multiple
        concurrent tasks to handle different aspects of audio processing:
        - Sending keepalive signals to maintain the connection
        - Processing audio requests from the queue
        - Receiving and handling responses from the STT service
        - Monitoring health and detecting turn completion events
        """
        # Emit connecting state
        self._emit_stt_state(
            state=STTState.CONNECTING,
            message="Connecting to STT service",
        )

        async with self._stt_factory.connection():
            # Emit connected state
            self._emit_stt_state(
                state=STTState.CONNECTED,
                message="STT service connected",
            )

            async def _respond_to_consumer() -> None:
                """Send processed responses to the client."""
                try:
                    while True:
                        try:
                            response = await self._await_response()
                            if response is not None:
                                try:
                                    await self._handle_response_for_consumer(response)
                                finally:
                                    self._stt_service_results.task_done()
                        except asyncio.TimeoutError:
                            # Timeout waiting for response - continue
                            continue
                except asyncio.CancelledError:
                    # Allow cancellation to propagate for clean shutdown
                    raise
                except Exception as error:
                    logger.error(
                        "STT consumer forwarding failed error_type=%s",
                        type(error).__name__,
                    )
                    raise  # Re-raise to trigger task restart

            # Dictionary mapping task names to their coroutine functions
            task_definitions: dict[str, LongRunningTaskFactory] = {
                _RESPONSE_TASK_NAME: _respond_to_consumer,
            }

            # Initialize active tasks dictionary
            active_tasks: dict[str, asyncio.Task[None]] = {}
            self._active_tasks = active_tasks
            for name, coro in task_definitions.items():
                active_tasks[name] = asyncio.create_task(coro())

            try:
                # Emit ready state
                self._emit_stt_state(
                    state=STTState.READY,
                    message="STT service ready to process audio",
                )

                # Main task monitoring loop
                while self._disconnect_task is None:
                    self._stt_factory.raise_if_failed()
                    if self._wait_task is not None and self._wait_task.done():
                        self._wait_task.result()
                    await monitor_long_running_tasks(
                        task_definitions=task_definitions,
                        active_tasks=active_tasks,
                        exceptions_to_ignore={asyncio.CancelledError},
                        exceptions_to_restart={STTConnectionFailed},
                    )
                    raise_if_stt_task_stopped(active_tasks)
                    await asyncio.sleep(self._HEALTH_CHECK_INTERVAL)

            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error(
                    "STT runtime failed error_type=%s",
                    type(error).__name__,
                )
                raise
            finally:
                try:
                    await self.disconnect()
                finally:
                    await teardown_long_running_tasks(active_tasks=active_tasks)

    async def disconnect(self) -> None:
        """Keep forwarding alive through provider EOF; final delivery is bounded."""
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._disconnect())
            self._disconnect_task.add_done_callback(_observe_disconnect)
        await asyncio.shield(self._disconnect_task)

    async def _disconnect(self) -> None:
        try:
            await self._stt_factory.disconnect()
        finally:
            await self._drain_responses()
        self._emit_stt_state(
            state=STTState.DISCONNECTED,
            message="STT service disconnected",
        )

    async def _drain_responses(self) -> None:
        """No provider producers remain; forward accepted events before final debounce."""
        async with asyncio.timeout(self._JOIN_TIMEOUT):
            if self._response_task is not None:
                if self._response_task.done():
                    self._response_task.result()
                await self._stt_service_results.join()
                if self._response_task.done():
                    self._response_task.result()
            else:
                while not self._stt_service_results.empty():
                    response = self._stt_service_results.get_nowait()
                    try:
                        await self._handle_response_for_consumer(response)
                    finally:
                        self._stt_service_results.task_done()
            await self._cancel_wait_task()
            await self._flush_transcript_buffer()

    async def _cancel_wait_task(self) -> None:
        """Join the owned timer; a previous delivery failure remains visible."""
        task = self._wait_task
        self._wait_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        current = asyncio.current_task()
        cancellation_count = current.cancelling() if current is not None else 0
        try:
            await task
        except asyncio.CancelledError:
            # Suppress only cancellation of the timer, never its caller's.
            if current is not None and current.cancelling() > cancellation_count:
                raise

    async def _flush_transcript_buffer(self) -> None:
        """Keep segments until downstream acceptance; cancellation loses no batch."""
        async with self._transcript_lock:
            if not self._transcript_buffer:
                return
            batch = FinalTranscriptBatch(segments=tuple(self._transcript_buffer))
            await self._respond_back_queue.put(batch)
            self._transcript_buffer.clear()

    async def _run_wait_timer(self) -> None:
        """The runtime owns and observes this task, including delivery failures."""
        await asyncio.sleep(self._wait_seconds)
        await self._flush_transcript_buffer()


def _observe_disconnect(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
