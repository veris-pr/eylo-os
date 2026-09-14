"""Sarvam adapter for the canonical STT socket contract."""

import asyncio
import base64
import logging
from collections.abc import Mapping
from enum import Enum, IntEnum, StrEnum
from typing import Self
from urllib.parse import urlencode

import websockets
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_serializer,
    model_validator,
)
from sarvamai.types import AudioData, AudioMessage, SttFlushSignal

from eylo.common.contracts.speech_runtime import SpeechOption, SpeechOptionState
from eylo.common.contracts.voice import InterruptionType
from eylo.sockets.stt.adapters.connection_errors import raise_websocket_connection_error
from eylo.sockets.stt.adapters.sarvam_events import (
    sarvam_speech_started_event,
    sarvam_transcript_event,
)
from eylo.sockets.stt.adapters.sarvam_wire import (
    SarvamErrorEvent,
    SarvamSTTEvent,
    SarvamSignalType,
    SarvamTranscript,
    parse_sarvam_stt_event,
)
from eylo.sockets.stt.base import STTVendorAdapter
from eylo.sockets.stt.exceptions import (
    STTConnectionCleanupFailed,
    STTConnectionClosed,
    STTConnectionFailureKind,
    STTConnectionRetryUnsafe,
)
from eylo.sockets.stt.schemas import (
    STTCapabilities,
    STTCapabilitySupport,
    STTEvent,
    STTProvider,
)

logger = logging.getLogger(__name__)

_SARVAM_STT_WS_URL = "wss://api.sarvam.ai/speech-to-text/ws"
_KEEPALIVE_SILENCE_SECONDS = 0.1
_CLOSE_TIMEOUT_SECONDS = 10.0
_CLEANUP_WAIT_SECONDS = 12.0


class SarvamSTTModel(str, Enum):
    SAARAS_V3 = "saaras:v3"
    SAARIKA_V2_5 = "saarika:v2.5"


class SarvamSTTMode(str, Enum):
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    VERBATIM = "verbatim"
    TRANSLIT = "translit"
    CODEMIX = "codemix"


class SarvamInputAudioCodec(str, Enum):
    WAV = "wav"
    PCM_S16LE = "pcm_s16le"
    PCM_L16 = "pcm_l16"
    PCM_RAW = "pcm_raw"


class SarvamSourceEncoding(StrEnum):
    """Consumed transport encodings, including existing direct-adapter aliases."""

    LINEAR16 = "linear16"
    PCM_S16LE = "pcm_s16le"
    L16 = "l16"
    PCM_L16 = "pcm_l16"
    PCM_RAW = "pcm_raw"
    WAV = "wav"
    AUDIO_WAV = "audio/wav"
    MULAW = "mulaw"
    PCM_MULAW = "pcm_mulaw"
    ULAW = "ulaw"
    PCM_ULAW = "pcm_ulaw"


class SarvamSampleRate(IntEnum):
    HZ_8000 = 8000
    HZ_16000 = 16000


_MULAW_ENCODINGS = {
    SarvamSourceEncoding.MULAW,
    SarvamSourceEncoding.PCM_MULAW,
    SarvamSourceEncoding.ULAW,
    SarvamSourceEncoding.PCM_ULAW,
}
_ENCODING_TO_CODEC = {
    SarvamSourceEncoding.AUDIO_WAV: SarvamInputAudioCodec.WAV,
    SarvamSourceEncoding.WAV: SarvamInputAudioCodec.WAV,
    SarvamSourceEncoding.LINEAR16: SarvamInputAudioCodec.PCM_S16LE,
    SarvamSourceEncoding.PCM_S16LE: SarvamInputAudioCodec.PCM_S16LE,
    SarvamSourceEncoding.L16: SarvamInputAudioCodec.PCM_L16,
    SarvamSourceEncoding.PCM_L16: SarvamInputAudioCodec.PCM_L16,
    SarvamSourceEncoding.PCM_RAW: SarvamInputAudioCodec.PCM_RAW,
    **{encoding: SarvamInputAudioCodec.PCM_S16LE for encoding in _MULAW_ENCODINGS},
}
_PCM_SAMPLE_BYTES = 2
_MULAW_BYTE_MASK = 0xFF
_MULAW_MANTISSA_MASK = 0x0F
_MULAW_EXPONENT_MASK = 0x70
_MULAW_SIGN_MASK = 0x80
_MULAW_BIAS = 0x84
_MULAW_MANTISSA_SHIFT = 3
_MULAW_EXPONENT_SHIFT = 4


