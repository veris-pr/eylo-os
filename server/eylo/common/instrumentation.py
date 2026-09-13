"""Safe no-op instrumentation helpers for the open-source runtime."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID


def traced_agent[**Params, Result](
    agent_name: str,
) -> Callable[[Callable[Params, Result]], Callable[Params, Result]]:
    """Return a decorator that leaves the wrapped callable unchanged."""

    def decorator(function: Callable[Params, Result]) -> Callable[Params, Result]:
        return function

    return decorator


@contextmanager
def agent_span(
    agent_name: str,
    conversation_id: UUID | None = None,
    model: str | None = None,
    available_tools: list[str] | None = None,
) -> Iterator["NullSpan"]:
    """Yield a span-compatible no-op object."""
    yield NullSpan()


@contextmanager
def tool_span(
    tool_name: str,
    tool_input: str | None = None,
) -> Iterator["NullSpan"]:
    """Yield a span-compatible no-op object."""
    yield NullSpan()


class NullSpan:
    """Minimal span-like object that accepts data without retaining it."""

    def set_data(self, key: str, value: object) -> None:
        pass
