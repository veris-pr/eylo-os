"""Narrow live voice resource ports shared by transport session owners."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class VoiceTurnRunner(Protocol):
    """Session teardown drains work; the runner owns execution and cancellation."""

    async def drain(self) -> None: ...