def _decode_mulaw_to_pcm_s16le(audio_data: bytes) -> bytes:
    pcm_data = bytearray(len(audio_data) * _PCM_SAMPLE_BYTES)

    for index, byte in enumerate(audio_data):
        mu_law = (~byte) & _MULAW_BYTE_MASK
        magnitude = (
            (mu_law & _MULAW_MANTISSA_MASK) << _MULAW_MANTISSA_SHIFT
        ) + _MULAW_BIAS
        magnitude <<= (mu_law & _MULAW_EXPONENT_MASK) >> _MULAW_EXPONENT_SHIFT
        sample = (
            _MULAW_BIAS - magnitude
            if mu_law & _MULAW_SIGN_MASK
            else magnitude - _MULAW_BIAS
        )

        offset = index * _PCM_SAMPLE_BYTES
        pcm_data[offset : offset + _PCM_SAMPLE_BYTES] = int(sample).to_bytes(
            _PCM_SAMPLE_BYTES, byteorder="little", signed=True
        )

    return bytes(pcm_data)


class SarvamSTTConfig(BaseModel):
    """Frozen resolved input; aliases normalize before vendor protocol validation."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        hide_input_in_errors=True,
        revalidate_instances="always",
    )
    api_key: SecretStr = Field(min_length=1, exclude=True, repr=False)
    model: SarvamSTTModel
    language_code: str = Field(strict=True, min_length=1, pattern=r"\S")
    mode: SarvamSTTMode = SarvamSTTMode.TRANSCRIBE
    sample_rate: int = Field(default=SarvamSampleRate.HZ_16000, strict=True)
    input_audio_codec: SarvamInputAudioCodec = SarvamInputAudioCodec.PCM_S16LE
    high_vad_sensitivity: SpeechOption = SpeechOptionState.ENABLED
    vad_signals: SpeechOption = SpeechOptionState.ENABLED
    flush_signal: SpeechOption = SpeechOptionState.ENABLED
    interruption_type: InterruptionType = InterruptionType.VAD
    source_encoding: SarvamSourceEncoding = SarvamSourceEncoding.LINEAR16

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data

        normalized: dict[str, object] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                raise ValueError("Sarvam config keys must be strings.")
            normalized[key] = value

        if "language" in normalized and "language_code" not in normalized:
            normalized["language_code"] = normalized["language"]
        if "encoding" in normalized and "source_encoding" not in normalized:
            normalized["source_encoding"] = normalized["encoding"]
        for key in ("source_encoding", "input_audio_codec"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized[key] = value.lower()

        if "input_audio_codec" not in normalized:
            source_encoding = normalized.get(
                "source_encoding", SarvamSourceEncoding.LINEAR16
            )
            if not isinstance(source_encoding, str):
                raise ValueError("Sarvam source encoding must be a named encoding.")
            normalized["input_audio_codec"] = _ENCODING_TO_CODEC[
                SarvamSourceEncoding(source_encoding)
            ]

        return normalized

    @model_validator(mode="after")
    def validate_config(self) -> Self:
        SarvamSampleRate(self.sample_rate)
        return self


class _SarvamSpeechState(StrEnum):
    IDLE = "idle"
    SPEAKING = "speaking"


class _SarvamSTTQuery(BaseModel):
    """Serialize only supported connection fields; credentials stay in headers."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    language_code: str = Field(serialization_alias="language-code")
    model: SarvamSTTModel
    mode: SarvamSTTMode
    sample_rate: SarvamSampleRate
    input_audio_codec: SarvamInputAudioCodec
    high_vad_sensitivity: SpeechOption
    vad_signals: SpeechOption
    flush_signal: SpeechOption

    @field_serializer("high_vad_sensitivity", "vad_signals", "flush_signal")
    def query_flag(self, value: SpeechOptionState) -> str:
        return str(value.value).lower()


