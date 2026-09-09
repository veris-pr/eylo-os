"""Adapter construction for the `stt` socket."""

import asyncio
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from uuid import UUID

from pydantic import JsonValue

from eylo.common.contracts.provider_config import Capability, NotConfiguredError
from eylo.runtime.tasks import (
    LongRunningTaskFactory,
    monitor_long_running_tasks,
    teardown_long_running_tasks,
)
from eylo.sockets.stt.adapters.amazon_transcribe_adapter import (
    AmazonTranscribeSTTAdapter,
)
from eylo.sockets.stt.adapters.assemblyai_adapter import AssemblyAIAdapter
from eylo.sockets.stt.adapters.cartesia_adapter import CartesiaAdapter
from eylo.sockets.stt.adapters.deepgram_adapter import DeepgramAdapter
from eylo.sockets.stt.adapters.deepgram_flux_adapter import (
    DeepgramFluxConfig,
    DeepgramFluxSTT,
)
from eylo.sockets.stt.adapters.gladia_adapter import GladiaAdapter
from eylo.sockets.stt.adapters.google_adapter import GoogleAdapter
from eylo.sockets.stt.adapters.revai_adapter import RevAIAdapter
from eylo.sockets.stt.adapters.sarvam_adapter import SarvamSTT, SarvamSTTConfig
from eylo.sockets.stt.adapters.speechmatics_adapter import SpeechmaticsAdapter
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    RETRYABLE_STT_CONNECTION_KINDS,
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTConfig,
    STTEvent,
    STTMetricsSnapshot,
    STTProvider,
)

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 5
_READINESS_POLL_INTERVAL_SECONDS = 0.01
_DISCONNECT_TIMEOUT_SECONDS = 10.0
_FINAL_DELIVERY_TIMEOUT_SECONDS = 2.0
_RESPONSE_TASK_NAME = "stt_factory_service_await_response"
_KEEPALIVE_TASK_NAME = "stt_factory_service_keepalive_loop"
_DEEPGRAM_ENDPOINTING_MS = 500
_DEEPGRAM_UTTERANCE_END_MS = 1000

_REQUIRED_FIELDS: dict[STTProvider, frozenset[str]] = {
    STTProvider.AMAZON_TRANSCRIBE: frozenset(
        {"region", "language", "access_key_id", "secret_access_key"}
    ),
    STTProvider.ASSEMBLYAI: frozenset({"model", "api_key"}),
    STTProvider.CARTESIA: frozenset({"model", "language", "api_key"}),
    STTProvider.DEEPGRAM: frozenset({"model", "language", "api_key"}),
    STTProvider.DEEPGRAM_FLUX: frozenset({"model", "api_key"}),
    STTProvider.GLADIA: frozenset({"language", "api_key"}),
    STTProvider.GOOGLE: frozenset({"model", "language", "service_account_json"}),
    STTProvider.REVAI: frozenset({"language", "api_key"}),
    STTProvider.SARVAM: frozenset({"model", "language", "api_key"}),
    STTProvider.SPEECHMATICS: frozenset({"language", "api_key"}),
}


