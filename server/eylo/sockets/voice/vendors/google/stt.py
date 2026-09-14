"""Own a Google Speech v1 async SDK stream and its immutable native settings."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Never

from google.cloud import speech_v1 as speech
from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, TypeAdapter

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.sockets.stt.exceptions import (
    STTConfigurationError,
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTFinalizationFailed,
)
from eylo.sockets.stt.schemas import STTEncoding

_DEFAULT_SAMPLE_RATE = 16000
_QUEUE_CAPACITY = 1000
_FINAL_RESULT_TIMEOUT_SECONDS = 2.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_PCM_SAMPLE_BYTES = 2
_ServiceAccountInfo = TypeAdapter(dict[str, JsonValue])
_Text = Annotated[str, Field(strict=True, min_length=1)]


class GoogleSTTConfig(BaseModel):
    """Consume native settings; model/language identifiers remain vendor-extensible."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )

    model: _Text
    language: _Text
    sample_rate: int = Field(
        default=_DEFAULT_SAMPLE_RATE, strict=True, ge=8000, le=48000
    )
    encoding: STTEncoding = STTEncoding.LINEAR16
    service_account_json: SecretStr = Field(min_length=1, exclude=True, repr=False)
    interim_results: SpeechOption = SpeechOptionState.ENABLED
    punctuation: SpeechOption = SpeechOptionState.ENABLED
    profanity_filter: SpeechOption = SpeechOptionState.DISABLED
    detect_language: SpeechOption = SpeechOptionState.DISABLED
    alternative_languages: tuple[_Text, ...] = Field(default=(), max_length=3)
    word_timestamps: SpeechOption = SpeechOptionState.DISABLED

    def recognition_config(self) -> speech.StreamingRecognitionConfig:
        """The first native request is configuration only; no audio or fallback."""
        if self.encoding not in {STTEncoding.LINEAR16, STTEncoding.PCM_S16LE}:
            raise STTConfigurationError("Google STT requires mono PCM16 input.")
        return speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language,
                model=self.model,
                enable_automatic_punctuation=self.punctuation
                is SpeechOptionState.ENABLED,
                profanity_filter=self.profanity_filter is SpeechOptionState.ENABLED,
                alternative_language_codes=list(self.alternative_languages)
                if self.detect_language is SpeechOptionState.ENABLED
                else [],
                enable_word_time_offsets=self.word_timestamps
                is SpeechOptionState.ENABLED,
            ),
            interim_results=self.interim_results is SpeechOptionState.ENABLED,
        )


class GoogleSTT:
    """Keep resolved credentials local; every attempt gets its own async client."""

    def __init__(self, config: GoogleSTTConfig) -> None:
        self.config = GoogleSTTConfig.model_validate(config)
        self.config.recognition_config()
        try:
            info = _ServiceAccountInfo.validate_json(
                self.config.service_account_json.get_secret_value()
            )
            self._credentials = service_account.Credentials.from_service_account_info(
                info
            )
        except (TypeError, ValueError):
            raise STTConfigurationError(
                "Google service_account_json is invalid."
            ) from None

    def stream(self) -> GoogleSTTStream:
        return GoogleSTTStream(
            config=self.config,
            client=speech.SpeechAsyncClient(credentials=self._credentials),
        )


