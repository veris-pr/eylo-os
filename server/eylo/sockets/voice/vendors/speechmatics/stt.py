"""Own Speechmatics recognition readiness, PCM writes and validated response delivery."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import NoReturn
from uuid import uuid4

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from eylo.sockets.voice.audio import AudioByteStream, AudioFrame
from eylo.sockets.voice.vendors.speechmatics.wire import (
    SpeechmaticsAudioAdded,
    SpeechmaticsAudioFormat,
    SpeechmaticsDiarization,
    SpeechmaticsEndOfStream,
    SpeechmaticsEndOfTranscript,
    SpeechmaticsError,
    SpeechmaticsEvent,
    SpeechmaticsForceEndOfUtterance,
    SpeechmaticsRecognitionStarted,
    SpeechmaticsStartRecognition,
    SpeechmaticsTranscriptionConfig,
    SpeechmaticsVocabulary,
    parse_speechmatics_event,
)

DEFAULT_BASE_URL = "wss://eu2.rt.speechmatics.com/v2"
SAMPLE_RATE = 16000
# Additional vocabulary can take 15 seconds to initialize according to the vendor.
_CONNECT_TIMEOUT_SECONDS = 30.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_HEARTBEAT_SECONDS = 30.0
_AUDIO_CHUNK_SECONDS = 0.05
_OUTPUT_QUEUE_CAPACITY = 1000
_PCM_BYTES_PER_SAMPLE = 2


class STTOptions(BaseModel):
    """Immutable native material; secrets are neither represented nor serialized."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    recognition: SpeechmaticsStartRecognition
    api_key: SecretStr = Field(min_length=1, repr=False, exclude=True)


class SpeechmaticsStreamState(StrEnum):
    """A failed stream cannot be reused; the caller owns recovery."""

    NEW = "new"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class SpeechmaticsStreamError(RuntimeError):
    """Recognition or transport failed; no implicit retry or fabricated transcript."""


