"""Deepgram Flux adapter for the canonical STT socket contract."""

import asyncio
import logging
from urllib.parse import urlencode

import websockets
from pydantic import ConfigDict, Field, SecretStr, ValidationError, field_validator

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.adapters.connection_errors import (
    close_failed_websocket_connection,
)
from eylo.sockets.stt.adapters.deepgram_flux_events import (
    flux_stream_final_event,
    flux_turn_event,
)
from eylo.sockets.stt.adapters.deepgram_flux_wire import (
    FluxCloseStream,
    FluxConnected,
    FluxEOTThreshold,
    FluxEOTTimeout,
    FluxEncoding,
    FluxError,
    FluxListenQuery,
    FluxResponse,
    FluxSampleRate,
    FluxTurnInfo,
    parse_flux_response,
)
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTCapabilitySupport,
    STTEncoding,
    STTEvent,
    STTEventType,
    STTProvider,
)

logger = logging.getLogger(__name__)

_DEEPGRAM_API_URL = "wss://api.deepgram.com/v2/listen"
_DEFAULT_EOT_THRESHOLD = 0.85
_DEFAULT_EOT_TIMEOUT_MS = 5000
_CLOSE_TIMEOUT_SECONDS = 2.0
_CLEANUP_WAIT_SECONDS = 7.0
_READY_TIMEOUT_SECONDS = 10.0
_FINAL_DRAIN_SECONDS = 2.0
_RESPONSE_QUEUE_CAPACITY = 1000
_MILLISECONDS_PER_SECOND = 1000


