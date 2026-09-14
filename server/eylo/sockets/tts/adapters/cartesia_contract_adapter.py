"""Translate Cartesia's context-scoped wire protocol into the TTS audio contract."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect

from eylo.sockets.tts.adapters.cartesia_wire import (
    CartesiaAudioOutput,
    CartesiaCancelRequest,
    CartesiaContinuation,
    CartesiaDoneOutput,
    CartesiaErrorOutput,
    CartesiaGenerationConfig,
    CartesiaGenerationRequest,
    CartesiaInput,
    CartesiaInputError,
    CartesiaOutputError,
    CartesiaStreamState,
    CartesiaVoice,
    parse_envelope,
    parse_output,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionFailed
from eylo.sockets.tts.schemas import (
    RetryOptions,
    TTSAudioFormat,
    TTSCapabilities,
    TTSCapabilitySupport,
    TTSConfig,
    TTSProvider,
)

logger = logging.getLogger(__name__)

PROVIDER = TTSProvider.CARTESIA
CARTESIA_VERSION = "2025-04-16"
_STREAM_URL = "wss://api.cartesia.ai/tts/websocket"
_API_KEY_HEADER = "X-API-Key"


class CartesiaContractAdapter(TTSVendorAdapter):
    """Own a persistent WebSocket and a distinct context for every utterance."""

    def __init__(
        self,
        config: TTSConfig,
        retry_options: RetryOptions | None = None,
    ) -> None:
        self._input = CartesiaInput.from_config(config)
        super().__init__(config, retry_options)
        self._ws: ClientConnection | None = None
        self._state = CartesiaStreamState.DISCONNECTED
        self._context_id: str | None = None
        self._turn_complete = False
        self._completion_error: TTSConnectionFailed | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()

    @property
    def config(self) -> TTSConfig:
        return self._contract_config

    @property
    def provider(self) -> str:
        return PROVIDER.value

    @property
    def model(self) -> str:
        return self._input.model

    @property
    def sample_rate(self) -> int:
        return self._input.output_format.sample_rate

    @property
    def output_audio_format(self) -> TTSAudioFormat:
        return TTSAudioFormat.model_validate(self._input.output_format.model_dump())

    @property
    def capabilities(self) -> TTSCapabilities:
        """Native cancel stops queued work; local filtering stops late playback."""
        return TTSCapabilities(
            streaming=TTSCapabilitySupport.SUPPORTED,
            batch_synthesize=TTSCapabilitySupport.UNSUPPORTED,
            native_interruption=TTSCapabilitySupport.SUPPORTED,
            aligned_transcript=TTSCapabilitySupport.UNSUPPORTED,
            emotion_control=TTSCapabilitySupport.UNSUPPORTED,
            speed_control=TTSCapabilitySupport.SUPPORTED,
            voice_cloning=TTSCapabilitySupport.UNSUPPORTED,
            context_continuity=TTSCapabilitySupport.SUPPORTED,
        )

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    @property
    def is_turn_complete(self) -> bool:
        return self._turn_complete

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    def url(self) -> str:
        """Credentials go in headers, not a URL retained in transport errors."""
        return f"{_STREAM_URL}?{urlencode({'cartesia_version': CARTESIA_VERSION})}"

    def request(
        self,
        text: str,
        *,
        context_id: str,
        continuation: CartesiaContinuation,
    ) -> CartesiaGenerationRequest:
        speed = self._input.options.speed
        try:
            return CartesiaGenerationRequest(
                model_id=self._input.model,
                transcript=text,
                voice=CartesiaVoice(id=self._input.voice),
                output_format=self._input.output_format,
                context_id=context_id,
                continue_=continuation,
                language=self._input.language,
                generation_config=(
                    CartesiaGenerationConfig(speed=speed) if speed is not None else None
                ),
            )
        except ValidationError:
            raise CartesiaInputError("Invalid Cartesia synthesis input.") from None

    async def connect(self) -> ClientConnection:
        """Serialize acquisitions; native connect owns cleanup before it returns."""
        async with self._lifecycle_lock:
            if self._ws is not None:
                return self._ws
            try:
                ws = await connect(
                    self.url(),
                    additional_headers={_API_KEY_HEADER: self._input.options.api_key},
                    open_timeout=self._retry_options.timeout_seconds,
                    close_timeout=self._retry_options.timeout_seconds,
                )
            except asyncio.CancelledError:
                self._state = CartesiaStreamState.DISCONNECTED
                raise
            except Exception:
                error = TTSConnectionFailed("Cartesia connection failed.")
                self._completion_error = error
                self._state = CartesiaStreamState.FAILED
                raise error from None
            self._ws = ws
            self._context_id = None
            self._state = CartesiaStreamState.READY
            self._turn_complete = False
            self._completion_error = None
            logger.info("Cartesia TTS connected")
            return ws

    async def disconnect(self) -> None:
        """Detach before close; cancelled callers leave bounded close work owned."""
        async with self._lifecycle_lock:
            self._state = CartesiaStreamState.DISCONNECTED
            self._context_id = None
            ws, self._ws = self._ws, None
            if ws is not None:
                await self._close(ws)
            if self._closing_tasks:
                closing = asyncio.gather(*self._closing_tasks, return_exceptions=True)
                await asyncio.shield(closing)

    async def _close(self, ws: ClientConnection) -> None:
        # websockets bounds this handshake with close_timeout. Retain ownership
        # when the task awaiting it is cancelled during disconnect/failure.
        task = asyncio.create_task(ws.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closed)
        try:
            await asyncio.shield(task)
        except Exception:
            pass  # Callback consumes failure; preserve the original exception.

    def _closed(self, task: asyncio.Task[None]) -> None:
        self._closing_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Cartesia close failed")

    async def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._context_id = None
            self._state = CartesiaStreamState.FAILED
            self._turn_complete = False
            self._completion_error = error
        await self._close(ws)

    async def _send(
        self, message: CartesiaGenerationRequest | CartesiaCancelRequest
    ) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionFailed("Cartesia TTS is not connected.")
        try:
            await ws.send(message.model_dump_json(by_alias=True, exclude_none=True))
        except asyncio.CancelledError:
            await self._fail(ws, TTSConnectionFailed("Cartesia send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Cartesia send failed.")
            await self._fail(ws, error)
            raise error from None

    async def send_text(self, text: str) -> None:
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._ws is None:
                raise TTSConnectionFailed("Cartesia TTS is not connected.")
            if self._state is CartesiaStreamState.DRAINING:
                raise TTSConnectionFailed("Cartesia previous turn is still draining.")
            context_id = self._context_id or str(uuid4())
            message = self.request(
                text, context_id=context_id, continuation=CartesiaContinuation.CONTINUE
            )
            self._context_id = context_id
            self._turn_complete = False
            self._state = CartesiaStreamState.STREAMING
            await self._send(message)

    async def flush(self) -> None:
        """Eylo finalize means end-of-input, not Cartesia's nonterminal flush."""
        async with self._lifecycle_lock:
            if self._state is CartesiaStreamState.STREAMING and self._context_id:
                message = self.request(
                    "",
                    context_id=self._context_id,
                    continuation=CartesiaContinuation.FINALIZE,
                )
                self._state = CartesiaStreamState.DRAINING
                await self._send(message)

    async def keepalive(self) -> None:
        """Native WebSocket ping/pong owns keepalive; no synthetic speech input."""

    async def receive_audio(self) -> bytes | None:
        """Filter stale contexts before decoding or changing the active turn."""
        ws = self._ws
        if ws is None:
            if self._completion_error is not None:
                raise self._completion_error
            return None
        try:
            raw = await ws.recv()
            if self._ws is not ws:
                return None
            # No await after consumption: a polling timeout must not discard a
            # frame while waiting for a concurrent send's lifecycle lock.
            envelope = parse_envelope(raw)
            if (
                envelope.context_id is not None
                and envelope.context_id != self._context_id
            ):
                return None
            output = parse_output(raw)
            if isinstance(output, CartesiaErrorOutput):
                raise CartesiaOutputError("Cartesia rejected speech synthesis.")
            if isinstance(output, CartesiaDoneOutput):
                self._context_id = None
                self._turn_complete = True
                self._state = CartesiaStreamState.READY
            if isinstance(output, CartesiaAudioOutput):
                return output.audio_bytes()
            return None
        except CartesiaOutputError as error:
            await self._fail(ws, error)
            raise
        except Exception:
            if self._ws is not ws:
                return None
            error = TTSConnectionFailed("Cartesia receive failed.")
            await self._fail(ws, error)
            raise error from None
        # Cancelling recv is supported by websockets and used for polling. It
        # does not close the socket, retire the context or fabricate completion.

    async def handle_interruption(self) -> None:
        """Retire identity before sending cancel; discard any late vendor output."""
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            context_id, self._context_id = self._context_id, None
            self._state = CartesiaStreamState.READY
            self._turn_complete = True
            if context_id is not None:
                await self._send(CartesiaCancelRequest(context_id=context_id))
