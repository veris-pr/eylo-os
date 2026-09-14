"""AssemblyAI STT - Real-time speech recognition with turn detection.

AssemblyAI provides industry-leading speech recognition with advanced
turn detection capabilities for natural conversation understanding.

Based on: livekit-plugins-assemblyai/livekit/plugins/assemblyai/stt.py
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from eylo.sockets.voice.audio import AudioByteStream
from eylo.sockets.voice.vendors.assemblyai.events import (
    AssemblyAIError,
    AssemblyAIEvent,
    AssemblyAITermination,
    parse_assemblyai_event,
)
from eylo.sockets.voice.vendors.assemblyai.requests import (
    AssemblyAIConnectionQuery,
    AssemblyAIControl,
    AssemblyAIControlKind,
)

DEFAULT_API_URL = "wss://streaming.assemblyai.com/v3/ws"
SAMPLE_RATE = 16000
_CLOSE_TIMEOUT_SECONDS = 5.0


class AssemblyAIEncoding(StrEnum):
    """The native audio chunker currently supports PCM16 only."""

    PCM_S16LE = "pcm_s16le"


class STTOptions(BaseModel):
    """Validated native snapshot; updates affect subsequently opened streams."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", hide_input_in_errors=True, allow_inf_nan=False
    )

    speech_model: str = Field(min_length=1)
    sample_rate: int = Field(strict=True, ge=8000, le=96000)
    encoding: AssemblyAIEncoding
    buffer_size_seconds: float = Field(strict=True, gt=0, le=1)
    end_of_turn_confidence_threshold: float = Field(strict=True, ge=0, le=1)
    min_end_of_turn_silence_when_confident: int = Field(strict=True, ge=0)
    max_turn_silence: int = Field(strict=True, gt=0)
    format_turns: StrictBool
    keyterms_prompt: tuple[str, ...] | None = Field(max_length=100)
    api_key: str = Field(min_length=1, repr=False, exclude=True)

    @model_validator(mode="after")
    def require_whole_sample_capacity(self) -> STTOptions:
        if round(self.sample_rate * self.buffer_size_seconds) < 1:
            raise ValueError("Audio buffer must hold at least one sample.")
        return self