class STTFactory:
    """Validate resolved config, select an explicit adapter, and own its supervisor."""

    def __init__(
        self,
        organization_id: UUID,
        session_id: str,
        consumer_queue: asyncio.Queue[STTEvent] | None = None,
        stt_config: STTConfig | Mapping[str, object] | None = None,
        stt_vendor: str | STTProvider | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        """Resolved keys override settings; no vendor connection opens here."""
        self._organization_id = organization_id
        self._session_id = session_id

        self._typed_config = STTConfig.from_mapping(
            stt_config,
            vendor=stt_vendor,
            api_key=api_key,
        )
        self._stt_vendor = self._typed_config.vendor
        self._stt_service: STTVendorAdapter | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._disconnect_task: asyncio.Task[None] | None = None
        self._pending_event: STTEvent | None = None
        self._respond_back_queue = (
            consumer_queue if consumer_queue is not None else asyncio.Queue()
        )
        self._metrics = STTMetricsSnapshot()

        self._stt_config = self._typed_config.to_adapter_config()
        if self._stt_vendor is STTProvider.DEEPGRAM:
            self._stt_config.setdefault("endpointing", _DEEPGRAM_ENDPOINTING_MS)
            if self._stt_config.get("interim_results") is True:
                self._stt_config.setdefault(
                    "utterance_end_ms", _DEEPGRAM_UTTERANCE_END_MS
                )

        _require_configuration(self._stt_vendor, self._stt_config)

    @property
    def config(self) -> STTConfig:
        """Get the normalized typed config."""
        return self._typed_config

    @property
    def metrics(self) -> dict[str, JsonValue]:
        """Get current lightweight metrics."""
        return self._metrics.as_dict()

    @property
    def capabilities(self) -> STTCapabilities:
        """Read the selected adapter's declaration, constructing it without connecting."""
        return self.service.capabilities

    @property
    def consumer_queue(self) -> asyncio.Queue[STTEvent]:
        """Get the response queue."""
        return self._respond_back_queue

    @property
    def service(self) -> STTVendorAdapter:
        """Get the current STT service, initializing if needed."""
        if self._stt_service:
            return self._stt_service
        return self._initialize_agent()

    @property
    def is_connected(self) -> bool:
        """Check if the STT service is connected."""
        return self._get_connection_status()

    def _get_connection_status(self) -> bool:
        """Check if the STT service is connected."""
        return self.service.is_connected

    def _initialize_agent(self) -> STTVendorAdapter:
        """Create an STT service instance based on the vendor."""
        if not self._stt_service:
            if self._stt_vendor is STTProvider.DEEPGRAM:
                self._stt_service = DeepgramAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.DEEPGRAM_FLUX:
                self._stt_service = DeepgramFluxSTT(
                    config=DeepgramFluxConfig.model_validate(self._stt_config)
                )
            elif self._stt_vendor is STTProvider.SPEECHMATICS:
                self._stt_service = SpeechmaticsAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.GOOGLE:
                self._stt_service = GoogleAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.GLADIA:
                self._stt_service = GladiaAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.REVAI:
                self._stt_service = RevAIAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.SARVAM:
                self._stt_service = SarvamSTT(
                    config=SarvamSTTConfig.model_validate(self._stt_config)
                )
            elif self._stt_vendor is STTProvider.ASSEMBLYAI:
                self._stt_service = AssemblyAIAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.CARTESIA:
                self._stt_service = CartesiaAdapter(config=self._stt_config)
            elif self._stt_vendor is STTProvider.AMAZON_TRANSCRIBE:
                self._stt_service = AmazonTranscribeSTTAdapter(
                    config=self._stt_config,
                )
            else:
                raise ValueError(f"Unsupported STT vendor: {self._stt_vendor}")
        return self._stt_service

    def raise_if_failed(self) -> None:
        """Surface the reader's typed failure before the next supervisor poll.

        Restarting an event reader does not reestablish its failed native RPC.
        Connection retry authority belongs to the bounded connect path instead.
        """
        if self._disconnect_task is None:
            raise_if_stt_task_stopped(self._active_tasks)
        if self._monitor_task is not None:
            raise_if_stt_task_stopped({"stt_factory_monitor": self._monitor_task})

    @property
    def _response_task(self) -> asyncio.Task[None] | None:
        return self._active_tasks.get(_RESPONSE_TASK_NAME)

    @property
    def _keepalive_task(self) -> asyncio.Task[None] | None:
        return self._active_tasks.get(_KEEPALIVE_TASK_NAME)

    async def disconnect(self) -> None:
        """Close the provider before joining final forwarding; retain failed work."""
        if (
            self._disconnect_task is not None
            and self._disconnect_task.done()
            and not self._disconnect_task.cancelled()
            and self._disconnect_task.exception() is not None
            and self._stt_service is not None
        ):
            # An explicit later close may retry disposal of the same retained
            # adapter. It never opens a replacement or duplicates a live task.
            self._disconnect_task = None
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._disconnect())
            self._disconnect_task.add_done_callback(_observe_disconnect)
        await asyncio.shield(self._disconnect_task)

    async def _disconnect(self) -> None:
        await _stop_task(self._monitor_task)
        await _stop_task(self._keepalive_task)
        service = self._stt_service
        finalization_error: Exception | None = None
        try:
            if service is not None:
                try:
                    await self._disconnect_service(service)
                except STTFinalizationFailed as error:
                    # This distinct contract guarantees resources closed even
                    # though final output was incomplete. Deliver queued events.
                    finalization_error = error
                if self._stt_service is service:
                    self._stt_service = None
            if self._response_task is not None:
                if (
                    service is None or not service.is_connected
                ) and self._pending_event is None:
                    # Closed, empty adapter and no acquired event: an idle read
                    # has nothing left to deliver and can be stopped immediately.
                    await _stop_task(self._response_task)
                else:
                    try:
                        async with asyncio.timeout(_FINAL_DELIVERY_TIMEOUT_SECONDS):
                            await asyncio.shield(self._response_task)
                    except Exception as error:
                        finalization_error = error
        finally:
            await _stop_task(self._response_task)
        response_task = self._response_task
        if response_task is not None and not response_task.cancelled():
            response_error = response_task.exception()
            if (
                response_error is not None
                and self._pending_event is None
                and (finalization_error is None or finalization_error is response_error)
            ):
                # An already failed reader is not a new final-delivery failure.
                # Preserve its cause for both live runs and connect-only verification.
                raise response_error
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "STT closed before final output could be fully forwarded."
            ) from finalization_error

    async def _disconnect_service(self, service: STTVendorAdapter) -> None:
        """Adapters must propagate cancellation and release partial connections."""
        task = asyncio.current_task()
        cancellation_count = task.cancelling() if task is not None else 0
        async with asyncio.timeout(_DISCONNECT_TIMEOUT_SECONDS) as deadline:
            await service.disconnect()
        if task is not None and task.cancelling() > cancellation_count:
            raise asyncio.CancelledError
        if deadline.expired():
            raise TimeoutError("STT cleanup exceeded its deadline.")

    async def _connect_attempt(self, service: STTVendorAdapter) -> object:
        """Do not return or retry until readiness or failed-attempt cleanup."""
        task = asyncio.current_task()
        cancellation_count = task.cancelling() if task is not None else 0
        try:
            async with asyncio.timeout(self._typed_config.retry.timeout) as deadline:
                connection = await service.connect()
                if deadline.expired():
                    raise TimeoutError("STT connection exceeded its deadline.")
                if task is not None and task.cancelling() > cancellation_count:
                    raise asyncio.CancelledError
                while not service.is_connected:
                    await asyncio.sleep(_READINESS_POLL_INTERVAL_SECONDS)
            if task is not None and task.cancelling() > cancellation_count:
                raise asyncio.CancelledError
            return connection
        except BaseException as connection_error:
            try:
                await self._disconnect_service(service)
            except Exception as cleanup_error:
                logger.error(
                    "STT startup cleanup failed error_type=%s",
                    type(cleanup_error).__name__,
                )
                if not isinstance(connection_error, asyncio.CancelledError):
                    if task is not None and task.cancelling() > cancellation_count:
                        raise asyncio.CancelledError from cleanup_error
                    raise STTConnectionCleanupFailed(
                        "STT connection cleanup failed; no further attempt was made."
                    ) from cleanup_error
            if (
                not isinstance(connection_error, asyncio.CancelledError)
                and task is not None
                and task.cancelling() > cancellation_count
            ):
                raise asyncio.CancelledError from connection_error
            raise

    async def _connect_with_retry(self, service: STTVendorAdapter) -> object:
        """Retry explicit transient kinds/timeouts; unknown failures stop."""
        retry = self._typed_config.retry
        retries = 0
        while True:
            try:
                return await self._connect_attempt(service)
            except STTConnectionRetryUnsafe:
                raise
            except (STTConnectionFailed, TimeoutError) as error:
                if (
                    isinstance(error, STTConnectionFailed)
                    and error.kind not in RETRYABLE_STT_CONNECTION_KINDS
                ):
                    raise
                if retries >= retry.max_retry:
                    raise
                retries += 1
                failure_kind = (
                    error.kind
                    if isinstance(error, STTConnectionFailed)
                    else STTConnectionFailureKind.TIMEOUT
                )
                logger.warning(
                    "Retrying STT connection retry=%d max_retry=%d failure_kind=%s",
                    retries,
                    retry.max_retry,
                    failure_kind.value,
                )
                await asyncio.sleep(retry.retry_interval)

    async def reconnect(self) -> object:
        """Close before bounded connection attempts; never replay audio here."""
        if self._disconnect_task is not None:
            raise STTConnectionClosed("STT factory is closing; reconnect is refused.")
        service = self.service
        await self._disconnect_service(service)
        self._metrics.mark_reconnect()
        return await self._connect_with_retry(service)

    @asynccontextmanager
    async def connection(
        self,
    ) -> AsyncGenerator[object, None]:
        """Start readers only after a bounded, cleanup-safe connection attempt."""
        if self._pending_event is not None:
            raise STTFinalizationFailed(
                "STT has an undelivered event; a new connection cannot replace it."
            )
        service = self.service
        ws = await self._connect_with_retry(service)
        self._disconnect_task = None
        self._metrics.mark_connected()

        # Dictionary mapping task names to their coroutine functions
        async def _keepalive_loop() -> None:
            """Send periodic keepalive messages to maintain the connection."""
            try:
                while service.is_connected:
                    await asyncio.sleep(_KEEPALIVE_INTERVAL)
                    await service.keepalive()
            except asyncio.CancelledError:
                # Allow cancellation to propagate for clean shutdown
                raise
            except Exception as error:
                logger.error(
                    "STT keepalive loop failed error_type=%s",
                    type(error).__name__,
                )
                raise

        async def _await_response() -> None:
            """Receive and process responses from the STT service."""
            try:
                while service.is_connected:
                    try:
                        event = await service.receive_event()
                        if event:
                            self._pending_event = event
                            self._metrics.mark_event(event.type)
                            logger.info(
                                "STTFactory received type=%s final=%s "
                                "transcript_chars=%d",
                                event.type.value,
                                event.is_final,
                                len(event.transcript),
                            )
                            await self._respond_back_queue.put(event)
                            self._pending_event = None
                        else:
                            await asyncio.sleep(0.01)

                    except asyncio.TimeoutError:
                        # Timeout waiting for response - continue
                        continue
                    except STTConnectionClosed:
                        if service.is_connected:
                            raise
                        return
            except asyncio.CancelledError:
                # Allow cancellation to propagate for clean shutdown
                raise
            except Exception as error:
                self._metrics.mark_error()
                logger.error(
                    "STT response loop failed error_type=%s",
                    type(error).__name__,
                )
                raise

        async def _monitor_tasks() -> None:
            try:
                # Main task monitoring loop
                while service.is_connected:  # this is important to check
                    # otherwise we will go to finally block and cancel all tasks
                    await monitor_long_running_tasks(
                        task_definitions=_long_running_tasks,
                        active_tasks=_active_long_running_tasks,
                        exceptions_to_ignore={asyncio.CancelledError},
                    )
                    raise_if_stt_task_stopped(_active_long_running_tasks)
                    await asyncio.sleep(_KEEPALIVE_INTERVAL)

            except asyncio.CancelledError:
                raise
            except STTConnectionClosed:
                logger.info("STT connection closed")
                raise
            except Exception as error:
                logger.error(
                    "STT task monitor failed error_type=%s",
                    type(error).__name__,
                )
                raise

        _long_running_tasks: dict[str, LongRunningTaskFactory] = {
            _KEEPALIVE_TASK_NAME: _keepalive_loop,
            _RESPONSE_TASK_NAME: _await_response,
        }

        # Initialize active tasks dictionary
        _active_long_running_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_tasks = _active_long_running_tasks
        monitor_task: asyncio.Task[None] | None = None

        try:
            # Start the monitoring task
            # A stopped child ends this attempt; only connect owns retries.
            for name, coro in _long_running_tasks.items():
                _active_long_running_tasks[name] = asyncio.create_task(coro())
            monitor_task = asyncio.create_task(_monitor_tasks())
            self._monitor_task = monitor_task
            yield ws
        finally:
            try:
                await self.disconnect()
            finally:
                if monitor_task is not None:
                    if not monitor_task.done():
                        monitor_task.cancel()
                    await asyncio.gather(monitor_task, return_exceptions=True)
                await teardown_long_running_tasks(
                    active_tasks=_active_long_running_tasks,
                )
                if self._monitor_task is monitor_task:
                    self._monitor_task = None


def raise_if_stt_task_stopped(tasks: Mapping[str, asyncio.Task[None]]) -> None:
    """After permitted restarts, a stopped STT child is terminal for its owner."""
    for name, task in tasks.items():
        if not task.done():
            continue
        if not task.cancelled():
            task.result()
        raise STTConnectionClosed(f"STT task stopped: {name}")


def _observe_disconnect(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


async def _stop_task(task: asyncio.Task[None] | None) -> None:
    """Stop supervision/forwarding without propagating an already observed failure."""
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _require_configuration(vendor: STTProvider, config: Mapping[str, object]) -> None:
    required = _REQUIRED_FIELDS[vendor]
    missing: list[str] = []
    for name in sorted(required):
        value = config.get(name)
        if not isinstance(value, str) or not value.strip():
            missing.append(name)
    if missing:
        raise NotConfiguredError(
            capability=Capability.STT,
            missing=missing,
            configure_via="/api/stt-configs",
        )
