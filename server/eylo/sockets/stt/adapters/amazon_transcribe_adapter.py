"""Amazon Transcribe streaming adapter for the STT socket contract."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from aws_sdk_transcribe_streaming.client import TranscribeStreamingClient
from aws_sdk_transcribe_streaming.config import Config
from aws_sdk_transcribe_streaming.models import (
    BadRequestException,
    ConflictException,
    InternalFailureException,
    LanguageCode,
    LimitExceededException,
    MediaEncoding,
    PartialResultsStability,
    ServiceUnavailableException,
    StartStreamTranscriptionInput,
    TranscriptResultStreamBadRequestException,
    TranscriptResultStreamConflictException,
    TranscriptResultStreamInternalFailureException,
    TranscriptResultStreamLimitExceededException,
    TranscriptResultStreamServiceUnavailableException,
    TranscriptResultStreamTranscriptEvent,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from smithy_aws_core.identity import StaticCredentialsResolver
from smithy_core.exceptions import SmithyIdentityError

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.adapters.amazon_transcribe_stream import AmazonTranscribeStream
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailed,
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
    TimedWord,
)

logger = logging.getLogger(__name__)

_SUPPORTED_SAMPLE_RATES = (8000, 16000, 44100, 48000)
_RESPONSE_QUEUE_SIZE = 1000
_MILLISECONDS_PER_SECOND = 1000
_DEFAULT_SAMPLE_RATE = 16000
_STANDARD_MODEL = "standard"
_FINAL_RESULT_TIMEOUT_SECONDS = 2.0

_NonemptyText = Annotated[str, Field(strict=True, min_length=1)]


class AmazonTranscribeAdapterConfig(BaseModel):
    """Validate consumed AWS options; shared settings do not become native fields."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        str_strip_whitespace=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    region: _NonemptyText
    language: LanguageCode
    sample_rate: int = Field(default=_DEFAULT_SAMPLE_RATE, strict=True)
    access_key_id: SecretStr = Field(min_length=1, repr=False, exclude=True)
    secret_access_key: SecretStr = Field(min_length=1, repr=False, exclude=True)
    session_token: SecretStr | None = Field(
        default=None, min_length=1, repr=False, exclude=True
    )
    vocabulary_name: _NonemptyText | None = None
    language_model_name: _NonemptyText | None = None
    show_speaker_label: SpeechOption = SpeechOptionState.DISABLED
    partial_results_stability: PartialResultsStability | None = None

    @field_validator("sample_rate")
    @classmethod
    def supported_sample_rate(cls, value: int) -> int:
        if value not in _SUPPORTED_SAMPLE_RATES:
            raise ValueError("Amazon Transcribe sample_rate is not supported.")
        return value

    @field_validator(
        "access_key_id", "secret_access_key", "session_token", mode="before"
    )
    @classmethod
    def normalize_secret(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if value is None:
            return value
        if isinstance(value, str):
            return value.strip()
        raise ValueError("Amazon Transcribe credentials must be text.")

    @field_validator("language", "partial_results_stability", mode="before")
    @classmethod
    def normalize_choice(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, str):
            return value.strip()
        raise ValueError("Amazon Transcribe option must be text or its native enum.")

    @field_validator("language")
    @classmethod
    def supported_language(cls, value: LanguageCode) -> LanguageCode:
        # Smithy's enums admit unknown response values for forward compatibility.
        # Operator requests must select one of the installed SDK's known values.
        if value not in tuple(LanguageCode):
            raise ValueError("Amazon Transcribe language is not supported by the SDK.")
        return value

    @field_validator("partial_results_stability")
    @classmethod
    def supported_stability(
        cls, value: PartialResultsStability | None
    ) -> PartialResultsStability | None:
        if value is not None and value not in tuple(PartialResultsStability):
            raise ValueError("Amazon Transcribe partial_results_stability is invalid.")
        return value


class AmazonTranscribeResultMetadata(BaseModel):
    """Native result identity is distinct from the HTTP request and stream session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_id: str | None = None
    channel_id: str | None = None


class AmazonTranscribeSTTAdapter(STTVendorAdapter):
    """Stream signed PCM audio through Amazon Transcribe.

    The adapter receives credentials as resolved primitives. It never reads
    provider configuration, environment credentials, or platform domain types.
    """

    def __init__(self, config: object) -> None:
        super().__init__()
        self._config = AmazonTranscribeAdapterConfig.model_validate(config)
        self._client = TranscribeStreamingClient(
            Config(
                region=self._config.region,
                aws_access_key_id=self._config.access_key_id.get_secret_value(),
                aws_credentials_identity_resolver=StaticCredentialsResolver(),
                aws_secret_access_key=self._config.secret_access_key.get_secret_value(),
                aws_session_token=self._config.session_token.get_secret_value()
                if self._config.session_token is not None
                else None,
            )
        )
        self._stream: AmazonTranscribeStream | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._receive_task: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[STTEvent] = asyncio.Queue(
            maxsize=_RESPONSE_QUEUE_SIZE
        )
        self._connected = False
        self._disconnecting = False
        self._stream_error: Exception | None = None
        self._disconnect_task: asyncio.Task[None] | None = None

    async def connect(self) -> AmazonTranscribeSTTAdapter:
        async with self._lifecycle_lock:
            if self._connected:
                return self
            await self._disconnect()
            self._disconnect_task = None
            self._events = asyncio.Queue(maxsize=_RESPONSE_QUEUE_SIZE)
            self._stream_error = None
            self._stream = AmazonTranscribeStream()
            try:
                await self._stream.open(self._client, self._request())
            except BaseException as error:
                try:
                    await self._disconnect()
                except Exception as cleanup_error:
                    if isinstance(error, asyncio.CancelledError):
                        raise error from cleanup_error
                    raise STTConnectionCleanupFailed(
                        "Amazon Transcribe startup cleanup did not complete."
                    ) from cleanup_error
                if isinstance(error, Exception):
                    # Native service-error retry admission remains a separate
                    # policy from physical cleanup and final transcript drain.
                    raise STTConnectionRetryUnsafe(
                        "Amazon Transcribe connection failed.",
                        kind=_stream_failure(error).kind,
                    ) from error
                raise
            self._disconnecting = False
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_events())
            logger.info("Amazon Transcribe connected")
            return self

    def _request(self) -> StartStreamTranscriptionInput:
        request = StartStreamTranscriptionInput(
            language_code=self._config.language,
            media_sample_rate_hertz=self._config.sample_rate,
            media_encoding=MediaEncoding.PCM,
            vocabulary_name=self._config.vocabulary_name,
            show_speaker_label=(
                self._config.show_speaker_label is SpeechOptionState.ENABLED
            ),
            enable_partial_results_stabilization=(
                self._config.partial_results_stability is not None
            ),
            partial_results_stability=self._config.partial_results_stability,
            language_model_name=self._config.language_model_name,
        )
        return request

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        if self._disconnect_task is None:
            self._disconnect_task = asyncio.create_task(self._close_connection())
            self._disconnect_task.add_done_callback(_observe_disconnect)
        await asyncio.shield(self._disconnect_task)

    async def _close_connection(self) -> None:
        self._disconnecting = True
        task = self._receive_task
        stream = self._stream
        previous_stream_error = self._stream_error
        finalization_error: Exception | None = None
        try:
            if stream is not None and task is not None:
                try:
                    async with asyncio.timeout(_FINAL_RESULT_TIMEOUT_SECONDS):
                        await stream.finish_input()
                        await asyncio.shield(task)
                    if (
                        self._stream_error is not None
                        and self._stream_error is not previous_stream_error
                    ):
                        raise self._stream_error
                except Exception as error:
                    finalization_error = error
        finally:
            self._connected = False
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if stream is not None:
                await stream.close()
                self._stream = None
            self._receive_task = None
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Amazon Transcribe closed before final output could be fully received."
            ) from finalization_error

    async def send_audio(self, audio_data: bytes) -> None:
        if self._disconnecting or not self._connected or self._stream is None:
            raise STTConnectionClosed("Amazon Transcribe is not connected.")
        if not audio_data:
            return
        try:
            await self._stream.send_audio(audio_data)
        except Exception as error:
            self._connected = False
            raise STTConnectionClosed(
                "Amazon Transcribe audio stream closed."
            ) from error

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        if not self._events.empty():
            return self._events.get_nowait()
        if self._stream_error is not None:
            self._connected = False
            if isinstance(self._stream_error, STTConnectionFailed):
                raise self._stream_error
            raise _stream_failure(self._stream_error) from self._stream_error
        if not self._connected:
            raise STTConnectionClosed("Amazon Transcribe stream ended.")
        try:
            return await asyncio.wait_for(
                self._events.get(),
                timeout=timeout_ms / _MILLISECONDS_PER_SECOND,
            )
        except asyncio.TimeoutError:
            return None

    async def keepalive(self) -> None:
        """Amazon Transcribe has no separate keepalive frame."""

    async def flush(self) -> None:
        """Amazon Transcribe exposes final results through continuous audio."""

    @property
    def is_connected(self) -> bool:
        """Keep queued output and a not-yet-delivered terminal failure readable."""
        return self._connected or not self._events.empty()

    @property
    def provider(self) -> str:
        return STTProvider.AMAZON_TRANSCRIBE.value

    @property
    def model(self) -> str:
        return self._config.language_model_name or _STANDARD_MODEL

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            batch_recognize=STTCapabilitySupport.UNSUPPORTED,
            interim_results=STTCapabilitySupport.SUPPORTED,
            vad_events=STTCapabilitySupport.UNSUPPORTED,
            turn_detection=STTCapabilitySupport.UNSUPPORTED,
            word_timestamps=STTCapabilitySupport.SUPPORTED,
            speaker_labels=STTCapabilitySupport.SUPPORTED,
            language_detection=STTCapabilitySupport.UNSUPPORTED,
            custom_vocabulary=STTCapabilitySupport.SUPPORTED,
            punctuation=STTCapabilitySupport.SUPPORTED,
            supported_encodings=(STTEncoding.PCM_S16LE, STTEncoding.LINEAR16),
            supported_sample_rates=_SUPPORTED_SAMPLE_RATES,
        )

    async def _receive_events(self) -> None:
        try:
            while self._stream is not None:
                event = await self._stream.receive()
                if event is None:
                    break
                if isinstance(
                    event,
                    (
                        TranscriptResultStreamBadRequestException,
                        TranscriptResultStreamConflictException,
                        TranscriptResultStreamInternalFailureException,
                        TranscriptResultStreamLimitExceededException,
                        TranscriptResultStreamServiceUnavailableException,
                    ),
                ):
                    raise event.value
                if not isinstance(event, TranscriptResultStreamTranscriptEvent):
                    raise STTConnectionFailed(
                        "Amazon Transcribe returned an unknown stream event.",
                        kind=STTConnectionFailureKind.PROTOCOL,
                    )
                await self._enqueue_transcript_event(event)
        except StopAsyncIteration:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stream_error = error
            logger.error(
                "Amazon Transcribe receive failed error_type=%s",
                type(error).__name__,
            )
        finally:
            if self._stream_error is None:
                self._connected = False

    async def _enqueue_transcript_event(
        self,
        event: TranscriptResultStreamTranscriptEvent,
    ) -> None:
        transcript = event.value.transcript
        if transcript is None:
            return
        stream = self._stream
        session_id = stream.session_id if stream is not None else None
        request_id = stream.request_id if stream is not None else None
        for result in transcript.results or ():
            alternatives = result.alternatives or ()
            if not alternatives:
                continue
            alternative = alternatives[0]
            text = alternative.transcript or ""
            if not text:
                continue
            items = alternative.items or ()
            confidences = [
                item.confidence for item in items if item.confidence is not None
            ]
            confidence = sum(confidences) / len(confidences) if confidences else None
            language = result.language_code
            speakers = {item.speaker for item in items if item.speaker is not None}
            words = tuple(
                TimedWord(
                    word=item.content or "",
                    start_time=item.start_time,
                    end_time=item.end_time,
                    confidence=item.confidence,
                    speaker_id=item.speaker,
                )
                for item in items
                if item.content
            )
            await self._events.put(
                STTEvent(
                    type=(
                        STTEventType.TRANSCRIPT_PARTIAL
                        if result.is_partial
                        else STTEventType.TRANSCRIPT_FINAL
                    ),
                    provider=STTProvider.AMAZON_TRANSCRIBE,
                    model=self.model,
                    session_id=session_id or "",
                    transcript=text,
                    confidence=confidence,
                    language=language.value if language is not None else None,
                    provider_request_id=request_id,
                    words=words,
                    speaker_id=next(iter(speakers)) if len(speakers) == 1 else None,
                    audio_start_ms=int(result.start_time * _MILLISECONDS_PER_SECOND),
                    audio_end_ms=int(result.end_time * _MILLISECONDS_PER_SECOND),
                    vendor_metadata=AmazonTranscribeResultMetadata(
                        result_id=result.result_id,
                        channel_id=result.channel_id,
                    ).model_dump(mode="json", exclude_none=True),
                )
            )


def _observe_disconnect(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


def _stream_failure(error: Exception) -> STTConnectionFailed:
    """Retain native categories for diagnostics, not as evidence of replay safety."""
    if isinstance(error, STTConnectionFailed):
        return error
    if isinstance(error, SmithyIdentityError):
        kind = STTConnectionFailureKind.AUTHENTICATION
    elif isinstance(error, (BadRequestException, ConflictException)):
        kind = STTConnectionFailureKind.REQUEST_REJECTED
    elif isinstance(error, LimitExceededException):
        kind = STTConnectionFailureKind.QUOTA_EXCEEDED
    elif isinstance(error, (InternalFailureException, ServiceUnavailableException)):
        kind = STTConnectionFailureKind.SERVICE_UNAVAILABLE
    else:
        kind = STTConnectionFailureKind.UNKNOWN
    return STTConnectionFailed("Amazon Transcribe response stream failed.", kind=kind)
