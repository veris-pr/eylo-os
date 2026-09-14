"""Translate Google Speech v1 native responses into the STT socket contract."""

from __future__ import annotations

import asyncio
import logging

from google.api_core import exceptions as google_errors
from google.cloud import speech_v1 as speech
from google.rpc import code_pb2
from pydantic import BaseModel, ConfigDict

from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    STTConnectionClosed,
    STTConnectionFailed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
    STTFinalizationFailed,
)
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTCapabilitySupport,
    STTEvent,
    STTEventType,
    STTProvider,
    TimedWord,
)
from eylo.sockets.voice.vendors.google import (
    GoogleSTT,
    GoogleSTTConfig,
    GoogleSTTStream,
)

logger = logging.getLogger(__name__)
_RESPONSE_QUEUE_CAPACITY = 1000
_FINAL_FORWARD_TIMEOUT_SECONDS = 2.0
_MILLISECONDS_PER_SECOND = 1000
_STATUS_KINDS: dict[int, STTConnectionFailureKind] = {
    code_pb2.UNAUTHENTICATED: STTConnectionFailureKind.AUTHENTICATION,
    code_pb2.PERMISSION_DENIED: STTConnectionFailureKind.AUTHORIZATION,
    code_pb2.INVALID_ARGUMENT: STTConnectionFailureKind.REQUEST_REJECTED,
    code_pb2.RESOURCE_EXHAUSTED: STTConnectionFailureKind.QUOTA_EXCEEDED,
    code_pb2.UNAVAILABLE: STTConnectionFailureKind.SERVICE_UNAVAILABLE,
    code_pb2.DEADLINE_EXCEEDED: STTConnectionFailureKind.TIMEOUT,
}
_ERROR_KINDS = (
    (google_errors.Unauthenticated, STTConnectionFailureKind.AUTHENTICATION),
    (google_errors.PermissionDenied, STTConnectionFailureKind.AUTHORIZATION),
    (google_errors.InvalidArgument, STTConnectionFailureKind.REQUEST_REJECTED),
    (google_errors.ResourceExhausted, STTConnectionFailureKind.QUOTA_EXCEEDED),
    (google_errors.ServiceUnavailable, STTConnectionFailureKind.SERVICE_UNAVAILABLE),
    (google_errors.DeadlineExceeded, STTConnectionFailureKind.TIMEOUT),
)
_SPEECH_EVENTS: dict[int, STTEventType] = {
    speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN: STTEventType.SPEECH_START,
    speech.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END: STTEventType.SPEECH_END,
    speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE: STTEventType.SPEECH_END,
}


