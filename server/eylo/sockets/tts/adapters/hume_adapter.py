"""Own Hume TTS stream input, validated PCM output and per-turn teardown."""

from __future__ import annotations

import asyncio
import logging
from typing import Self
from urllib.parse import urlencode

from pydantic import Field, StrictFloat, StrictInt, model_validator
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed
from websockets.frames import CloseCode

from eylo.common.contracts.speech_runtime import (
    SpeechOption,
    SpeechOptionState,
    SpeechText,
)
from eylo.sockets.tts.adapters.config import TTSAdapterConfig
from eylo.sockets.tts.adapters.hume_wire import (
    HUME_API_KEY_HEADER,
    HUME_PCM_ENCODING,
    HUME_SAMPLE_RATE,
    HUME_STREAM_URL,
    HumeAudioOutput,
    HumeEndInput,
    HumeOutputError,
    HumeStreamState,
    HumeText,
    HumeVersion,
    HumeVoice,
    parse_output,
    version_for_model,
)
from eylo.sockets.tts.base import TTSVendorAdapter
from eylo.sockets.tts.exceptions import TTSConnectionClosed, TTSConnectionFailed
from eylo.sockets.tts.schemas import TTSCapabilities, TTSConfig, TTSProvider

logger = logging.getLogger(__name__)
_DEFAULT_SPEED = 1.0
_DEFAULT_FORMAT = "pcm"
# Bound tracking even if a peer never terminates the snippets it announces.
_MAX_PENDING_SNIPPETS = 1024


class HumeTTSConfig(TTSAdapterConfig):
    """Native settings; language/rate are legacy inputs, not Hume wire options.

    The native endpoint has no language/rate selector and emits fixed 48 kHz
    PCM. Consumers must use output_audio_format for any transport conversion.
    """

    provider = TTSProvider.HUME
    model: SpeechText
    voice: SpeechText | None = None
    voice_description: SpeechText | None = None
    language: SpeechText
    speed: StrictFloat = Field(default=_DEFAULT_SPEED, gt=0)
    format: SpeechText = _DEFAULT_FORMAT
    sample_rate: StrictInt = Field(default=HUME_SAMPLE_RATE, gt=0)
    instant_mode: SpeechOption = SpeechOptionState.ENABLED

    @model_validator(mode="after")
    def require_supported_input(self) -> Self:
        version = version_for_model(self.model)
        if self.voice is None:
            if self.voice_description is None:
                raise ValueError("Hume TTS requires a voice or voice description.")
            if version is HumeVersion.OCTAVE_2:
                raise ValueError("Hume Octave 2 requires a saved voice.")
            if self.instant_mode is SpeechOptionState.ENABLED:
                raise ValueError("Hume voice design requires instant mode disabled.")
        if self.format.lower() != _DEFAULT_FORMAT:
            raise ValueError("Hume TTS must emit PCM for realtime voice.")
        return self