class DeepgramFluxConfig(FluxListenQuery):
    """Frozen consumed settings; shared runtime policy is not vendor query data."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)
    encoding: FluxEncoding = FluxEncoding.LINEAR16
    sample_rate: int = Field(default=FluxSampleRate.HZ_16000, strict=True)
    interim_results: SpeechOption = SpeechOptionState.ENABLED
    eot_threshold: FluxEOTThreshold = _DEFAULT_EOT_THRESHOLD
    eot_timeout_ms: FluxEOTTimeout = _DEFAULT_EOT_TIMEOUT_MS

    @field_validator("encoding", mode="before")
    @classmethod
    def normalize_encoding(cls, value: object) -> object:
        if value == STTEncoding.PCM_S16LE:
            return FluxEncoding.LINEAR16
        return value

    @field_validator("api_key")
    @classmethod
    def require_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Deepgram Flux requires a nonempty API key.")
        return value


class DeepgramFluxSTT(STTVendorAdapter):
    """Own one native stream; only the factory may retry establishment."""

    def __init__(self, config: DeepgramFluxConfig) -> None:
        super().__init__()
        self._config = DeepgramFluxConfig.model_validate(config)
        self._ws: websockets.ClientConnection | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._stream_failure: STTConnectionRetryUnsafe | None = None
        self._last_response: FluxConnected | FluxTurnInfo | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._close_signal_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[STTEvent] = asyncio.Queue(
            maxsize=_RESPONSE_QUEUE_CAPACITY
        )
        self._pending_output: STTEvent | None = None
        self._reader_error: STTConnectionRetryUnsafe | None = None
        logger.info(
            "Deepgram Flux initialized model=%s encoding=%s sample_rate=%d",
            self._config.model,
            self._config.encoding,
            self._config.sample_rate,
        )

    @property
    def is_connected(self) -> bool:
        """Remain readable after native EOF until acquired output/errors are consumed."""
        return (
            not self._response_queue.empty()
            or self._pending_output is not None
            or self._reader_error is not None
            or (self._receive_task is not None and not self._receive_task.done())
        )

    def _get_ws_url(self) -> str:
        """Generate the Deepgram Flux API URL with query parameters."""
        query = FluxListenQuery(
            model=self._config.model,
            sample_rate=self._config.sample_rate,
            encoding=self._config.encoding,
            eot_threshold=self._config.eot_threshold,
            eot_timeout_ms=self._config.eot_timeout_ms,
        )
        return f"{_DEEPGRAM_API_URL}?{urlencode(query.model_dump(mode='json'))}"

    async def keepalive(self) -> None:
        """Keepalive is not supported for Flux, skipping."""
        return None

    async def connect(self) -> websockets.ClientConnection:
        """Publish readiness only after the native acknowledgement; clean failures."""
        async with self._lifecycle_lock:
            if self._close_task is not None:
                await self._await_close()
            if self._stream_failure is not None:
                raise self._stream_failure
            if self._ws is not None:
                if (
                    self._last_response is not None
                    and self._ws.state == websockets.protocol.State.OPEN
                ):
                    return self._ws
                raise STTConnectionRetryUnsafe(
                    "Deepgram Flux's previous stream ended; replacement is refused."
                )
            if self.is_connected:
                raise STTFinalizationFailed(
                    "Deepgram Flux has undelivered output; replacement is refused."
                )
            self._close_task = None
            self._close_signal_task = None
            try:
                self._ws = await websockets.connect(
                    self._get_ws_url(),
                    additional_headers={
                        "Authorization": f"Token {self._config.api_key.get_secret_value()}"
                    },
                    close_timeout=_CLOSE_TIMEOUT_SECONDS,
                )
                async with asyncio.timeout(_READY_TIMEOUT_SECONDS):
                    response = await self._receive_raw_event()
                if not isinstance(response, FluxConnected):
                    self._stream_failure = STTConnectionRetryUnsafe(
                        "Deepgram Flux did not acknowledge the new stream.",
                        kind=STTConnectionFailureKind.PROTOCOL,
                    )
                    raise self._stream_failure
                self._last_response = response
                self._receive_task = asyncio.create_task(self._receive_events())
                self._receive_task.add_done_callback(self._observe_close)
                logger.info("Connected to Deepgram Flux STT service")
                return self._ws
            except BaseException as error:
                logger.error(
                    "Deepgram Flux connection failed error_type=%s",
                    type(error).__name__,
                )
                await close_failed_websocket_connection(error, self._disconnect_locked)

    async def disconnect(self) -> None:
        """Cancelled waiters cannot abandon or duplicate the owned close operation."""
        async with self._lifecycle_lock:
            await self._disconnect_locked()

    async def _disconnect_locked(self) -> None:
        """Used by startup rollback and explicit close under the same lifecycle lock."""
        if (
            self._close_task is not None
            and self._close_task.done()
            and not self._close_task.cancelled()
            and isinstance(self._close_task.exception(), STTConnectionCleanupFailed)
        ):
            # Retry physical disposal of the retained socket, never the
            # application close signal or an uncertain audio send.
            self._close_task = None
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(self._observe_close)
        await self._await_close()

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _await_close(self) -> None:
        task = self._close_task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), _CLEANUP_WAIT_SECONDS)
        except TimeoutError:
            raise STTConnectionCleanupFailed(
                "Deepgram Flux cleanup is still pending; replacement is refused."
            ) from None

    async def _close(self) -> None:
        socket = self._ws
        if socket is None:
            return
        finalization_error: Exception | None = None
        receiver = self._receive_task
        try:
            if (
                self._last_response is not None
                and socket.state == websockets.protocol.State.OPEN
                and self._stream_failure is None
            ):
                try:
                    if self._close_signal_task is None:
                        self._close_signal_task = asyncio.create_task(
                            self._send_close_signal(socket)
                        )
                        self._close_signal_task.add_done_callback(self._observe_close)
                    async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                        await asyncio.shield(self._close_signal_task)
                    if receiver is not None:
                        async with asyncio.timeout(_FINAL_DRAIN_SECONDS):
                            await asyncio.shield(receiver)
                        if self._stream_failure is not None:
                            raise self._stream_failure
                except Exception as error:
                    finalization_error = error
                    self._stream_failure = STTConnectionRetryUnsafe(
                        "Deepgram Flux final output did not complete."
                    )
        finally:
            try:
                await socket.close()
                await socket.wait_closed()
            except Exception:
                if self._stream_failure is None:
                    self._stream_failure = STTConnectionRetryUnsafe(
                        "Deepgram Flux cleanup failed; the stream cannot resume."
                    )
                raise STTConnectionCleanupFailed(
                    "Deepgram Flux cleanup failed; the connection remains owned."
                ) from None
        for task in (self._close_signal_task, receiver):
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._receive_task = None
        self._ws = None
        self._last_response = None
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Deepgram Flux closed before final transcription completed."
            ) from finalization_error

    async def _send_close_signal(self, socket: websockets.ClientConnection) -> None:
        async with self._send_lock:
            if self._stream_failure is not None:
                raise self._stream_failure
            await socket.send(FluxCloseStream().model_dump_json())

    async def _receive(self) -> str | None:
        """Receive a message from the WebSocket connection."""
        if self._stream_failure is not None:
            raise self._stream_failure
        if self._ws is None:
            return None
        try:
            return await self._ws.recv(decode=True)
        except websockets.ConnectionClosed:
            if self._close_signal_task is not None:
                await asyncio.shield(self._close_signal_task)
                if self._stream_failure is None:
                    raise STTConnectionClosed(
                        "Deepgram Flux finished the stream."
                    ) from None
            if self._stream_failure is not None:
                raise self._stream_failure from None
            self._stream_failure = STTConnectionRetryUnsafe(
                "Deepgram Flux ended without confirmed final delivery.",
                kind=STTConnectionFailureKind.NETWORK,
            )
            raise self._stream_failure from None

    async def _receive_raw_event(self) -> FluxResponse | None:
        """Keep failed/malformed provider responses distinct from absent speech."""
        payload = await self._receive()
        if payload is None:
            return None
        try:
            return parse_flux_response(payload)
        except ValidationError:
            self._stream_failure = STTConnectionRetryUnsafe(
                "Deepgram Flux returned an invalid STT event.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
            raise self._stream_failure from None

    async def send_audio(self, audio_data: bytes) -> None:
        """Apply backpressure; uncertain delivery must not be replayed or continued."""
        async with self._send_lock:
            if self._stream_failure is not None:
                raise self._stream_failure
            if (
                self._close_task is not None
                or not self._ws
                or self._last_response is None
                or self._ws.state != websockets.protocol.State.OPEN
            ):
                raise STTConnectionRetryUnsafe("Deepgram Flux is not accepting input.")
            try:
                await self._ws.send(audio_data)
            except asyncio.CancelledError:
                self._stream_failure = STTConnectionRetryUnsafe(
                    "Deepgram Flux audio delivery was interrupted and is uncertain."
                )
                raise
            except Exception:
                self._stream_failure = STTConnectionRetryUnsafe(
                    "Deepgram Flux audio delivery failed and is uncertain."
                )
                raise self._stream_failure from None

    async def _read_next_event(self) -> STTEvent | None:
        """Expose typed hypotheses and turn signals without treating eager text as final."""
        previous = self._last_response
        if previous is None:
            raise STTConnectionClosed("Deepgram Flux has not acknowledged a stream.")
        native = await self._receive_raw_event()
        if native is None:
            return None
        if isinstance(native, FluxError):
            self._stream_failure = STTConnectionRetryUnsafe(
                "Deepgram Flux reported an STT failure.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
            raise self._stream_failure from None
        if (
            isinstance(native, FluxConnected)
            or native.request_id != previous.request_id
            or native.sequence_id <= previous.sequence_id
        ):
            self._stream_failure = STTConnectionRetryUnsafe(
                "Deepgram Flux returned an inconsistent stream identity or sequence.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
            raise self._stream_failure
        self._last_response = native
        event = flux_turn_event(native, model=self.model)
        if (
            event.type is STTEventType.TRANSCRIPT_PARTIAL
            and self._config.interim_results is SpeechOptionState.DISABLED
        ):
            return None
        return event

    async def _publish(self, event: STTEvent) -> None:
        """Retain acquired output if shutdown interrupts queue backpressure."""
        self._pending_output = event
        await self._response_queue.put(event)
        self._pending_output = None

    async def _receive_events(self) -> None:
        try:
            try:
                while True:
                    event = await self._read_next_event()
                    if event is not None:
                        await self._publish(event)
            except STTConnectionClosed:
                native = self._last_response
                if isinstance(native, FluxTurnInfo):
                    final = flux_stream_final_event(native, model=self.model)
                    if final is not None:
                        await self._publish(final)
        except STTConnectionRetryUnsafe as error:
            self._reader_error = error
        except Exception as error:
            logger.error("Flux output failed error_type=%s", type(error).__name__)
            self._stream_failure = STTConnectionRetryUnsafe(
                "Deepgram Flux output processing failed."
            )
            self._reader_error = self._stream_failure

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        """One native reader preserves ordering; consumer cancellation cannot steal data."""
        if not self._response_queue.empty():
            event = self._response_queue.get_nowait()
            self._response_queue.task_done()
            return event
        if self._receive_task is None or self._receive_task.done():
            if self._pending_output is not None:
                event, self._pending_output = self._pending_output, None
                return event
            if self._reader_error is not None:
                error, self._reader_error = self._reader_error, None
                raise error
            raise STTConnectionClosed("Deepgram Flux output ended.")
        try:
            event = await asyncio.wait_for(
                self._response_queue.get(), timeout_ms / _MILLISECONDS_PER_SECOND
            )
            self._response_queue.task_done()
            return event
        except TimeoutError:
            if self._reader_error is not None:
                error, self._reader_error = self._reader_error, None
                raise error
            return None

    async def flush(self) -> None:
        """No flush frame on this stream. Explicit, not faked."""
        return None

    @property
    def provider(self) -> str:
        return STTProvider.DEEPGRAM_FLUX.value

    @property
    def model(self) -> str:
        return self._config.model.value

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def capabilities(self) -> STTCapabilities:
        """Canonical behavior implemented for Listen v2, not Listen v1 features."""
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            batch_recognize=STTCapabilitySupport.UNSUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            vad_events=STTCapabilitySupport.SUPPORTED,
            turn_detection=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            speaker_labels=STTCapabilitySupport.UNSUPPORTED,
            language_detection=STTCapabilitySupport.UNSUPPORTED,
            supported_encodings=(
                STTEncoding.LINEAR16,
                STTEncoding.PCM_S16LE,
                STTEncoding.MULAW,
                STTEncoding.ALAW,
            ),
            supported_sample_rates=tuple(int(rate) for rate in FluxSampleRate),
        )