class SarvamSTT(STTVendorAdapter):
    """Own one native stream; only the factory may retry establishment."""

    def __init__(self, config: SarvamSTTConfig) -> None:
        super().__init__()
        self._config = SarvamSTTConfig.model_validate(config)
        self._ws: websockets.ClientConnection | None = None
        self._speech_state = _SarvamSpeechState.IDLE
        self._lifecycle_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._stream_failure: STTConnectionRetryUnsafe | None = None

    @property
    def is_connected(self) -> bool:
        if not self._ws:
            return False
        return self._ws.state == websockets.protocol.State.OPEN

    def _get_ws_url(self) -> str:
        query = _SarvamSTTQuery(
            flush_signal=self._config.flush_signal,
            high_vad_sensitivity=self._config.high_vad_sensitivity,
            input_audio_codec=self._config.input_audio_codec,
            language_code=self._config.language_code,
            mode=self._config.mode,
            model=self._config.model,
            sample_rate=SarvamSampleRate(self._config.sample_rate),
            vad_signals=self._config.vad_signals,
        )
        params = query.model_dump(mode="json", by_alias=True)
        return f"{_SARVAM_STT_WS_URL}?{urlencode(params)}"

    def _prepare_audio(self, audio_data: bytes) -> bytes:
        if self._config.source_encoding in _MULAW_ENCODINGS:
            return _decode_mulaw_to_pcm_s16le(audio_data)
        return audio_data

    def _build_audio_message(self, audio_data: bytes) -> str:
        encoded_audio = base64.b64encode(audio_data).decode("utf-8")
        return AudioMessage(
            audio=AudioData(
                data=encoded_audio,
                encoding="audio/wav",
                sample_rate=self._config.sample_rate,
            )
        ).model_dump_json()

    def _build_keepalive_chunk(self) -> bytes:
        samples = max(1, int(self._config.sample_rate * _KEEPALIVE_SILENCE_SECONDS))
        if self._config.source_encoding in _MULAW_ENCODINGS:
            return b"\xff" * samples
        return b"\x00\x00" * samples

    async def connect(self) -> websockets.ClientConnection:
        async with self._lifecycle_lock:
            if self._close_task is not None:
                await self._await_close()
            if self._stream_failure is not None:
                raise self._stream_failure
            if self._ws is not None:
                if self.is_connected:
                    return self._ws
                raise STTConnectionRetryUnsafe(
                    "Sarvam's previous stream ended; implicit replacement is refused."
                )
            self._close_task = None
            try:
                self._ws = await websockets.connect(
                    self._get_ws_url(),
                    additional_headers={
                        "api-subscription-key": self._config.api_key.get_secret_value(),
                    },
                    ping_interval=None,
                    close_timeout=_CLOSE_TIMEOUT_SECONDS,
                )
                logger.info("Connected to Sarvam STT service")
                return self._ws
            except Exception as error:
                logger.error(
                    "Sarvam STT connection failed error_type=%s",
                    type(error).__name__,
                )
                raise_websocket_connection_error(error)

    async def disconnect(self) -> None:
        """Retain failed/in-progress cleanup; cancelling a caller cannot abandon it."""
        async with self._lifecycle_lock:
            if self._close_task is None:
                self._close_task = asyncio.create_task(self._close())
                self._close_task.add_done_callback(self._observe_close)
            await self._await_close()

    @staticmethod
    def _observe_close(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _await_close(self) -> None:
        task = self._close_task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), _CLEANUP_WAIT_SECONDS)
        except TimeoutError:
            raise STTConnectionCleanupFailed(
                "Sarvam STT cleanup is still pending; replacement is refused."
            ) from None

    async def _close(self) -> None:
        socket = self._ws
        if socket is not None:
            try:
                await socket.close()
                await socket.wait_closed()
            except Exception:
                raise STTConnectionCleanupFailed(
                    "Sarvam STT cleanup failed; the connection remains owned."
                ) from None
        self._ws = None
        self._speech_state = _SarvamSpeechState.IDLE

    async def keepalive(self) -> None:
        if not self.is_connected:
            return
        await self.send_audio(self._build_keepalive_chunk())

    async def _receive(self) -> str | None:
        if self._stream_failure is not None:
            raise self._stream_failure
        if not self._ws:
            return None

        try:
            return await self._ws.recv(decode=True)
        except websockets.ConnectionClosed:
            if self._close_task is not None:
                raise STTConnectionClosed("Sarvam STT was closed locally.") from None
            self._stream_failure = STTConnectionRetryUnsafe(
                "Sarvam STT ended without confirmed final delivery.",
                kind=STTConnectionFailureKind.NETWORK,
            )
            raise self._stream_failure from None

    async def _send_flush(self) -> None:
        if (
            not self._ws
            or not self.is_connected
            or self._config.flush_signal is SpeechOptionState.DISABLED
        ):
            return
        await self._send(SttFlushSignal().model_dump_json())

    async def _receive_raw_event(self) -> SarvamSTTEvent | None:
        payload = await self._receive()
        if payload is None:
            return None
        try:
            return parse_sarvam_stt_event(payload)
        except ValidationError:
            self._stream_failure = STTConnectionRetryUnsafe(
                "Sarvam returned an invalid STT event.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
            raise self._stream_failure from None

    async def send_audio(self, audio_data: bytes) -> None:
        prepared_audio = self._prepare_audio(audio_data)
        await self._send(self._build_audio_message(prepared_audio))

    async def _send(self, message: str) -> None:
        async with self._send_lock:
            if self._stream_failure is not None:
                raise self._stream_failure
            if self._close_task is not None or not self._ws or not self.is_connected:
                raise STTConnectionRetryUnsafe("Sarvam STT is not accepting input.")
            try:
                await self._ws.send(message)
            except asyncio.CancelledError:
                self._stream_failure = STTConnectionRetryUnsafe(
                    "Sarvam STT input delivery was interrupted and is uncertain."
                )
                raise
            except Exception:
                self._stream_failure = STTConnectionRetryUnsafe(
                    "Sarvam STT input delivery failed and is uncertain."
                )
                raise self._stream_failure from None

    async def receive_event(self, timeout_ms: int = 100) -> STTEvent | None:
        """Keep native identity and metrics; failed responses are not empty speech."""
        native = await self._receive_raw_event()
        if native is None:
            return None
        if isinstance(native, SarvamErrorEvent):
            self._stream_failure = STTConnectionRetryUnsafe(
                "Sarvam reported an STT failure.",
                kind=STTConnectionFailureKind.PROTOCOL,
            )
            raise self._stream_failure from None
        if isinstance(native, SarvamTranscript):
            self._speech_state = _SarvamSpeechState.IDLE
            return sarvam_transcript_event(native, model=self.model)
        if native.data.signal_type is SarvamSignalType.START_SPEECH:
            if self._speech_state is not _SarvamSpeechState.SPEAKING:
                self._speech_state = _SarvamSpeechState.SPEAKING
                return sarvam_speech_started_event(native, model=self.model)
            return None
        self._speech_state = _SarvamSpeechState.IDLE
        await self._send_flush()
        return None

    async def flush(self) -> None:
        """Request a final result when enabled; this API has no flush-complete ack."""
        await self._send_flush()

    @property
    def provider(self) -> str:
        return STTProvider.SARVAM.value

    @property
    def model(self) -> str:
        return self._config.model.value

    @property
    def sample_rate(self) -> int:
        return self._config.sample_rate

    @property
    def capabilities(self) -> STTCapabilities:
        """The configured legacy endpoint emits finals, not realtime partials."""
        return STTCapabilities(
            streaming=STTCapabilitySupport.SUPPORTED,
            batch_recognize=STTCapabilitySupport.UNSUPPORTED,
            interim_results=STTCapabilitySupport.UNSUPPORTED,
            vad_events=STTCapabilitySupport.SUPPORTED,
            turn_detection=STTCapabilitySupport.UNSUPPORTED,
            word_timestamps=STTCapabilitySupport.UNSUPPORTED,
            speaker_labels=STTCapabilitySupport.UNSUPPORTED,
            language_detection=STTCapabilitySupport.UNSUPPORTED,
        )