class SpeechmaticsSTT:
    """Build isolated native streams and close only HTTP sessions acquired here."""

    def __init__(
        self,
        *,
        language: str,
        api_key: str,
        enable_partials: bool = True,
        enable_entities: bool = False,
        max_delay: float = 2.0,
        sample_rate: int = SAMPLE_RATE,
        diarization: SpeechmaticsDiarization | None = None,
        custom_vocabulary: tuple[str, ...] | None = None,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._opts = STTOptions(
            recognition=SpeechmaticsStartRecognition(
                audio_format=SpeechmaticsAudioFormat(sample_rate=sample_rate),
                transcription_config=SpeechmaticsTranscriptionConfig(
                    language=language,
                    enable_partials=enable_partials,
                    enable_entities=enable_entities,
                    max_delay=max_delay,
                    diarization=diarization,
                    additional_vocab=tuple(
                        SpeechmaticsVocabulary(content=word)
                        for word in custom_vocabulary or ()
                    ),
                ),
            ),
            api_key=api_key,
        )
        self._session = http_session
        self._owns_session = http_session is None

    @property
    def language(self) -> str:
        return self._opts.recognition.transcription_config.language

    @property
    def provider(self) -> str:
        return "Speechmatics"

    @property
    def sample_rate(self) -> int:
        return self._opts.recognition.audio_format.sample_rate

    def stream(self) -> SpeechmaticsSTTStream:
        """Create an unopened stream; connect must acknowledge recognition before audio."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return SpeechmaticsSTTStream(opts=self._opts, http_session=self._session)

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            session, self._session = self._session, None
            await session.close()


class SpeechmaticsSTTStream:
    """One reader owns terminal output; serialized writes preserve audio/control order."""

    def __init__(
        self, *, opts: STTOptions, http_session: aiohttp.ClientSession
    ) -> None:
        self._opts = opts
        self._session = http_session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._state = SpeechmaticsStreamState.NEW
        self._failure: Exception | None = None
        self._task: asyncio.Task[None] | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._output_queue: asyncio.Queue[SpeechmaticsEvent | None] = asyncio.Queue(
            maxsize=_OUTPUT_QUEUE_CAPACITY
        )
        self._output_closed = False
        self._sequence = 0
        self.recognition_id: str | None = None
        # Native id is optional. This local ID only correlates fragments, not authority.
        self.session_id = str(uuid4())
        sample_rate = opts.recognition.audio_format.sample_rate
        self._audio = AudioByteStream(
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=max(1, round(sample_rate * _AUDIO_CHUNK_SECONDS)),
        )

    @property
    def is_connected(self) -> bool:
        return self._state is SpeechmaticsStreamState.OPEN and self._failure is None

    async def connect(self) -> None:
        """Await RecognitionStarted; no queued input can be silently discarded beforehand."""
        async with self._lifecycle_lock:
            if self.is_connected:
                return
            if self._state is not SpeechmaticsStreamState.NEW:
                raise SpeechmaticsStreamError("Speechmatics stream cannot be reopened.")
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                    self._ws = await self._session.ws_connect(
                        DEFAULT_BASE_URL,
                        headers={
                            "Authorization": f"Bearer {self._opts.api_key.get_secret_value()}"
                        },
                        heartbeat=_HEARTBEAT_SECONDS,
                    )
                    await self._ws.send_str(
                        self._opts.recognition.model_dump_json(exclude_none=True)
                    )
                    while True:
                        event = await self._receive(self._ws)
                        if event is None:
                            continue
                        if isinstance(event, SpeechmaticsError):
                            raise SpeechmaticsStreamError(
                                f"Speechmatics recognition refused: {event.type.value}."
                            )
                        if not isinstance(event, SpeechmaticsRecognitionStarted):
                            raise SpeechmaticsStreamError(
                                "Speechmatics sent output before recognition was ready."
                            )
                        self.recognition_id = event.id
                        self.session_id = event.id or self.session_id
                        break
            except BaseException:
                self._state = SpeechmaticsStreamState.CLOSED
                await self._close_socket()
                self._finish_output()
                raise
            self._state = SpeechmaticsStreamState.OPEN
            self._task = asyncio.create_task(self._read())

    async def _receive(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> SpeechmaticsEvent | None:
        message = await ws.receive()
        if message.type in {
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.ERROR,
        }:
            raise SpeechmaticsStreamError(
                "Speechmatics closed without EndOfTranscript."
            )
        if message.type is not aiohttp.WSMsgType.TEXT:
            return None
        return parse_speechmatics_event(message.data)

    def _require_open(self) -> aiohttp.ClientWebSocketResponse:
        if self._failure is not None:
            raise self._failure
        if not self.is_connected or self._ws is None:
            raise SpeechmaticsStreamError("Speechmatics stream is not open.")
        return self._ws

    async def push_audio(self, frame: AudioFrame) -> None:
        """Reject format mismatch before sending; await socket acceptance for backpressure."""
        if (
            frame.sample_rate != self._opts.recognition.audio_format.sample_rate
            or frame.num_channels != 1
            or len(frame.data) != frame.samples_per_channel * _PCM_BYTES_PER_SAMPLE
        ):
            raise ValueError("Speechmatics requires matching mono 16-bit PCM frames.")
        async with self._send_lock:
            ws = self._require_open()
            try:
                for chunk in self._audio.write(frame.data):
                    await self._send_chunk(ws, chunk.data)
            except BaseException:
                self._failure = SpeechmaticsStreamError(
                    "Speechmatics audio send failed."
                )
                raise

    async def _send_chunk(
        self, ws: aiohttp.ClientWebSocketResponse, data: bytes
    ) -> None:
        await ws.send_bytes(data)
        self._sequence += 1

    async def _flush_audio(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        for chunk in self._audio.flush():
            await self._send_chunk(ws, chunk.data)

    async def flush(self) -> None:
        """Request a final transcript without ending the reusable recognition session."""
        async with self._send_lock:
            ws = self._require_open()
            try:
                await self._flush_audio(ws)
                await ws.send_str(SpeechmaticsForceEndOfUtterance().model_dump_json())
            except BaseException:
                self._failure = SpeechmaticsStreamError(
                    "Speechmatics finalization failed."
                )
                raise

    async def _read(self) -> None:
        try:
            if self._ws is None:
                raise SpeechmaticsStreamError("Speechmatics socket was not acquired.")
            while True:
                event = await self._receive(self._ws)
                if event is None or isinstance(event, SpeechmaticsAudioAdded):
                    continue
                if isinstance(event, SpeechmaticsRecognitionStarted):
                    raise SpeechmaticsStreamError(
                        "Speechmatics restarted an active session."
                    )
                await self._output_queue.put(event)
                if isinstance(event, (SpeechmaticsEndOfTranscript, SpeechmaticsError)):
                    return
        except Exception as error:
            self._failure = error
        finally:
            self._state = SpeechmaticsStreamState.CLOSED
            await self._close_socket()
            self._finish_output()

    def __aiter__(self) -> SpeechmaticsSTTStream:
        return self

    async def __anext__(self) -> SpeechmaticsEvent:
        if self._output_closed and self._output_queue.empty():
            self._raise_terminal()
        event = await self._output_queue.get()
        self._output_queue.task_done()
        if event is not None:
            return event
        self._raise_terminal()

    def _raise_terminal(self) -> NoReturn:
        if self._failure is not None:
            raise self._failure
        raise StopAsyncIteration

    def _finish_output(self) -> None:
        if self._output_closed:
            return
        self._output_closed = True
        try:
            self._output_queue.put_nowait(None)
        except asyncio.QueueFull:
            # Preserve accepted output; a subsequent empty read observes closure.
            pass

    async def _close_socket(self) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                    await self._ws.close()
            except Exception as error:
                if self._failure is None:
                    self._failure = error

    async def aclose(self) -> None:
        """End with the exact sent-chunk count; drain within a bound, then join the reader."""
        async with self._lifecycle_lock:
            try:
                if self.is_connected:
                    self._state = SpeechmaticsStreamState.CLOSING
                    try:
                        async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                            async with self._send_lock:
                                if self._ws is not None:
                                    await self._flush_audio(self._ws)
                                    await self._ws.send_str(
                                        SpeechmaticsEndOfStream(
                                            last_seq_no=self._sequence
                                        ).model_dump_json()
                                    )
                            if self._task is not None:
                                await asyncio.shield(self._task)
                    except TimeoutError:
                        self._failure = self._failure or SpeechmaticsStreamError(
                            "Speechmatics close acknowledgement timed out."
                        )
                    except Exception as error:
                        self._failure = self._failure or error
            finally:
                if self._task is not None:
                    if not self._task.done():
                        self._task.cancel()
                    await asyncio.gather(self._task, return_exceptions=True)
                await self._close_socket()
                self._state = SpeechmaticsStreamState.CLOSED
                self._finish_output()