class HumeTTSAdapter(TTSVendorAdapter):
    """One native socket per turn; only drained end-input completes synthesis.

    No background receiver or lossy audio queue. Poll cancellation leaves recv
    intact; interruption detaches the old socket before waiting for its close.
    """

    def __init__(self, config: HumeTTSConfig) -> None:
        config = HumeTTSConfig.model_validate(config)
        self._config = config
        super().__init__(
            TTSConfig(
                vendor=TTSProvider.HUME,
                model=config.model,
                voice=config.voice,
                sample_rate=HUME_SAMPLE_RATE,
                encoding=HUME_PCM_ENCODING,
            )
        )
        self._ws: ClientConnection | None = None
        self._state = HumeStreamState.DISCONNECTED
        self._stream_available = asyncio.Event()
        self._lifecycle_lock = asyncio.Lock()
        self._closing_tasks: set[asyncio.Task[None]] = set()
        self._turn_complete = False
        self._completion_error: TTSConnectionFailed | None = None
        self._unfinished_snippets: set[tuple[str, str]] = set()
        self._received_audio = False

    def _build_ws_url(self) -> str:
        # The SDK supports header authentication; credentials never enter URLs.
        params = {
            "version": version_for_model(self._config.model).value,
            "format_type": _DEFAULT_FORMAT,
            "no_binary": "true",
            "strip_headers": "true",
            "instant_mode": (
                "true"
                if self._config.instant_mode is SpeechOptionState.ENABLED
                else "false"
            ),
        }
        return f"{HUME_STREAM_URL}?{urlencode(params)}"

    async def connect(self) -> Self:
        async with self._lifecycle_lock:
            if self._ws is None:
                await self._open_stream()
            return self

    async def _open_stream(self) -> None:
        """Acquire under the lifecycle lock; no await after taking ownership."""
        try:
            ws = await connect(
                self._build_ws_url(),
                additional_headers={HUME_API_KEY_HEADER: self._config.api_key},
                open_timeout=self._retry_options.timeout_seconds,
                close_timeout=self._retry_options.timeout_seconds,
            )
        except asyncio.CancelledError:
            self._state = HumeStreamState.DISCONNECTED
            self._stream_available.set()
            raise
        except Exception:
            self._state = HumeStreamState.FAILED
            self._completion_error = TTSConnectionFailed("Hume connection failed.")
            self._stream_available.set()
            raise self._completion_error from None
        self._ws = ws
        self._state = HumeStreamState.READY
        self._completion_error = None
        self._turn_complete = False
        self._received_audio = False
        self._unfinished_snippets.clear()
        self._stream_available.set()

    async def send_text(self, text: str) -> None:
        if isinstance(text, str) and not text.strip():
            return
        message = HumeText(
            text=text,
            speed=self._config.speed,
            voice=HumeVoice(name=self._config.voice) if self._config.voice else None,
            description=self._config.voice_description,
        )
        async with self._lifecycle_lock:
            if self._completion_error is not None:
                raise self._completion_error
            if self._state is HumeStreamState.DISCONNECTED:
                raise TTSConnectionClosed("Hume TTS is not connected.")
            if self._state is HumeStreamState.DRAINING:
                raise TTSConnectionFailed("Hume previous turn is still draining.")
            if self._ws is None:
                await self._open_stream()
            self._state = HumeStreamState.STREAMING
            self._turn_complete = False
            await self._send(message)

    async def _send(self, message: HumeText | HumeEndInput) -> None:
        ws = self._ws
        if ws is None:
            raise TTSConnectionClosed("Hume TTS is not connected.")
        try:
            await ws.send(message.model_dump_json(exclude_none=True))
        except asyncio.CancelledError:
            self._fail(ws, TTSConnectionFailed("Hume send cancelled."))
            raise
        except Exception:
            error = TTSConnectionFailed("Hume send failed.")
            self._fail(ws, error)
            raise error from None

    async def flush(self) -> None:
        """Hume close forces buffered synthesis and closes after draining it."""
        async with self._lifecycle_lock:
            if self._state is HumeStreamState.STREAMING:
                self._state = HumeStreamState.DRAINING
                await self._send(HumeEndInput())

    async def receive_audio(self) -> bytes | None:
        if self._state is HumeStreamState.DISCONNECTED:
            return None
        await self._stream_available.wait()
        ws = self._ws
        if ws is None:
            if self._completion_error is not None:
                raise self._completion_error
            return None
        try:
            raw = await ws.recv()
            if self._ws is not ws:
                return None
            if not isinstance(raw, str):
                raise HumeOutputError("Unexpected Hume binary output.")
            output = parse_output(raw)
            if not isinstance(output, HumeAudioOutput):
                return None
            if self._state not in (HumeStreamState.STREAMING, HumeStreamState.DRAINING):
                raise HumeOutputError("Unexpected Hume audio before input.")
            audio = output.audio_bytes()
            identity = (output.request_id, output.snippet_id)
            if output.is_last_chunk:
                self._unfinished_snippets.discard(identity)
            else:
                self._unfinished_snippets.add(identity)
                if len(self._unfinished_snippets) > _MAX_PENDING_SNIPPETS:
                    raise HumeOutputError("Hume pending snippet limit exceeded.")
            self._received_audio = self._received_audio or bool(audio)
            return audio or None
        except ConnectionClosed as error:
            if self._ws is not ws:
                return None
            if (
                error.rcvd is not None
                and error.rcvd.code == CloseCode.NORMAL_CLOSURE
                and self._state is HumeStreamState.DRAINING
                and self._received_audio
                and not self._unfinished_snippets
            ):
                self._ws = None
                self._state = HumeStreamState.READY
                self._turn_complete = True
                self._stream_available.clear()
                self._start_close(ws)
                return None
            failure = HumeOutputError("Hume stream ended before completion.")
            self._fail(ws, failure)
            raise failure from None
        except HumeOutputError as error:
            self._fail(ws, error)
            raise
        except Exception:
            if self._ws is not ws:
                return None
            failure = HumeOutputError("Hume receive failed.")
            self._fail(ws, failure)
            raise failure from None
        # No await between recv and classification: polling cancellation cannot
        # consume and silently discard a frame, or retire a healthy stream.

    def _fail(self, ws: ClientConnection, error: TTSConnectionFailed) -> None:
        if self._ws is ws:
            self._ws = None
            self._state = HumeStreamState.FAILED
            self._completion_error = error
            self._turn_complete = False
            self._stream_available.set()
        self._start_close(ws)

    def _start_close(self, ws: ClientConnection) -> asyncio.Task[None]:
        task = asyncio.create_task(ws.close())
        self._closing_tasks.add(task)
        task.add_done_callback(self._closed)
        return task

    def _closed(self, task: asyncio.Task[None]) -> None:
        self._closing_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("Hume close failed")

    async def _close(self, ws: ClientConnection) -> None:
        try:
            await asyncio.shield(self._start_close(ws))
        except Exception:
            # Callback retrieves the error; cleanup must not mask the cause.
            pass

    async def handle_interruption(self) -> None:
        async with self._lifecycle_lock:
            if not self.is_connected:
                return
            ws, self._ws = self._ws, None
            self._state = HumeStreamState.READY
            self._turn_complete = True
            self._stream_available.clear()
            self._unfinished_snippets.clear()
            if ws is not None:
                await self._close(ws)

    async def disconnect(self) -> None:
        async with self._lifecycle_lock:
            ws, self._ws = self._ws, None
            self._state = HumeStreamState.DISCONNECTED
            self._stream_available.set()
            if ws is not None:
                await self._close(ws)
            if self._closing_tasks:
                closing = asyncio.gather(
                    *self._closing_tasks,
                    return_exceptions=True,
                )
                await asyncio.shield(closing)

    async def keepalive(self) -> None:
        async with self._lifecycle_lock:
            ws = self._ws
            if ws is not None and self._state in (
                HumeStreamState.READY,
                HumeStreamState.STREAMING,
            ):
                try:
                    await ws.ping()
                except Exception:
                    error = TTSConnectionFailed("Hume keepalive failed.")
                    self._fail(ws, error)
                    raise error from None

    @property
    def sample_rate(self) -> int:
        return HUME_SAMPLE_RATE

    @property
    def provider(self) -> str:
        return TTSProvider.HUME.value

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def is_connected(self) -> bool:
        return self._state not in (HumeStreamState.DISCONNECTED, HumeStreamState.FAILED)

    @property
    def is_turn_complete(self) -> bool:
        return self._turn_complete

    @property
    def turn_completion_error(self) -> TTSConnectionFailed | None:
        return self._completion_error

    @property
    def capabilities(self) -> TTSCapabilities:
        return TTSCapabilities(
            streaming=True,
            batch_synthesize=False,
            native_interruption=False,
            aligned_transcript=False,
            emotion_control=True,
            speed_control=True,
            voice_cloning=False,
            context_continuity=False,
            sample_rates=(HUME_SAMPLE_RATE,),
        )