class AssemblyAISTT:
    """AssemblyAI STT with turn detection."""

    def __init__(
        self,
        *,
        api_key: str,
        speech_model: str,
        sample_rate: int = SAMPLE_RATE,
        encoding: str = "pcm_s16le",
        end_of_turn_confidence_threshold: float = 0.6,
        min_end_of_turn_silence_when_confident: int = 500,
        max_turn_silence: int = 1500,
        format_turns: bool = True,
        keyterms_prompt: list[str] | None = None,
        buffer_size_seconds: float = 0.05,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._session = http_session
        self._owns_session = http_session is None
        self._api_key = api_key
        self._opts = STTOptions(
            speech_model=speech_model,
            sample_rate=sample_rate,
            encoding=encoding,
            buffer_size_seconds=buffer_size_seconds,
            end_of_turn_confidence_threshold=end_of_turn_confidence_threshold,
            min_end_of_turn_silence_when_confident=min_end_of_turn_silence_when_confident,
            max_turn_silence=max_turn_silence,
            format_turns=format_turns,
            keyterms_prompt=keyterms_prompt,
            api_key=api_key,
        )

    @property
    def model(self) -> str:
        """Get the STT model being used."""
        return self._opts.speech_model

    @property
    def provider(self) -> str:
        """Get the provider name."""
        return "AssemblyAI"

    @property
    def sample_rate(self) -> int:
        """Get the audio sample rate."""
        return self._opts.sample_rate

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    def stream(self) -> AssemblyAISTTStream:
        """Create a streaming STT session.

        Returns:
            AssemblyAISTTStream for real-time transcription with turn detection.

        """
        return AssemblyAISTTStream(
            opts=self._opts,
            api_key=self._api_key,
            http_session=self._ensure_session(),
        )

    def update_options(
        self,
        *,
        buffer_size_seconds: float | None = None,
        end_of_turn_confidence_threshold: float | None = None,
        min_end_of_turn_silence_when_confident: int | None = None,
        max_turn_silence: int | None = None,
    ) -> None:
        """Validate an atomic replacement for future streams, not a remote update."""
        current = self._opts
        self._opts = STTOptions(
            speech_model=current.speech_model,
            sample_rate=current.sample_rate,
            encoding=current.encoding,
            buffer_size_seconds=buffer_size_seconds
            if buffer_size_seconds is not None
            else current.buffer_size_seconds,
            end_of_turn_confidence_threshold=end_of_turn_confidence_threshold
            if end_of_turn_confidence_threshold is not None
            else current.end_of_turn_confidence_threshold,
            min_end_of_turn_silence_when_confident=min_end_of_turn_silence_when_confident
            if min_end_of_turn_silence_when_confident is not None
            else current.min_end_of_turn_silence_when_confident,
            max_turn_silence=max_turn_silence
            if max_turn_silence is not None
            else current.max_turn_silence,
            format_turns=current.format_turns,
            keyterms_prompt=current.keyterms_prompt,
            api_key=current.api_key,
        )

    async def aclose(self) -> None:
        """Close HTTP session if owned by this instance."""
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None


class AssemblyAISTTStream:
    """AssemblyAI WebSocket streaming STT session with turn detection."""

    _CLOSE_MSG = AssemblyAIControl(
        type=AssemblyAIControlKind.TERMINATE
    ).model_dump_json()

    def __init__(
        self,
        *,
        opts: STTOptions,
        api_key: str,
        http_session: aiohttp.ClientSession,
    ) -> None:
        self._opts = opts
        self._api_key = api_key
        self._session = http_session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closed = False
        self._terminated = asyncio.Event()
        self._termination_sent = False

        # Audio input queue
        self._input_queue: asyncio.Queue[bytes | AssemblyAIControl] = asyncio.Queue()

        # Transcription output queue
        self._output_queue: asyncio.Queue[AssemblyAIEvent | None] = asyncio.Queue()
        self._failure: Exception | None = None
        self._output_closed = False

        # Start background task
        self._task = asyncio.create_task(self._run_and_signal())

    async def push_audio(self, audio_data: bytes) -> None:
        """Push audio data for transcription.

        Args:
            audio_data: Raw audio bytes (PCM format).

        """
        if not self._closed:
            await self._input_queue.put(audio_data)

    async def flush(self) -> None:
        """Flush any pending audio and get final transcription."""
        if not self._closed:
            await self._input_queue.put(
                AssemblyAIControl(type=AssemblyAIControlKind.FORCE_ENDPOINT)
            )

    def __aiter__(self) -> AssemblyAISTTStream:
        """Async iterator for transcription events."""
        return self

    async def __anext__(self) -> AssemblyAIEvent:
        """Return a validated native event; reader failures never masquerade as EOF."""
        if self._output_closed and self._output_queue.empty():
            if self._failure is not None:
                raise self._failure
            raise StopAsyncIteration
        event = await self._output_queue.get()
        self._output_queue.task_done()
        if event is None:
            if self._failure is not None:
                raise self._failure
            raise StopAsyncIteration
        return event

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        """Connect to AssemblyAI V3 WebSocket."""
        # Build configuration per V3 API spec
        live_config = AssemblyAIConnectionQuery(
            speech_model=self._opts.speech_model,
            sample_rate=self._opts.sample_rate,
            encoding=self._opts.encoding.value,
            end_of_turn_confidence_threshold=self._opts.end_of_turn_confidence_threshold,
            min_turn_silence=self._opts.min_end_of_turn_silence_when_confident,
            max_turn_silence=self._opts.max_turn_silence,
            format_turns=self._opts.format_turns,
            keyterms_prompt=self._opts.keyterms_prompt,
        )

        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
            "User-Agent": "AssemblyAI/1.0 (integration=Eylo)",
        }

        url = f"{DEFAULT_API_URL}?{live_config.query_string()}"

        try:
            ws = await self._session.ws_connect(url, headers=headers)
            return ws
        except Exception as error:
            raise RuntimeError("Failed to connect to AssemblyAI.") from error

    async def _run_and_signal(self) -> None:
        """Every reader exit wakes iteration, including failure and cancellation."""
        try:
            await self._run()
        except Exception as error:
            self._failure = error
        finally:
            self._finish_output()

    def _finish_output(self) -> None:
        """Wake readers once, including cancellation before the worker's first step."""
        if not self._output_closed:
            self._output_closed = True
            self._output_queue.put_nowait(None)

    async def _run(self) -> None:
        """One native connection; the platform runtime owns retry decisions."""

        async def send_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            """Send audio to AssemblyAI."""
            # Calculate samples per buffer
            samples_per_buffer = round(
                self._opts.sample_rate * self._opts.buffer_size_seconds
            )

            audio_bstream = AudioByteStream(
                sample_rate=self._opts.sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_buffer,
            )

            while True:
                data = await self._input_queue.get()

                if isinstance(data, AssemblyAIControl):
                    chunks = audio_bstream.flush()
                    for chunk in chunks:
                        await ws.send_bytes(chunk.data)
                    await ws.send_str(data.model_dump_json())
                    if data.type is AssemblyAIControlKind.TERMINATE:
                        self._termination_sent = True
                        await self._terminated.wait()
                        return
                    continue

                # Buffer data and get chunks
                chunks = audio_bstream.write(data)
                for chunk in chunks:
                    await ws.send_bytes(chunk.data)

        async def recv_task(ws: aiohttp.ClientWebSocketResponse) -> None:
            """Receive transcriptions from AssemblyAI."""
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5)
                except asyncio.TimeoutError:
                    if self._closed:
                        break
                    continue

                if msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                ):
                    if self._closed:
                        return
                    raise RuntimeError("AssemblyAI connection closed unexpectedly")

                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue

                event = parse_assemblyai_event(msg.data)
                if event is None:
                    continue
                await self._output_queue.put(event)
                if isinstance(event, (AssemblyAITermination, AssemblyAIError)):
                    self._terminated.set()
                    return

        # Recovery belongs to the owning STT runtime, not this native connection.
        while not self._closed:
            ws = None
            try:
                ws = await self._connect_ws()
                self._ws = ws

                # Start tasks
                tasks = [
                    asyncio.create_task(send_task(ws)),
                    asyncio.create_task(recv_task(ws)),
                ]

                try:
                    done, _ = await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    # Check for exceptions
                    for task in done:
                        task.result()  # Raise exception if any
                    break
                finally:
                    # Cancel all tasks
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as error:
                # The owning STT runtime decides recovery. Retrying malformed
                # frames or rejected credentials here hides the real failure.
                self._failure = error
                break
            finally:
                if ws and not ws.closed:
                    try:
                        if not self._termination_sent and not self._terminated.is_set():
                            async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                                await ws.send_str(self._CLOSE_MSG)
                                self._termination_sent = True
                    except Exception as error:
                        if self._failure is None:
                            self._failure = error
                    finally:
                        try:
                            async with asyncio.timeout(_CLOSE_TIMEOUT_SECONDS):
                                await ws.close()
                        except Exception as error:
                            if self._failure is None:
                                self._failure = error

    async def aclose(self) -> None:
        """Bounded graceful termination retains final native frames; always join tasks."""
        if self._closed:
            await asyncio.gather(self._task, return_exceptions=True)
            return
        self._closed = True
        try:
            if self._ws is not None and not self._task.done():
                await self._input_queue.put(
                    AssemblyAIControl(type=AssemblyAIControlKind.TERMINATE)
                )
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._task), _CLOSE_TIMEOUT_SECONDS
                    )
                except TimeoutError:
                    pass
        finally:
            if not self._task.done():
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._finish_output()
