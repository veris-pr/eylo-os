"""Amazon Polly adapter for the TTS socket contract."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager, suppress
from typing import Self

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from eylo.sockets.tts.adapters.polly_sdk import (
    PollySdkClient,
    PollySynthesisResponse,
    close_audio_stream,
    open_polly_client,
    read_audio,
)
from eylo.sockets.tts.adapters.polly_wire import (
    POLLY_PCM_ENCODING,
    POLLY_PCM_SAMPLE_RATES,
    PollyConfig,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import (
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)

logger = logging.getLogger(__name__)

_AUDIO_CHUNK_SIZE = 4096
_QUEUE_SIZE = 500
_RECEIVE_POLL_SECONDS = 0.1
_VERIFICATION_TEXT = "."


class AmazonPollyTTSAdapter(TTSVendorAdapter):
    """Synthesize ordered text fragments through Amazon Polly.

    Polly uses one HTTP request per fragment and streams the response body. A
    single background worker preserves fragment order while the voice pipeline
    consumes audio concurrently. Interruption cancels the active response and
    discards all queued text/audio for the interrupted generation.
    """

    def __init__(self, config: TTSConfig) -> None:
        self._native_config = PollyConfig.from_runtime(config)
        contract = TTSConfig(
            vendor=TTSProvider.AMAZON_POLLY,
            model=self._native_config.model.value,
            voice=self._native_config.voice,
            language=self._native_config.language,
            sample_rate=self._native_config.sample_rate.value,
            encoding=POLLY_PCM_ENCODING,
            retry=config.retry,
        )
        super().__init__(contract)

        self._session = aioboto3.Session(
            aws_access_key_id=self._native_config.access_key_id,
            aws_secret_access_key=self._native_config.secret_access_key,
            aws_session_token=self._native_config.session_token,
            region_name=self._native_config.region,
        )
        self._client_context: AbstractAsyncContextManager[PollySdkClient] | None = None
        self._client: PollySdkClient | None = None
        self._text_queue: asyncio.Queue[tuple[int, str]] = asyncio.Queue(
            maxsize=_QUEUE_SIZE
        )
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._worker_task: asyncio.Task[None] | None = None
        self._connected = False
        self._synthesizing = False
        self._flush_requested = False
        self._turn_complete = False
        self._generation = 0
        self._completion_error: Exception | None = None

    async def connect(self) -> Self:
        if self._connected and self._client is not None:
            return self

        self._client_context = open_polly_client(self._session)
        try:
            self._client = await self._client_context.__aenter__()
            await self._verify_connection()
        except (TTSConnectionFailed, asyncio.CancelledError):
            await self._close_client()
            raise
        except Exception as error:
            await self._close_client()
            logger.error(
                "Amazon Polly connection failed error_type=%s",
                type(error).__name__,
            )
            raise TTSConnectionFailed("Amazon Polly request failed.") from None

        self._connected = True
        self._completion_error = None
        self._worker_task = asyncio.create_task(self._synthesis_loop())
        logger.info(
            "Amazon Polly connected region=%s engine=%s voice=%s sample_rate=%s",
            self._native_config.region,
            self._native_config.model.value,
            self._native_config.voice,
            self.sample_rate,
        )
        return self

    async def disconnect(self) -> None:
        self._connected = False
        await self._stop_worker()
        self._drain_queue(self._text_queue)
        self._drain_queue(self._audio_queue)
        await self._close_client()
        self._turn_complete = True
        logger.info("Amazon Polly disconnected")

    async def send_text(self, text: str) -> None:
        if not self._connected or self._client is None:
            raise TTSConnectionClosed("Amazon Polly is not connected.")
        if not text or not text.strip():
            return
        self._completion_error = None
        self._flush_requested = False
        self._turn_complete = False
        await self._text_queue.put((self._generation, text))

    async def receive_audio(self) -> bytes | None:
        try:
            chunk = await asyncio.wait_for(
                self._audio_queue.get(), timeout=_RECEIVE_POLL_SECONDS
            )
        except asyncio.TimeoutError:
            self._update_turn_complete()
            return None
        self._audio_queue.task_done()
        self._update_turn_complete()
        return chunk

    async def handle_interruption(self) -> None:
        self._generation += 1
        await self._stop_worker()
        self._drain_queue(self._text_queue)
        self._drain_queue(self._audio_queue)
        self._synthesizing = False
        self._flush_requested = True
        self._completion_error = None
        self._turn_complete = True
        if self._connected:
            self._worker_task = asyncio.create_task(self._synthesis_loop())

    async def flush(self) -> None:
        self._flush_requested = True
        self._update_turn_complete()

    async def keepalive(self) -> None:
        """Polly uses request/response HTTP and needs no keepalive frame."""

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_turn_complete(self) -> bool:
        self._update_turn_complete()
        return self._turn_complete

    @property
    def turn_completion_error(self) -> Exception | None:
        return self._completion_error

    @property
    def provider(self) -> str:
        return TTSProvider.AMAZON_POLLY.value

    @property
    def sample_rate(self) -> int:
        return self._native_config.sample_rate.value

    @property
    def model(self) -> str:
        return self._native_config.model.value

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.SUPPORTED,
            native_interruption=TTSCapabilitySupport.UNSUPPORTED,
            aligned_transcript=TTSCapabilitySupport.UNSUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.UNSUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.UNSUPPORTED,
            word_timestamps=TTSCapabilitySupport.UNSUPPORTED,
            sample_rates=POLLY_PCM_SAMPLE_RATES,
            languages_count=1,
        )

    async def _verify_connection(self) -> None:
        response = await self._synthesize(_VERIFICATION_TEXT)
        audio_stream = response.audio_stream
        try:
            while await read_audio(audio_stream, _AUDIO_CHUNK_SIZE):
                pass
        finally:
            await close_audio_stream(audio_stream)

    async def _synthesis_loop(self) -> None:
        while True:
            generation, text = await self._text_queue.get()
            try:
                if generation != self._generation:
                    continue
                self._synthesizing = True
                await self._synthesize_and_queue(text, generation)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._completion_error = _connection_error(error)
                logger.error(
                    "Amazon Polly synthesis failed error_type=%s",
                    type(error).__name__,
                )
            finally:
                self._synthesizing = False
                self._text_queue.task_done()
                self._update_turn_complete()

    async def _synthesize_and_queue(self, text: str, generation: int) -> None:
        response = await self._synthesize(text)
        audio_stream = response.audio_stream
        try:
            while self._connected and generation == self._generation:
                chunk = await read_audio(audio_stream, _AUDIO_CHUNK_SIZE)
                if not chunk:
                    break
                await self._audio_queue.put(chunk)
        finally:
            await close_audio_stream(audio_stream)

    async def _synthesize(self, text: str) -> PollySynthesisResponse:
        if self._client is None:
            raise TTSConnectionClosed("Amazon Polly is not connected.")
        try:
            request = self._native_config.request(text)
            response = await self._client.synthesize_speech(
                Engine=request.Engine.value,
                LanguageCode=request.LanguageCode,
                OutputFormat=request.OutputFormat,
                SampleRate=request.SampleRate,
                Text=request.Text,
                TextType=request.TextType,
                VoiceId=request.VoiceId,
            )
            return await PollySynthesisResponse.from_sdk(response)
        except (BotoCoreError, ClientError) as error:
            raise _connection_error(error) from None

    async def _stop_worker(self) -> None:
        task = self._worker_task
        self._worker_task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _close_client(self) -> None:
        context = self._client_context
        self._client_context = None
        self._client = None
        if context is not None:
            with suppress(Exception):
                await context.__aexit__(None, None, None)

    def _update_turn_complete(self) -> None:
        self._turn_complete = bool(
            self._flush_requested
            and not self._synthesizing
            and self._text_queue.empty()
            and self._audio_queue.empty()
        )

    @staticmethod
    def _drain_queue[T](queue: asyncio.Queue[T]) -> None:
        while not queue.empty():
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                return


def _connection_error(error: Exception) -> TTSConnectionFailed:
    if isinstance(error, TTSConnectionFailed):
        return error
    return TTSConnectionFailed("Amazon Polly request failed.")
