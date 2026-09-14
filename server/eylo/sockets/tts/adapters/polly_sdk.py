"""Narrow Polly's generated client and own each streaming response body."""

import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Protocol, runtime_checkable

import aioboto3
from aiobotocore.response import StreamingBody
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from eylo.sockets.tts.adapters.polly_wire import POLLY_SERVICE
from eylo.sockets.tts.exceptions import TTSConnectionFailed


@runtime_checkable
class PollySdkClient(Protocol):
    async def synthesize_speech(
        self,
        *,
        Engine: str,
        LanguageCode: str,
        OutputFormat: str,
        SampleRate: str,
        Text: str,
        TextType: str,
        VoiceId: str,
    ) -> object: ...


@runtime_checkable
class PollyStreamCloser(Protocol):
    def close(self) -> object: ...


@runtime_checkable
class PollyAudioStream(PollyStreamCloser, Protocol):
    async def read(self, amount: int) -> object: ...


class _SdkAudioStream(BaseModel):
    """Expose the concrete SDK proxy's methods to structural validation."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    native: StreamingBody = Field(repr=False, exclude=True)

    async def read(self, amount: int) -> object:
        return await self.native.read(amount)

    def close(self) -> object:
        return self.native.close()


class _PollyRawResponse(BaseModel):
    """Keep the body reachable if validation fails, so it can still be closed."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    audio_stream: object = Field(alias="AudioStream", repr=False, exclude=True)


class PollySynthesisResponse(BaseModel):
    """Only the consumed body; additional AWS response metadata is ignored."""

    model_config = ConfigDict(
        frozen=True,
        extra="ignore",
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )
    audio_stream: PollyAudioStream = Field(
        alias="AudioStream", repr=False, exclude=True
    )

    @field_validator("audio_stream", mode="before")
    @classmethod
    def _sdk_proxy(cls, value: object) -> object:
        if isinstance(value, StreamingBody):
            return _SdkAudioStream(native=value)
        return value

    @field_validator("audio_stream")
    @classmethod
    def _stream_methods(cls, value: PollyAudioStream) -> PollyAudioStream:
        if not callable(value.read) or not callable(value.close):
            raise ValueError("Polly audio stream requires read and close methods.")
        return value

    @classmethod
    async def from_sdk(cls, value: object) -> "PollySynthesisResponse":
        body: object = None
        try:
            raw = _PollyRawResponse.model_validate(value)
            body = raw.audio_stream
            return cls(AudioStream=body)
        except ValidationError:
            if isinstance(body, PollyStreamCloser) and callable(body.close):
                await close_audio_stream(body)
            raise TTSConnectionFailed(
                "Amazon Polly returned an invalid audio stream."
            ) from None


@asynccontextmanager
async def open_polly_client(session: aioboto3.Session) -> AsyncIterator[PollySdkClient]:
    """The SDK context owns cleanup, including rejected client shapes."""
    async with session.client(POLLY_SERVICE) as native:
        if not isinstance(native, PollySdkClient) or not callable(
            native.synthesize_speech
        ):
            raise TTSConnectionFailed("Amazon Polly returned an invalid client.")
        yield native


async def read_audio(stream: PollyAudioStream, amount: int) -> bytes:
    value = await stream.read(amount)
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TTSConnectionFailed("Amazon Polly returned non-binary audio.")
    return bytes(value)


async def close_audio_stream(stream: PollyStreamCloser) -> None:
    """Close the proxied SDK body; injected streams may await cleanup."""
    with suppress(Exception):
        result = stream.close()
        if inspect.isawaitable(result):
            await result
