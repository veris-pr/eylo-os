"""Lightning-v2 synthesis with typed frames and explicit request ownership.

Each native request owns its connection, as in the vendor's v2 example. The
manager streams successive text chunks without accumulating an audio queue.
Completion closes the native request; interruption invalidates it before close.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Self

import websockets
from pydantic import Field, StrictInt, model_validator
from websockets.asyncio.client import ClientConnection

from eylo.common.contracts.speech_runtime import (
    SpeechOption,
    SpeechOptionState,
    SpeechText,
)
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.adapters.smallest_wire import (
    SMALLEST_PCM_ENCODING,
    SMALLEST_SAMPLE_RATE,
    SMALLEST_WEBSOCKET_URL,
    SmallestChunk,
    SmallestError,
    SmallestModel,
    SmallestOutputError,
    SmallestSpeechRequest,
    SmallestStreamState,
    parse_response,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import (
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)

logger = logging.getLogger(__name__)
_NATIVE_TIMEOUT_SECONDS = 10.0


class SmallestTTSConfig(TTSAdapterConfig):
    """Only the configured v2 endpoint; raw PCM is required by the voice path."""

    provider = TTSProvider.SMALLEST
    voice: SpeechText
    model: SmallestModel
    language: SpeechText
    sample_rate: StrictInt = Field(default=SMALLEST_SAMPLE_RATE, gt=0)
    add_wav_header: SpeechOption = SpeechOptionState.DISABLED

    @model_validator(mode="after")
    def require_raw_audio(self) -> Self:
        if self.add_wav_header is SpeechOptionState.ENABLED:
            raise ValueError(
                "Smallest TTS add_wav_header must be false for realtime voice."
            )
        return self

    @property
    def voice_id(self) -> str:
        return self.voice


class SmallestTTSAdapter(TTSVendorAdapter):
    """One logical session, serialized native requests, cancellation-safe reads."""

    def __init__(self, config: SmallestTTSConfig) -> None:
        self._config = SmallestTTSConfig.model_validate(config)
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.SMALLEST,
                model=self._config.model.value,
                voice=self._config.voice,
                sample_rate=self._config.sample_rate,
                encoding=SMALLEST_PCM_ENCODING,
            )
        )
        self._ws: ClientConnection | None = None
        self._state = SmallestStreamState.DISCONNECTED
        self._native_request_id: str | None = None
        self._completion_error: TTSConnectionFailed | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._request_done = asyncio.Event()
        self._request_done.set()
        self._request_available = asyncio.Event()
        self._epoch = 0
        self._closing: dict[ClientConnection, asyncio.Task[None]] = {}

    async def _open(self) -> ClientConnection:
        try:
            return await websockets.connect(
                SMALLEST_WEBSOCKET_URL,
                additional_headers={"Authorization": f"Bearer {self._config.api_key}"},
                open_timeout=_NATIVE_TIMEOUT_SECONDS,
                close_timeout=_NATIVE_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise TTSConnectionFailed("Smallest TTS connection failed.") from None

    async def connect(self) -> Self:
        async with self._lifecycle_lock:
            if self.is_connected:
                return self
            await self._drain_closes()
            self._ws = await self._open()
            self._completion_error = None
            self._state = SmallestStreamState.READY
            self._request_done.set()
            return self

    def _start_close(self, connection: ClientConnection) -> None:
        if connection in self._closing:
            return
        task = asyncio.create_task(connection.close())
        self._closing[connection] = task
        task.add_done_callback(partial(self._closed, connection))

    def _closed(self, connection: ClientConnection, task: asyncio.Task[None]) -> None:
        self._closing.pop(connection, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Smallest TTS connection cleanup failed")

    async def _drain_closes(self) -> None:
        for task in tuple(self._closing.values()):
            try:
                await asyncio.shield(task)
            except Exception:
                # The owner callback consumes and records the native failure.
                pass

    def _detach(self) -> None:
        connection, self._ws = self._ws, None
        self._native_request_id = None
        self._request_done.set()
        self._request_available.set()
        if connection is not None:
            self._start_close(connection)

    def _fail(self, error: TTSConnectionFailed) -> None:
        self._completion_error = error
        self._state = SmallestStreamState.FAILED
        self._detach()

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            self._epoch += 1
            self._state = SmallestStreamState.DISCONNECTED
            self._detach()
        await self._drain_closes()

    async def send_text(self, text: str) -> None:
        if not text.strip():
            return
        request = SmallestSpeechRequest(
            text=text,
            voice_id=self._config.voice_id,
            language=self._config.language,
            sample_rate=self.sample_rate,
        )
        epoch = self._epoch
        # Wait outside the lifecycle lock so interruption can retire an active
        # request even while the manager is forwarding the next text chunk.
        while True:
            await self._request_done.wait()
            async with self._lifecycle_lock:
                if epoch != self._epoch:
                    return
                if not self.is_connected:
                    raise self._completion_error or TTSConnectionFailed(
                        "Smallest TTS is not connected."
                    )
                if self._state is SmallestStreamState.DRAINING:
                    raise TTSConnectionFailed(
                        "Smallest TTS input is already finalized."
                    )
                if not self._request_done.is_set():
                    continue
                try:
                    await self._drain_closes()
                    if self._ws is None:
                        self._ws = await self._open()
                    self._state = SmallestStreamState.STREAMING
                    self._native_request_id = None
                    self._request_done.clear()
                    async with asyncio.timeout(_NATIVE_TIMEOUT_SECONDS):
                        await self._ws.send(request.model_dump_json())
                    self._request_available.set()
                    return
                except asyncio.CancelledError:
                    self._fail(TTSConnectionFailed("Smallest TTS send cancelled."))
                    raise
                except Exception:
                    error = TTSConnectionFailed("Smallest TTS send failed.")
                    self._fail(error)
                    raise error from None

    async def flush(self) -> None:
        """Every text is a one-shot request; only its native final can drain it."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                raise self._completion_error or TTSConnectionFailed(
                    "Smallest TTS is not connected."
                )
            self._state = (
                SmallestStreamState.COMPLETE
                if self._request_done.is_set()
                else SmallestStreamState.DRAINING
            )
            self._request_available.set()

    async def receive_audio(self) -> bytes | None:
        """Validate before playback; native recv polling cancellation loses no frame."""
        await self._request_available.wait()
        self._request_available.clear()
        if self._completion_error is not None:
            raise self._completion_error
        connection = self._ws
        if connection is None or self._request_done.is_set():
            return None
        self._request_available.set()
        try:
            raw = await connection.recv()
            if self._ws is not connection:
                return None
            if not isinstance(raw, str):
                raise SmallestOutputError("Smallest returned non-JSON synthesis data.")
            message = parse_response(raw)
            if isinstance(message, SmallestError):
                raise SmallestOutputError("Smallest rejected the synthesis request.")
            if self._native_request_id is None:
                self._native_request_id = message.request_id
            elif self._native_request_id != message.request_id:
                raise SmallestOutputError(
                    "Smallest synthesis request identity changed."
                )
            audio = message.data.audio_bytes() if message.data is not None else None
            if not isinstance(message, SmallestChunk):
                self._state = (
                    SmallestStreamState.COMPLETE
                    if self._state is SmallestStreamState.DRAINING
                    else SmallestStreamState.READY
                )
                self._detach()
            return audio
        except asyncio.CancelledError:
            raise
        except Exception as native_error:
            if self._ws is not connection:
                return None
            error = (
                native_error
                if isinstance(native_error, SmallestOutputError)
                else TTSConnectionFailed("Smallest TTS audio stream failed.")
            )
            self._fail(error)
            raise error from None

    async def handle_interruption(self) -> None:
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            self._epoch += 1
            self._state = SmallestStreamState.READY
            self._detach()
        await self._drain_closes()

    async def keepalive(self) -> None:
        async with self._lifecycle_lock:
            connection = self._ws
            if connection is None:
                if self._completion_error is not None:
                    raise self._completion_error
                return
            try:
                async with asyncio.timeout(_NATIVE_TIMEOUT_SECONDS):
                    await connection.ping()
            except asyncio.CancelledError:
                raise
            except Exception:
                error = TTSConnectionFailed("Smallest TTS keepalive failed.")
                self._fail(error)
                raise error from None

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        await self.send_text(text)
        await self.flush()
        while not self.is_turn_complete:
            audio = await self.receive_audio()
            if audio:
                yield audio

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def provider(self) -> str:
        return TTSProvider.SMALLEST.value

    @property
    def is_connected(self) -> bool:
        return self._state not in (
            SmallestStreamState.DISCONNECTED,
            SmallestStreamState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._state is SmallestStreamState.COMPLETE

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    @property
    def model(self) -> str:
        return self._config.model.value

    @property
    def capabilities(self) -> TTSCapabilities:
        # The vendor supports speed, but this adapter does not yet expose it.
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED, sample_rates=(self.sample_rate,)
        )
