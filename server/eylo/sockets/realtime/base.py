"""Abstract base for realtime vendor adapters.

Same pattern as STT/TTS vendors: Factory creates → Manager calls lifecycle methods.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eylo.common.contracts.tool_record import ToolRecord
from eylo.sockets.realtime.config import RealtimeSessionConfig
from eylo.sockets.realtime.events import RealtimeEvent


class RealtimeFeatureSupport(Enum):
    """Native adapter support, serialized as the existing capability booleans."""

    UNSUPPORTED = False
    SUPPORTED = True

    def __bool__(self) -> bool:
        raise TypeError("Compare realtime support with its explicit enum member.")


class RealtimeSessionUpdateMode(str, Enum):
    """How an adapter applies a validated session update."""

    IN_PLACE = "in_place"
    RECONNECT = "reconnect"
    UNSUPPORTED = "unsupported"


RealtimeSampleRate = Annotated[int, Field(strict=True, gt=0)]


class RealtimeCapabilities(BaseModel):
    """Native behavior exposed by one realtime adapter.

    These facts describe the adapter and vendor path only. They never decide
    whether Eylo-owned policies such as recording, silence handling, or call
    limits are available.
    """

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always"
    )

    full_duplex_audio: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    input_transcription: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    output_transcription: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    native_turn_detection: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    native_interruption: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    tool_calling: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    platform_message_speech: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    session_update_mode: RealtimeSessionUpdateMode = (
        RealtimeSessionUpdateMode.UNSUPPORTED
    )
    voice_selection: RealtimeFeatureSupport = RealtimeFeatureSupport.SUPPORTED
    session_resumption: RealtimeFeatureSupport = RealtimeFeatureSupport.UNSUPPORTED
    context_compression: RealtimeFeatureSupport = RealtimeFeatureSupport.UNSUPPORTED
    input_sample_rates: tuple[RealtimeSampleRate, ...] = (16000,)
    output_sample_rates: tuple[RealtimeSampleRate, ...] = (24000,)

    @field_validator(
        "full_duplex_audio",
        "input_transcription",
        "output_transcription",
        "native_turn_detection",
        "native_interruption",
        "tool_calling",
        "platform_message_speech",
        "voice_selection",
        "session_resumption",
        "context_compression",
        mode="before",
    )
    @classmethod
    def validate_support(cls, value: object) -> RealtimeFeatureSupport:
        if isinstance(value, RealtimeFeatureSupport):
            return value
        if value is True:
            return RealtimeFeatureSupport.SUPPORTED
        if value is False:
            return RealtimeFeatureSupport.UNSUPPORTED
        raise ValueError("Realtime support requires an explicit choice or boolean.")


class RealtimeAdapter(abc.ABC):
    """Single-session, single-connection realtime voice adapter.

    Lifecycle: __init__(config) → connect() → send_audio()/receive() → disconnect()
    """

    def __init__(self, config: RealtimeSessionConfig) -> None:
        self._config = RealtimeSessionConfig.model_validate(config)
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    @abc.abstractmethod
    def capabilities(self) -> RealtimeCapabilities:
        """Return native capabilities implemented by this adapter path."""

    @abc.abstractmethod
    async def connect(self) -> None:
        """Open vendor WebSocket and send session config."""

    @abc.abstractmethod
    async def verify_ready(self) -> None:
        """Prove the connected vendor accepted this session configuration.

        Verification must not require user audio or consume a conversational
        response. Providers with an explicit acknowledgement wait for it;
        providers whose SDK completes setup during ``connect`` validate that
        established session here.
        """

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close vendor WebSocket cleanly."""

    @abc.abstractmethod
    async def send_audio(self, audio_data: bytes) -> None:
        """Forward a PCM chunk from the browser to the vendor."""

    @abc.abstractmethod
    async def request_speech(self, text: str) -> None:
        """Ask the connected model to speak one platform-owned message.

        This is the normalized boundary used for greetings, recording
        disclosures, silence reminders, and terminal messages. Vendor adapters
        decide how to trigger one response; call policy stays in the pipeline.
        """

    @abc.abstractmethod
    def receive(self) -> AsyncIterator[RealtimeEvent]:
        """Yield normalized events from the vendor.

        The manager iterates: ``async for event in adapter.receive(): ...``
        Runs until disconnect() is called or the vendor closes.
        """

    @abc.abstractmethod
    async def send_tool_result(self, tool_call_id: str, result: str) -> None:
        """Return a tool execution result to the vendor."""

    @abc.abstractmethod
    async def update_session(
        self,
        *,
        system_prompt: str | None = None,
        tools: list[ToolRecord] | None = None,
        voice: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Update session config mid-stream (for agent handoffs).

        Gemini: requires reconnect. OpenAI: sends session.update event.
        """