class GoogleSTTStream:
    """One RPC owns input, native output, and its client channel; never self-retry."""

    def __init__(
        self, *, config: GoogleSTTConfig, client: speech.SpeechAsyncClient
    ) -> None:
        self._config = config
        self._client = client
        self._input: asyncio.Queue[bytes | None] = asyncio.Queue(
            maxsize=_QUEUE_CAPACITY
        )
        self._output: asyncio.Queue[speech.StreamingRecognizeResponse] = asyncio.Queue(
            maxsize=_QUEUE_CAPACITY
        )
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._finish_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        return (
            self._ready.is_set()
            and self._task is not None
            and not self._task.done()
            and self._close_task is None
        )

    async def connect(self) -> None:
        """Wait for SDK connection establishment, not a fabricated local ready flag."""
        if self._close_task is not None:
            raise STTConnectionClosed("Google STT stream is closing.")
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            self._task.add_done_callback(_observe_task)
        await self._ready.wait()
        if self._task.done():
            self._task.result()
            raise STTConnectionClosed("Google STT ended during startup.")

    async def push_audio(self, audio: bytes) -> None:
        """Accept only whole PCM16 samples; a closed owner never silently drops input."""
        task = self._task
        if not self.is_connected or self._finish_task is not None or task is None:
            raise STTConnectionClosed("Google STT is not accepting audio.")
        if len(audio) % _PCM_SAMPLE_BYTES:
            raise STTConfigurationError(
                "Google STT audio must contain whole PCM16 samples."
            )
        if not audio:
            return
        enqueue = asyncio.create_task(self._input.put(audio))
        try:
            await asyncio.wait({enqueue, task}, return_when=asyncio.FIRST_COMPLETED)
            if enqueue.done():
                enqueue.result()
                return
            if not task.cancelled():
                task.result()
            raise STTConnectionClosed("Google STT ended before audio was accepted.")
        finally:
            if not enqueue.done():
                enqueue.cancel()
            await asyncio.gather(enqueue, return_exceptions=True)

    async def finish_input(self) -> None:
        """Half-close once while the response reader remains active."""
        if self._finish_task is None:
            self._finish_task = asyncio.create_task(self._input.put(None))
            self._finish_task.add_done_callback(_observe_task)
        await asyncio.shield(self._finish_task)

    def __aiter__(self) -> GoogleSTTStream:
        return self

    async def __anext__(self) -> speech.StreamingRecognizeResponse:
        if not self._output.empty():
            return self._output.get_nowait()
        task = self._task
        if task is None:
            raise STTConnectionClosed("Google STT has not started.")
        if task.done():
            self._end_iteration(task)
        receive = asyncio.create_task(self._output.get())
        try:
            await asyncio.wait({receive, task}, return_when=asyncio.FIRST_COMPLETED)
            if receive.done():
                return receive.result()
            self._end_iteration(task)
        finally:
            if not receive.done():
                receive.cancel()
            await asyncio.gather(receive, return_exceptions=True)

    def _end_iteration(self, task: asyncio.Task[None]) -> Never:
        """Channel-close cancellation is EOF, not cancellation of the reader's owner."""
        if not task.cancelled() or self._close_task is None:
            task.result()
        raise StopAsyncIteration

    async def _requests(self) -> AsyncIterator[speech.StreamingRecognizeRequest]:
        yield speech.StreamingRecognizeRequest(
            streaming_config=self._config.recognition_config()
        )
        while True:
            audio = await self._input.get()
            try:
                if audio is None:
                    return
                yield speech.StreamingRecognizeRequest(audio_content=audio)
            finally:
                self._input.task_done()

    async def _run(self) -> None:
        try:
            responses = await self._client.streaming_recognize(
                requests=self._requests(),
                retry=None,
                timeout=None,
            )
            self._ready.set()
            async for response in responses:
                if not isinstance(response, speech.StreamingRecognizeResponse):
                    raise TypeError("Google STT returned an invalid native response.")
                await self._output.put(response)
        finally:
            self._ready.set()

    async def aclose(self) -> None:
        """Bound graceful EOF; close the native channel even if output cannot drain."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(_observe_task)
        try:
            async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                await asyncio.shield(self._close_task)
        except TimeoutError as error:
            raise STTConnectionCleanupFailed(
                "Google STT cleanup did not complete."
            ) from error

    async def _close(self) -> None:
        task = self._task
        finalization_error: Exception | None = None
        try:
            if task is not None and not task.done():
                try:
                    async with asyncio.timeout(_FINAL_RESULT_TIMEOUT_SECONDS):
                        await self.finish_input()
                        await asyncio.shield(task)
                except Exception as error:
                    finalization_error = error
        finally:
            try:
                await self._client.transport.close()
            except Exception as error:
                raise STTConnectionCleanupFailed(
                    "Google STT channel close failed."
                ) from error
            finally:
                tasks = [
                    value for value in (task, self._finish_task) if value is not None
                ]
                for value in tasks:
                    if not value.done():
                        value.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        if finalization_error is not None:
            raise STTFinalizationFailed(
                "Google STT closed before final output completed."
            ) from finalization_error


def _observe_task(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()