class GoogleResultMetadata(BaseModel):
    """Native channel/stability are not fabricated request or segment identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    channel_tag: int | None = None
    stability: float | None = None


def google_stt_events(
    response: speech.StreamingRecognizeResponse, *, model: str
) -> tuple[STTEvent, ...]:
    """Preserve native ordering, absent confidence, timing and detected language."""
    if response.error.code != code_pb2.OK:
        raise STTConnectionRetryUnsafe(
            "Google STT rejected the stream.",
            kind=_STATUS_KINDS.get(
                response.error.code, STTConnectionFailureKind.UNKNOWN
            ),
        )
    events: list[STTEvent] = []
    event_type = _SPEECH_EVENTS.get(response.speech_event_type)
    if event_type is not None:
        events.append(
            STTEvent(type=event_type, provider=STTProvider.GOOGLE, model=model)
        )
    for result in response.results:
        if not result.alternatives:
            continue
        alternative = result.alternatives[0]
        if not alternative.transcript:
            continue
        metadata = GoogleResultMetadata(
            channel_tag=result.channel_tag or None,
            stability=result.stability
            if not result.is_final and result.stability
            else None,
        )
        events.append(
            STTEvent(
                type=STTEventType.TRANSCRIPT_FINAL
                if result.is_final
                else STTEventType.TRANSCRIPT_PARTIAL,
                provider=STTProvider.GOOGLE,
                model=model,
                transcript=alternative.transcript,
                confidence=alternative.confidence
                if result.is_final and alternative.confidence
                else None,
                language=result.language_code or None,
                audio_end_ms=int(
                    result.result_end_time.total_seconds() * _MILLISECONDS_PER_SECOND
                ),
                words=[
                    TimedWord(
                        word=word.word,
                        start_time=word.start_time.total_seconds(),
                        end_time=word.end_time.total_seconds(),
                        confidence=word.confidence or None,
                        speaker_id=word.speaker_label or None,
                    )
                    for word in alternative.words
                ],
                vendor_metadata=metadata.model_dump(mode="json", exclude_none=True),
            )
        )
    return tuple(events)


def _stream_error(error: Exception) -> STTConnectionFailed:
    if isinstance(error, STTConnectionFailed):
        return error
    kind = STTConnectionFailureKind.UNKNOWN
    for error_type, candidate in _ERROR_KINDS:
        if isinstance(error, error_type):
            kind = candidate
            break
    return STTConnectionRetryUnsafe("Google STT stream failed.", kind=kind)


class GoogleAdapter(STTVendorAdapter):
    """Own one native attempt; no response dictionaries or implicit reconnects."""

    def __init__(self, config: object) -> None:
        self._config = GoogleSTTConfig.model_validate(config)
        self._stt = GoogleSTT(self._config)
        self._stream: GoogleSTTStream | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[STTEvent] = asyncio.Queue(
            maxsize=_RESPONSE_QUEUE_CAPACITY
        )
        self._stream_error: STTConnectionFailed | None = None
        self._disconnect_task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def connect(self) -> GoogleAdapter:
        async with self._lifecycle_lock:
            if self._stream is not None and self._stream.is_connected:
                return self
            await self._disconnect()
            self._disconnect_task = None
            self._stream_error = None
            self._response_queue = asyncio.Queue(maxsize=_RESPONSE_QUEUE_CAPACITY)
            self._stream = self._stt.stream()
            try:
                await self._stream.connect()
            except BaseException as error:
                try:
                    await self._disconnect()
                except Exception as cleanup_error:
                    if isinstance(error, asyncio.CancelledError):
                        raise error from cleanup_error
                    raise
                if isinstance(error, Exception):
                    raise _stream_error(error) from error
                raise
            self._receive_task = asyncio.create_task(self._receive_events())
            logger.info("Google STT native stream established")
            return self

    async def _receive_events(self) -> None:
        stream = self._stream
        if stream is None:
            raise STTConnectionClosed("Google STT stream is unavailable.")
        try:
            async for response in stream:
                for event in google_stt_events(response, model=self.model):
                    await self._response_queue.put(event)
        except Exception as error:
            self._stream_error = _stream_error(error)
            logger.warning(
                "Google STT receiver ended failure_kind=%s",
                self._stream_error.kind.value,
            )

    async def send_audio(self, audio_data: bytes) -> None:
        if self._stream is None or self._disconnect_task is not None:
            raise STTConnectionClosed("Google STT is not accepting audio.")
        try:
            await self._stream.push_audio(audio_data)
        except google_errors.GoogleAPICallError as error:
            raise _stream_error(error) from error

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        if not self._response_queue.empty():
            return self._response_queue.get_nowait()
        if self._stream_error is not None:
            error = self._stream_error
            self._stream_error = None
            raise error
        if not self.is_connected:
            raise STTConnectionClosed("Google STT stream ended.")
        try:
            return await asyncio.wait_for(
                self._response_queue.get(), timeout_ms / _MILLISECONDS_PER_SECOND
            )
        except TimeoutError:
            return None

    async def keepalive(self) -> None:
        """The gRPC channel owns keepalive; it is not audio or a second request."""
        return None

    async def flush(self) -> None:
        """Speech v1 has no in-stream flush; EOF belongs to disconnect."""
        return None

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._close())
            self._disconnect_task.add_done_callback(_observe_disconnect)
        await asyncio.shield(self._disconnect_task)

    async def _close(self) -> None:
        stream = self._stream
        receiver = self._receive_task
        previous_error = self._stream_error
        finalization_error: Exception | None = None
        try:
            if stream is not None:
                try:
                    await stream.aclose()
                except STTFinalizationFailed as error:
                    finalization_error = error
                self._stream = None
            if receiver is not None:
                try:
                    async with asyncio.timeout(_FINAL_FORWARD_TIMEOUT_SECONDS):
                        await asyncio.shield(receiver)
                    if (
                        self._stream_error is not previous_error
                        and self._stream_error is not None
                    ):
                        raise self._stream_error
                except Exception as error:
                    finalization_error = error
        finally:
            if receiver is not None:
                if not receiver.done():
                    receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
                self._receive_task = None
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Google STT closed before final output was forwarded."
            ) from finalization_error

    @property
    def is_connected(self) -> bool:
        return (
            self._stream_error is not None
            or not self._response_queue.empty()
            or (self._receive_task is not None and not self._receive_task.done())
        )

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def provider(self) -> str:
        return STTProvider.GOOGLE.value

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            language_detection=STTCapabilitySupport.SUPPORTED,
            punctuation=STTCapabilitySupport.SUPPORTED,
            profanity_filter=STTCapabilitySupport.SUPPORTED,
        )


def _observe_disconnect(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
