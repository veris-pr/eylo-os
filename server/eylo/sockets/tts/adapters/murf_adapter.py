"""Murf WebSocket transport and native message projection for the TTS manager.

The receiver owns its captured connection. Interruption requests vendor context
clearing and drains local audio; it does not guarantee cancellation of audio
already being synthesized by Murf.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Self

import websockets
from pydantic import Field, StrictInt, field_validator
from websockets.asyncio.client import ClientConnection

from eylo.common.contracts.speech_runtime import SpeechText
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.adapters.murf_audio import MurfAudioDecoder
from eylo.sockets.tts.adapters.murf_wire import (
    DEFAULT_MAX_BUFFER_DELAY_MS,
    DEFAULT_MIN_BUFFER_SIZE,
    DEFAULT_SAMPLE_RATE,
    MAX_BUFFER_DELAY_MS,
    MAX_BUFFER_SIZE,
    MAX_EVENT_BYTES,
    MAX_VARIATION,
    MIN_BUFFER_SIZE,
    MIN_VARIATION,
    MurfAdvancedSettings,
    MurfAudioFormat,
    MurfClear,
    MurfHandshake,
    MurfInitialize,
    MurfOutputError,
    MurfStreamState,
    MurfText,
    MurfVoiceSettings,
    parse_output,
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

_DEFAULT_CHANNEL = "MONO"
_WS_URL = "wss://api.murf.ai/v1/speech/stream-input"

_NATIVE_TIMEOUT_SECONDS = 10.0
_RECEIVE_FRAME_LIMIT = 16


class MurfTTSConfig(TTSAdapterConfig):
    """Configuration for Murf TTS adapter."""

    provider = TTSProvider.MURF
    voice: SpeechText
    sample_rate: StrictInt = Field(default=DEFAULT_SAMPLE_RATE, gt=0)
    format: MurfAudioFormat = MurfAudioFormat.WAV
    channel_type: SpeechText = _DEFAULT_CHANNEL
    style: SpeechText | None = None
    rate: StrictInt = 0
    pitch: StrictInt = 0
    variation: StrictInt = Field(default=1, ge=MIN_VARIATION, le=MAX_VARIATION)
    min_buffer_size: StrictInt = Field(
        default=DEFAULT_MIN_BUFFER_SIZE, ge=MIN_BUFFER_SIZE, le=MAX_BUFFER_SIZE
    )
    max_buffer_delay_ms: StrictInt = Field(
        default=DEFAULT_MAX_BUFFER_DELAY_MS, ge=0, le=MAX_BUFFER_DELAY_MS
    )

    @field_validator("format", mode="before")
    @classmethod
    def normalize_format(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @property
    def voice_id(self) -> str:
        return self.voice


class MurfTTSAdapter(TTSVendorAdapter):
    """Own one native context per turn, with no detached audio receiver.

    The manager's receive task consumes the socket directly. Native bounded
    buffering supplies backpressure; cancellation of a receive poll is harmless.
    Lifecycle writes are serialized, and context identity rejects stale output.
    """

    def __init__(self, config: MurfTTSConfig) -> None:
        config = MurfTTSConfig.model_validate(config)
        if config.channel_type != _DEFAULT_CHANNEL:
            raise ValueError("Murf realtime audio requires MONO output.")
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.MURF,
                voice=config.voice,
                sample_rate=config.sample_rate,
                encoding="pcm_s16le",
            )
        )
        self._config = config
        self._ws: ClientConnection | None = None
        self._state = MurfStreamState.DISCONNECTED
        self._context_id: str | None = None
        self._audio: MurfAudioDecoder | None = None
        self._completion_error: TTSConnectionFailed | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._closing: dict[ClientConnection, asyncio.Task[None]] = {}

    def _build_ws_url(self) -> str:
        return MurfHandshake(
            api_key=self._config.api_key,
            sample_rate=self._config.sample_rate,
            channel_type=self._config.channel_type,
            format=self._config.format,
        ).url(_WS_URL)

    async def _initialize(self, connection: ClientConnection) -> None:
        voice = MurfInitialize(
            voice_config=MurfVoiceSettings(
                voiceId=self._config.voice_id,
                rate=self._config.rate,
                pitch=self._config.pitch,
                variation=self._config.variation,
                style=self._config.style,
            )
        )
        settings = MurfAdvancedSettings(
            min_buffer_size=self._config.min_buffer_size,
            max_buffer_delay_in_ms=self._config.max_buffer_delay_ms,
        )
        await connection.send(voice.model_dump_json(exclude_none=True))
        await connection.send(settings.model_dump_json())

    async def connect(self) -> Self:
        """Publish readiness only after both initialization messages succeed."""
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self
            connection: ClientConnection | None = None
            try:
                async with asyncio.timeout(_NATIVE_TIMEOUT_SECONDS):
                    connection = await websockets.connect(
                        self._build_ws_url(),
                        open_timeout=_NATIVE_TIMEOUT_SECONDS,
                        close_timeout=_NATIVE_TIMEOUT_SECONDS,
                        max_size=MAX_EVENT_BYTES,
                        max_queue=_RECEIVE_FRAME_LIMIT,
                    )
                    await self._initialize(connection)
            except asyncio.CancelledError:
                self._state = MurfStreamState.DISCONNECTED
                if connection is not None:
                    await self._close(connection)
                raise
            except Exception:
                self._state = MurfStreamState.FAILED
                self._completion_error = TTSConnectionFailed(
                    "Murf initialization failed."
                )
                if connection is not None:
                    await self._close(connection)
                raise self._completion_error from None
            self._ws = connection
            self._context_id = None
            self._audio = None
            self._completion_error = None
            self._state = MurfStreamState.READY
            return self

    def _start_close(self, connection: ClientConnection) -> asyncio.Task[None]:
        if existing := self._closing.get(connection):
            return existing
        task = asyncio.create_task(connection.close())
        self._closing[connection] = task
        task.add_done_callback(lambda done: self._closed(connection, done))
        return task

    def _closed(self, connection: ClientConnection, task: asyncio.Task[None]) -> None:
        self._closing.pop(connection, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Murf connection cleanup failed")

    async def _close(self, connection: ClientConnection) -> None:
        # websockets bounds close internally. Shield preserves its owner if the
        # caller is cancelled; the callback consumes the eventual outcome.
        try:
            await asyncio.shield(self._start_close(connection))
        except Exception:
            pass

    async def disconnect(self) -> None:
        """Detach before awaiting cleanup; old readers cannot affect a reconnect."""
        async with self._lifecycle_lock:
            self._state = MurfStreamState.DISCONNECTED
            self._context_id = None
            self._audio = None
            connection, self._ws = self._ws, None
            if connection is not None:
                await self._close(connection)
            for pending_close in tuple(self._closing.values()):
                try:
                    await asyncio.shield(pending_close)
                except Exception:
                    # The owning callback has already recorded cleanup failure.
                    pass

    async def _fail(
        self, connection: ClientConnection, error: TTSConnectionFailed
    ) -> None:
        if self._ws is connection:
            self._completion_error = error
            self._state = MurfStreamState.FAILED
            self._context_id = None
            self._audio = None
            self._ws = None
        await self._close(connection)

    async def _send(self, message: MurfText | MurfClear) -> None:
        connection = self._ws
        if connection is None:
            raise self._completion_error or TTSConnectionFailed(
                "Murf is not connected."
            )
        try:
            async with asyncio.timeout(_NATIVE_TIMEOUT_SECONDS):
                await connection.send(message.model_dump_json())
        except asyncio.CancelledError:
            await self._fail(connection, TTSConnectionFailed("Murf send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Murf send failed.")
            await self._fail(connection, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        """Keep a context open for all chunks until the platform flushes the turn."""
        if not text.strip():
            return
        async with self._lifecycle_lock:
            if not self.is_connected:
                raise self._completion_error or TTSConnectionFailed(
                    "Murf is not connected."
                )
            if self._state is MurfStreamState.DRAINING:
                raise TTSConnectionFailed("Murf previous turn is still draining.")
            if self._state in (MurfStreamState.READY, MurfStreamState.COMPLETE):
                self._context_id = str(uuid.uuid4())
                self._audio = MurfAudioDecoder(
                    format=self._config.format, sample_rate=self.sample_rate
                )
                self._state = MurfStreamState.STREAMING
            context_id = self._context_id
            if context_id is None:
                raise TTSConnectionFailed("Murf has no active context.")
            await self._send(MurfText(context_id=context_id, text=text, end=False))

    async def flush(self) -> None:
        """Send exactly one end marker; native final owns completion."""
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is not MurfStreamState.STREAMING:
                return
            context_id = self._context_id
            if context_id is None:
                raise TTSConnectionFailed("Murf has no active context.")
            self._state = MurfStreamState.DRAINING
            await self._send(MurfText(context_id=context_id, text="", end=True))

    async def receive_audio(self) -> bytes | None:
        """Validate/correlate before playback; poll cancellation loses no frame."""
        connection = self._ws
        if connection is None:
            if self._completion_error is not None:
                raise self._completion_error
            return None
        try:
            while self._ws is connection:
                raw = await connection.recv()
                if self._ws is not connection:
                    return None
                if not isinstance(raw, str):
                    raise MurfOutputError("Murf returned a non-JSON audio frame.")
                message = parse_output(raw)
                if (
                    message.context_id is not None
                    and message.context_id != self._context_id
                ):
                    continue
                if message.error is not None:
                    raise MurfOutputError("Murf rejected the synthesis request.")
                if self._context_id is None:
                    continue
                if message.context_id is None:
                    raise MurfOutputError("Murf omitted the synthesis context.")
                decoder = self._audio
                if decoder is None:
                    raise MurfOutputError("Murf has no active audio decoder.")
                if message.final is True:
                    if self._state is not MurfStreamState.DRAINING:
                        raise MurfOutputError("Murf finalized before input ended.")
                    decoder.finish()
                    self._state = MurfStreamState.COMPLETE
                    self._context_id = None
                    self._audio = None
                    return None
                audio = message.audio_bytes()
                if audio is not None:
                    pcm = decoder.feed(audio)
                    if pcm:
                        return pcm
            return None
        except asyncio.CancelledError:
            # websockets 15 recv is cancellation safe; the manager polls it.
            raise
        except Exception as native_error:
            if self._ws is not connection:
                return None
            error = (
                native_error
                if isinstance(native_error, MurfOutputError)
                else TTSConnectionFailed("Murf audio stream failed.")
            )
            await self._fail(connection, error)
            raise error from None

    async def handle_interruption(self) -> None:
        """Invalidate before clear; already synthesized old-context audio is ignored."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            context_id, self._context_id = self._context_id, None
            self._audio = None
            self._state = MurfStreamState.READY
            if context_id is not None:
                await self._send(MurfClear(context_id=context_id))

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
                error = TTSConnectionFailed("Murf keepalive failed.")
                await self._fail(connection, error)
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
        return TTSProvider.MURF.value

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._state not in (
            MurfStreamState.DISCONNECTED,
            MurfStreamState.FAILED,
        )

    @property
    def is_turn_complete(self) -> bool:
        return self._state is MurfStreamState.COMPLETE

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    @property
    def model(self) -> str:
        # This legacy adapter has no configured native model selector.
        return ""

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.UNSUPPORTED,
            native_interruption=TTSCapabilitySupport.UNSUPPORTED,
            aligned_transcript=TTSCapabilitySupport.UNSUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.SUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.UNSUPPORTED,
        )
