"""Critical application callbacks and best-effort lifecycle hooks for runs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from .agent import AgentSpec
from .common import FrozenFrameworkModel
from .context import RunContext, RunInput
from .model import ModelResponse
from .result import RunResult
from .tool import ToolCall, ToolResult


class RunCallbacks(FrozenFrameworkModel):
    """Application operations awaited at the existing persistence boundaries.

    Unlike lifecycle hooks, failures stop the run; cancellation propagates.
    Callbacks receive live ``RunContext`` but never become serialized run input.
    Bind them once to a runner, independently of mutable application state.
    """

    after_model_response: SkipJsonSchema[
        Callable[
            [RunContext, RunInput, ModelResponse, tuple[ToolCall, ...]], Awaitable[None]
        ]
        | None
    ] = Field(default=None, exclude=True, repr=False)
    before_tool_call: SkipJsonSchema[
        Callable[[RunContext, ToolCall, ModelResponse], Awaitable[None]] | None
    ] = Field(default=None, exclude=True, repr=False)
    after_tool_result: SkipJsonSchema[
        Callable[[RunContext, ToolCall, ToolResult], Awaitable[None]] | None
    ] = Field(default=None, exclude=True, repr=False)
    after_tool_results: SkipJsonSchema[
        Callable[[RunContext, RunInput, tuple[ToolResult, ...]], Awaitable[RunInput]]
        | None
    ] = Field(default=None, exclude=True, repr=False)


class RunHooks:
    """Best-effort lifecycle notifications; failures do not change run outcomes."""

    async def on_run_start(self, context: RunContext) -> None:
        """Run started."""

    async def on_run_end(self, context: RunContext, result: RunResult) -> None:
        """Run completed or stopped."""

    async def on_agent_start(self, context: RunContext, agent: AgentSpec) -> None:
        """Agent became active."""

    async def on_llm_start(self, context: RunContext, run_input: RunInput) -> None:
        """Model call started."""

    async def on_llm_end(
        self,
        context: RunContext,
        response: ModelResponse,
    ) -> None:
        """Model call completed."""

    async def on_tool_start(self, context: RunContext, call: ToolCall) -> None:
        """Tool execution started."""

    async def on_tool_end(
        self,
        context: RunContext,
        call: ToolCall,
        result: ToolResult,
    ) -> None:
        """Tool execution completed."""

    async def on_handoff(
        self,
        context: RunContext,
        from_agent: AgentSpec,
        to_agent: AgentSpec,
    ) -> None:
        """Active agent changed."""

    async def on_error(self, context: RunContext, error: Exception) -> None:
        """Run-level error occurred."""
