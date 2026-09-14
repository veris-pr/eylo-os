"""Resolved streaming TTS runtime construction."""

import asyncio
import logging
import time
from typing import Callable
from uuid import UUID

import arrow

from eylo.common.contracts.voice import VoiceSpeechOutcome
from eylo.events.py_events.emitter import emit_ephemeral
from eylo.events.schema.py_events.voice import (
    TTSState,
    TTSStateEvent,
    VoiceServiceEventData,
)
from eylo.pipelines.voice.audio_transport import StreamingAudioTranscoder
from eylo.pipelines.voice.tts_payloads import (
    TTSFinalizeRequest,
    TTSRequest,
    TTSRequestRef,
    TTSTextRequest,
    validate_tts_request,
)
from eylo.runtime.tasks import (
    LongRunningTaskFactory,
    monitor_long_running_tasks,
    teardown_long_running_tasks,
    teardown_queues,
)
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.factory import TTSFactory
from eylo.sockets.tts.schemas import (
    TTSAudioChunk,
    TTSAudioFormat,
    TTSConfig,
    TTSMetricsSnapshot,
    normalize_tts_config,
)
from eylo.sockets.tts.text_stream import (
    SpeakableTextBuffer,
)

logger = logging.getLogger(__name__)


class TTSRealtime:
    _REQUEST_QUEUE_TIMEOUT = (
        2  # seconds (reduced from 5 for faster voice pipeline responsiveness)
    )
    _MAX_QUEUE_SIZE = 1000
    _JOIN_TIMEOUT = 2  # seconds (reduced from 5 for faster shutdown)
    _HEALTH_CHECK_INTERVAL = 2  # seconds (reduced from 5 for faster task monitoring)
    _KEEPALIVE_INTERVAL = 5  # seconds
    _PLAYBACK_ACTIVITY_GRACE_SECONDS = 1.0

    def __init__(
        self,
        organization_id: UUID,
        session_id: str,
        consumer_queue: asyncio.Queue[bytes],
        tts_config: TTSConfig | dict[str, object],
        on_audio_chunk: "Callable[[bytes], None] | None" = None,
        on_playback_started: Callable[[], None] | None = None,
        on_playback_finished: Callable[[], None] | None = None,
        on_turn_outcome: Callable[[str | None, VoiceSpeechOutcome], None] | None = None,
        *,
        api_key: str | None = None,
        consumer_audio_format: TTSAudioFormat | None = None,
    ) -> None:
        self._organization_id = organization_id
        self._session_id = session_id
        self._request_queue: asyncio.Queue[TTSRequest] = asyncio.Queue(
            maxsize=self._MAX_QUEUE_SIZE
        )
        self._response_queue: asyncio.Queue[TTSAudioChunk] = asyncio.Queue(
            maxsize=self._MAX_QUEUE_SIZE
        )
        self._typed_tts_config = normalize_tts_config(tts_config)
        self._consumer_queue = consumer_queue
        self._on_audio_chunk = on_audio_chunk
        self._on_playback_started = on_playback_started
        self._on_playback_finished = on_playback_finished
        self._on_turn_outcome = on_turn_outcome
        # Connection state
        self._is_connected = False

        self._active_turn: TTSRequestRef | None = None
        self._queued_turn: TTSRequestRef | None = None
        self._input_generation = 0
        self._text_buffer = SpeakableTextBuffer()

        # Playback completion signaling
        self._playback_done: asyncio.Event = asyncio.Event()
        self._playback_done.set()
        self._playback_error: Exception | None = None
        self._awaiting_playback_completion = False
        self._received_audio_for_turn = False
        self._sent_text_for_turn = False
        self._last_audio_chunk_at = 0.0
        self._last_playback_activity_at = 0.0

        # Init
        self._tts_vendor = self._typed_tts_config.vendor.value

        self._tts_factory = TTSFactory(
            tts_vendor=self._typed_tts_config.vendor,
            tts_config=self._typed_tts_config,
            api_key=api_key,
        )
        self._audio_transcoder = (
            StreamingAudioTranscoder(
                source=self.output_audio_format,
                target=consumer_audio_format,
            )
            if consumer_audio_format is not None
            else None
        )

        # Metrics
        self._metrics = TTSMetricsSnapshot(
            vendor=self._tts_vendor,
            start_time=arrow.utcnow().timestamp(),
            last_activity=arrow.utcnow().timestamp(),
        )
        self._first_text_sent_at: float | None = None

    @property
    def consumer_queue(self) -> asyncio.Queue[bytes]:
        """Queue that receives synthesized audio for downstream playback."""
        return self._consumer_queue

    @property
    def is_connected(self) -> bool:
        """Return whether the provider connection is ready for requests."""
        return self._is_connected

    @property
    def active_request_id(self) -> str | None:
        if self._active_turn is None or self._active_turn.request_id is None:
            return None
        return str(self._active_turn.request_id)

    @property
    def queued_request_id(self) -> str | None:
        if self._queued_turn is None or self._queued_turn.request_id is None:
            return None
        return str(self._queued_turn.request_id)

    @property
    def output_audio_format(self) -> TTSAudioFormat:
        """Actual provider output, independent of downstream transport needs."""
        return self._tts_factory.service.output_audio_format

    @property
    def consumer_audio_format(self) -> TTSAudioFormat:
        """Format of both consumer queue bytes and the recording callback."""
        if self._audio_transcoder is not None:
            return self._audio_transcoder.target
        return self.output_audio_format

    def _publish_audio(self, audio: bytes) -> None:
        """Publish identical transport bytes to playback and the recording tap."""
        if not audio:
            return
        try:
            self._consumer_queue.put_nowait(audio)
        except asyncio.QueueFull:
            self._metrics.consumer_drops += 1
            raise TTSConnectionFailed("TTS playback queue capacity exceeded.") from None
        self._last_playback_activity_at = time.monotonic()
        if self._on_audio_chunk is not None:
            try:
                self._on_audio_chunk(audio)
            except Exception:
                logger.debug("TTS recording callback failed")

    def _publish_response(self, response: TTSAudioChunk) -> None:
        """Check native format before applying the explicit transport conversion."""
        native_format = self.output_audio_format
        if (
            response.sample_rate != native_format.sample_rate
            or response.encoding != native_format.encoding
            or (
                self._audio_transcoder is not None
                and native_format != self._audio_transcoder.source
            )
        ):
            raise TTSConnectionFailed("TTS audio disagrees with its declared format.")
        audio = (
            self._audio_transcoder.process(response.data)
            if self._audio_transcoder is not None
            else response.data
        )
        self._publish_audio(audio)

    def metrics_snapshot(self) -> TTSMetricsSnapshot:
        """Return a typed snapshot of current TTS runtime metrics."""
        return self._metrics.model_copy()

    def _emit_tts_state(
        self, state: TTSState, message: str, *, error_type: str | None = None
    ) -> None:
        """Emit presentation state without exposing provider error contents."""
        try:
            emit_ephemeral(
                TTSStateEvent(
                    state=state,
                    message=message,
                    vendor=self._tts_vendor,
                    session_id=self._session_id,
                    organization_id=self._organization_id,
                    data=VoiceServiceEventData(error_type=error_type),
                )
            )
            logger.debug(f"Emitted TTS state event: {state.value}")
        except Exception as error:
            logger.error(
                "TTS state event emission failed state=%s error_type=%s",
                state.value,
                type(error).__name__,
            )

    def _notify_playback_started(self) -> None:
        if not self._on_playback_started:
            return
        try:
            self._on_playback_started()
        except Exception:
            logger.debug("Playback-start callback failed")

    def _notify_playback_finished(self) -> None:
        if not self._on_playback_finished:
            return
        try:
            self._on_playback_finished()
        except Exception:
            logger.debug("Playback-finished callback failed")

    def set_turn_outcome_callback(
        self,
        callback: Callable[[str | None, VoiceSpeechOutcome], None],
    ) -> None:
        """Bind session-local speech outcome capture after pipeline creation."""
        self._on_turn_outcome = callback

    def set_playback_callbacks(
        self,
        *,
        started: Callable[[], None] | None,
        finished: Callable[[], None] | None,
    ) -> None:
        """Bind transport-local activity tracking after session registration.

        Telephony creates the provider runtime before its WebSocket session is
        registered. Binding here keeps that construction order without making
        the provider adapter aware of conversation activity policy.
        """
        self._on_playback_started = started
        self._on_playback_finished = finished

    def _notify_turn_outcome(
        self,
        request_id: str | None,
        outcome: VoiceSpeechOutcome,
    ) -> None:
        if self._on_turn_outcome is None:
            return
        try:
            self._on_turn_outcome(request_id, outcome)
        except Exception:
            logger.debug("Turn-outcome callback failed")

    def _reset_playback_tracking(self) -> None:
        self._playback_done.clear()
        self._playback_error = None
        self._awaiting_playback_completion = False
        self._received_audio_for_turn = False
        self._sent_text_for_turn = False
        self._last_audio_chunk_at = 0.0
        self._first_text_sent_at = None

    def _service_reports_turn_complete(self) -> bool:
        """Read the adapter contract without inventing a second completion state."""
        return self._tts_factory.service.is_turn_complete

    def _service_completion_error(self) -> Exception | None:
        return self._tts_factory.service.turn_completion_error

    def _mark_playback_done(
        self,
        *,
        notify_finished: bool = True,
        outcome: VoiceSpeechOutcome = VoiceSpeechOutcome.DRAINED,
    ) -> None:
        request_id = self.active_request_id or self.queued_request_id
        self._awaiting_playback_completion = False
        self._received_audio_for_turn = False
        self._last_audio_chunk_at = 0.0
        self._active_turn = None
        self._queued_turn = None
        self._text_buffer.reset()
        if self._audio_transcoder is not None:
            self._audio_transcoder.reset()
        self._playback_done.set()
        self._notify_turn_outcome(request_id, outcome)
        if notify_finished:
            self._notify_playback_finished()

    def _mark_playback_failed(self, error: Exception) -> None:
        if self._playback_done.is_set() and self._playback_error is not None:
            return
        self._playback_error = error
        self._mark_playback_done(outcome=VoiceSpeechOutcome.FAILED)

    def _stop_after_failure(self, error: Exception) -> None:
        """A failed provider operation ends this runtime; never replay speech."""
        self._is_connected = False
        self._mark_playback_failed(error)

    def is_playback_active(self, grace_seconds: float | None = None) -> bool:
        """Return True while speech is still being produced or draining downstream."""
        if self._active_turn is not None or self._queued_turn is not None:
            return True
        if self._awaiting_playback_completion or not self._playback_done.is_set():
            return True
        if (
            not self._request_queue.empty()
            or not self._response_queue.empty()
            or not self._consumer_queue.empty()
        ):
            return True

        activity_grace = (
            self._PLAYBACK_ACTIVITY_GRACE_SECONDS
            if grace_seconds is None
            else grace_seconds
        )
        if (
            self._last_playback_activity_at > 0
            and time.monotonic() - self._last_playback_activity_at < activity_grace
        ):
            return True
        return False

    def _maybe_mark_playback_done(self) -> None:
        if not self._awaiting_playback_completion:
            return
        if (
            not self._request_queue.empty()
            or not self._response_queue.empty()
            or not self._consumer_queue.empty()
        ):
            return
        error = self._service_completion_error()
        if error is not None:
            if isinstance(error, TTSConnectionClosed):
                self._mark_playback_failed(TTSConnectionFailed("TTS playback failed."))
                self._is_connected = False
                raise error
            self._mark_playback_failed(error)
            return
        if self._service_reports_turn_complete():
            if self._audio_transcoder is not None:
                tail = self._audio_transcoder.finish()
                if tail:
                    self._publish_audio(tail)
                    return
            self._mark_playback_done()

    async def _drain_completed_turn(self) -> None:
        """Finish native output without waiting for another vendor poll timeout.

        Queue joins include locally dequeued work. A turn replaced while waiting
        retains its own completion authority; this drain cannot complete it.
        """
        turn = self._active_turn
        if (
            turn is None
            or not self._awaiting_playback_completion
            or not self._service_reports_turn_complete()
        ):
            self._maybe_mark_playback_done()
            return
        await self._response_queue.join()
        await self._consumer_queue.join()
        if self._active_turn is not turn:
            return
        self._maybe_mark_playback_done()
        # The first completion check may have published the resampler tail.
        await self._consumer_queue.join()
        if self._active_turn is turn:
            self._maybe_mark_playback_done()

    async def add_to_request_queue(self, tts_item: TTSRequest) -> None:
        """Validate before enqueue; dropped work must not change playback identity."""
        tts_item = validate_tts_request(tts_item)
        try:
            self._request_queue.put_nowait(tts_item)
        except asyncio.QueueFull:
            self._metrics.request_drops += 1
            logger.warning(
                "TTS request queue full size=%s organization_id=%s total_drops=%s",
                self._MAX_QUEUE_SIZE,
                self._organization_id,
                self._metrics.request_drops,
            )
            return
        if isinstance(tts_item, TTSTextRequest):
            if not self._same_turn(self._queued_turn, tts_item):
                self._queued_turn = tts_item
                self._playback_done.clear()
                self._notify_playback_started()

    async def _read_from_response_queue(self) -> TTSAudioChunk:
        """Get the processed response from the response queue."""
        return await self._response_queue.get()

    @staticmethod
    def _same_turn(active: TTSRequestRef | None, incoming: TTSRequestRef) -> bool:
        return (
            active is not None
            and active.turn_id == incoming.turn_id
            and active.request_id == incoming.request_id
        )

    async def _begin_turn(self, request: TTSTextRequest) -> None:
        """Replace current synthesis without discarding the next turn's input."""
        if self._same_turn(self._active_turn, request):
            return
        if self._active_turn is not None:
            await self._interrupt_playback()
            self._queued_turn = request
            self._notify_playback_started()
        self._active_turn = request
        self._text_buffer.reset()
        self._reset_playback_tracking()

    async def initialize(self) -> None:
        """Run TTS and surface every fatal startup/runtime failure to the client."""
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._mark_playback_failed(error)
            self._emit_tts_state(
                state=TTSState.ERROR,
                message="TTS service failed",
                error_type=type(error).__name__,
            )
            logger.error(
                "TTS service terminated error_type=%s",
                type(error).__name__,
            )
            raise

    async def _run(self) -> None:  # noqa: C901 - vendor lifecycle orchestration
        # Emit connecting state
        self._emit_tts_state(
            state=TTSState.CONNECTING,
            message="Connecting to TTS service",
        )

        async with self._tts_factory.connection():
            self._is_connected = True

            # Emit connected state
            self._emit_tts_state(
                state=TTSState.CONNECTED,
                message="TTS service connected",
            )

            async def _keepalive_loop() -> None:
                """Send periodic keepalive messages to maintain the connection."""
                try:
                    while self._is_connected:
                        await asyncio.sleep(self._KEEPALIVE_INTERVAL)
                        await self._tts_factory.service.keepalive()
                except asyncio.CancelledError:
                    # Allow cancellation to propagate for clean shutdown
                    raise
                except Exception as error:
                    self._stop_after_failure(error)
                    logger.error(
                        "TTS keepalive loop failed error_type=%s",
                        type(error).__name__,
                    )
                    raise

            async def _forward_request() -> None:
                """Process text data from the request queue and send it to the TTS service."""
                logger.info("TTS forward_request loop started.")
                try:
                    while self._is_connected:
                        try:
                            # Wait for data with a timeout
                            data = await asyncio.wait_for(
                                self._request_queue.get(), self._REQUEST_QUEUE_TIMEOUT
                            )
                            try:
                                if isinstance(data, TTSTextRequest):
                                    await self._begin_turn(data)
                                    generation = self._input_generation
                                    for chunk in self._text_buffer.add(data.text):
                                        await self._process_text_chunk(
                                            chunk, request=data, generation=generation
                                        )

                                elif isinstance(data, TTSFinalizeRequest):
                                    if self._same_turn(self._active_turn, data):
                                        generation = self._input_generation
                                        self._awaiting_playback_completion = True
                                        for chunk in self._text_buffer.flush():
                                            await self._process_text_chunk(
                                                chunk,
                                                request=data,
                                                generation=generation,
                                            )
                                        if not self._current_input(data, generation):
                                            continue
                                        if self._sent_text_for_turn:
                                            logger.debug(
                                                "[TTS_PIPELINE] request_queue → vendor.flush (turn_id=%s)",
                                                data.turn_id,
                                            )
                                            await self._tts_factory.service.flush()
                                        else:
                                            self._mark_playback_done()

                                self._metrics.total_requests_processed += 1
                                self._metrics.last_activity = arrow.utcnow().timestamp()
                            finally:
                                self._request_queue.task_done()
                        except asyncio.TimeoutError:
                            continue
                except asyncio.CancelledError:
                    # Allow cancellation to propagate for clean shutdown
                    raise
                except TTSConnectionClosed:
                    self._is_connected = False
                    raise
                except Exception as error:
                    self._metrics.errors += 1
                    self._stop_after_failure(error)
                    logger.error(
                        "TTS request forwarding failed error_type=%s",
                        type(error).__name__,
                    )
                    raise

            async def _receive_response() -> None:
                """Receive and process responses from the TTS service."""
                logger.info("TTS receive_response loop started.")
                try:
                    while self._is_connected:
                        try:
                            response = await asyncio.wait_for(
                                self._tts_factory.service.receive_audio(),
                                self._REQUEST_QUEUE_TIMEOUT,
                            )
                            if response:
                                audio_chunk = TTSAudioChunk.from_response(
                                    response,
                                    sample_rate=self.output_audio_format.sample_rate,
                                    encoding=self.output_audio_format.encoding,
                                    request_id=self.active_request_id,
                                )
                                self._received_audio_for_turn = True
                                self._last_audio_chunk_at = time.monotonic()
                                self._last_playback_activity_at = (
                                    self._last_audio_chunk_at
                                )
                                if (
                                    self._metrics.first_audio_latency_seconds is None
                                    and self._first_text_sent_at is not None
                                ):
                                    self._metrics.first_audio_latency_seconds = (
                                        self._last_audio_chunk_at
                                        - self._first_text_sent_at
                                    )
                                self._metrics.chunks += 1
                                self._metrics.bytes += len(audio_chunk.data)
                                logger.debug(
                                    f"[TTS_PIPELINE] Vendor returned audio: {len(audio_chunk.data)} bytes → response_queue"
                                )
                                self._response_queue.put_nowait(audio_chunk)
                            else:
                                await self._drain_completed_turn()
                        except asyncio.QueueFull:
                            self._metrics.response_drops += 1
                            logger.warning("Response queue full, dropping data.")
                        except asyncio.TimeoutError:
                            await self._drain_completed_turn()
                            continue
                        except TTSConnectionClosed:
                            logger.info(
                                "[TTS_MANAGER] TTS stream finished. Signaling end of stream."
                            )
                            self._mark_playback_done()
                            break  # Exit the loop gracefully
                except asyncio.CancelledError:
                    logger.info("TTS receive_response loop cancelled.")
                    raise
                except Exception as error:
                    self._metrics.errors += 1
                    self._stop_after_failure(error)
                    logger.error(
                        "TTS response receive failed error_type=%s",
                        type(error).__name__,
                    )
                    raise

            async def _respond_to_consumer() -> None:
                """Send processed responses to the client."""
                logger.info("TTS respond_to_consumer loop started.")
                try:
                    while self._is_connected:
                        # No scheduling gap between dequeue and conversion:
                        # completion must not overtake an in-flight chunk.
                        response = await self._read_from_response_queue()
                        try:
                            self._publish_response(response)
                            self._metrics.total_responses_processed += 1
                        finally:
                            self._response_queue.task_done()
                except asyncio.CancelledError:
                    # Allow cancellation to propagate for clean shutdown
                    raise
                except TTSConnectionClosed:
                    self._is_connected = False
                    raise
                except Exception as error:
                    self._metrics.errors += 1
                    self._stop_after_failure(error)
                    logger.error(
                        "TTS client response failed error_type=%s",
                        type(error).__name__,
                    )
                    raise  # Re-raise to trigger task restart

            # Dictionary mapping task names to their coroutine functions
            task_definitions: dict[str, LongRunningTaskFactory] = {
                "request": _forward_request,
                "response": _receive_response,
                "client": _respond_to_consumer,
                "keepalive": _keepalive_loop,
            }
            active_tasks: dict[str, asyncio.Task[None]] = {
                name: asyncio.create_task(coro())
                for name, coro in task_definitions.items()
            }

            try:
                # Emit ready state
                self._emit_tts_state(
                    state=TTSState.READY,
                    message="TTS service ready to synthesize speech",
                )
                # Main task monitoring loop
                while self._is_connected:
                    await asyncio.sleep(self._HEALTH_CHECK_INTERVAL)
                    if not self._is_connected:
                        break
                    await monitor_long_running_tasks(
                        task_definitions=task_definitions,
                        active_tasks=active_tasks,
                        exceptions_to_ignore={asyncio.CancelledError},
                        exceptions_to_restart={
                            TTSConnectionClosed,
                            TTSConnectionFailed,
                        },
                    )
                if self._playback_error is not None:
                    raise self._playback_error
            except asyncio.CancelledError:
                logger.info("Process TTS main loop was cancelled")
                raise
            except Exception as error:
                logger.error(
                    "TTS main loop failed error_type=%s",
                    type(error).__name__,
                )
                raise
            finally:
                # Clean up phase
                logger.info("Shutting down TTS tasks gracefully...")

                # First, mark as disconnected to signal tasks to stop their loops
                self._is_connected = False
                await teardown_queues(
                    [self._request_queue, self._response_queue],
                    join_timeout=self._JOIN_TIMEOUT,
                )
                await teardown_long_running_tasks(active_tasks)
                logger.info("All TTS tasks have been stopped")

    async def interrupt(self) -> None:
        """User interruption discards all pending input as well as current audio."""
        while not self._request_queue.empty():
            try:
                self._request_queue.get_nowait()
                self._request_queue.task_done()
            except asyncio.QueueEmpty:
                break
        await self._interrupt_playback()

    async def _interrupt_playback(self) -> None:
        """Stop current synthesis; a turn switch must retain queued future input."""
        # Invalidate work before vendor cleanup yields. A send already awaiting
        # the provider must not re-enable bookkeeping or forward old fragments.
        self._input_generation += 1
        self._metrics.interruptions += 1
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
                self._response_queue.task_done()
            except asyncio.QueueEmpty:
                break

        # 2. Drain the consumer-facing queue to discard any buffered audio.
        drained_count = 0
        while not self._consumer_queue.empty():
            try:
                self._consumer_queue.get_nowait()
                self._consumer_queue.task_done()
                drained_count += 1
            except asyncio.QueueEmpty:
                break
        if drained_count > 0:
            logger.info(f"Drained {drained_count} items from the TTS consumer queue.")

        # 3. Propagate interruption to the specific TTS implementation (e.g., Cartesia)
        try:
            await self._tts_factory.service.handle_interruption()
        except Exception:
            self._metrics.errors += 1
            raise
        finally:
            self._mark_playback_done(outcome=VoiceSpeechOutcome.INTERRUPTED)
        logger.info("TTS interrupted successfully.")

    def _current_input(self, request: TTSRequestRef, generation: int) -> bool:
        return generation == self._input_generation and self._same_turn(
            self._active_turn, request
        )

    async def _process_text_chunk(
        self, text: str, *, request: TTSRequestRef, generation: int
    ) -> None:
        """An awaited send cannot revive an interrupted or replaced turn."""
        if not self._current_input(request, generation):
            return
        logger.debug(
            "[TTS_PIPELINE] request_queue → vendor.send_text chars=%d",
            len(text),
        )
        if self._first_text_sent_at is None:
            self._first_text_sent_at = time.monotonic()
        await self._tts_factory.service.send_text(text)
        if self._current_input(request, generation):
            self._sent_text_for_turn = True

    async def wait_until_done(self, timeout: float = 10.0) -> bool:
        """Wait until TTS playback finishes or timeout expires.

        Args:
            timeout: Maximum seconds to wait for playback to finish.

        Returns:
            True if playback completed, False if timeout expired.

        """
        try:
            await asyncio.wait_for(self._playback_done.wait(), timeout=timeout)
            if self._playback_error is not None:
                logger.warning(
                    "TTS turn ended with error organization_id=%s error_type=%s",
                    self._organization_id,
                    type(self._playback_error).__name__,
                )
                return False
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "TTS wait_until_done timed out timeout_seconds=%s organization_id=%s",
                timeout,
                self._organization_id,
            )
            return False

    async def wait_until_flushed(self, timeout: float = 15.0) -> bool:
        """Wait until synthesis and all downstream audio writes finish."""
        try:
            async with asyncio.timeout(timeout):
                await self._request_queue.join()
                if not await self.wait_until_done(timeout=timeout):
                    return False
                await self._consumer_queue.join()
                return True
        except TimeoutError:
            logger.warning(
                "TTS flush timed out organization_id=%s",
                self._organization_id,
            )
            return False

    async def disconnect(self) -> None:
        """Disconnect from the TTS service and clean up resources."""
        if self.is_playback_active():
            self._mark_playback_done(outcome=VoiceSpeechOutcome.CANCELLED)
        if self._is_connected:
            # Emit disconnected state BEFORE actually disconnecting
            # to ensure the WebSocket connection is still active
            self._emit_tts_state(
                state=TTSState.DISCONNECTED,
                message="TTS service disconnected",
            )

            self._is_connected = False
            await self._tts_factory.service.disconnect()

            logger.info("Disconnected from TTS service")
        else:
            logger.warning("TTS service is already disconnected")
