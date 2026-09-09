"""Bridge between realtime tool calls and platform tool execution.

Translates ToolCallEvent fields into LLMToolUseBlock, delegates to
the current platform executor. Uses isolated execution
(own transaction per call) since tools run in background tasks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, model_validator

from eylo.common.contracts.conversation import WIDGET_TOOL_PREFIX
from eylo.common.database import start_transaction
from eylo.framework.agents.config import RunConfig
from eylo.framework.agents.context import RunContext
from eylo.framework.agents.tool import ToolCall
from eylo.modules.conversations.schemas.conversations import ConversationContext
from eylo.pipelines.agent_execution_context import PlatformRunState
from eylo.pipelines.conversation.domain import agent_spec_from_context
from eylo.pipelines.conversation.tool_batch import (
    ConversationToolBatchExecutor,
    HandoffResult,
)
from eylo.pipelines.voice.live_buffer import LiveVoiceBufferIdentity
from eylo.pipelines.voice.tool_executor import (
    LiveVoiceToolExecutor,
    without_live_sandbox_agent_tools,
)
from eylo.sockets.llm.schemas import LLMToolUseBlock

logger = logging.getLogger(__name__)


class DispatchResult(BaseModel):
    """Outcome of a single tool dispatch.

    The manager inspects these fields for post-execution actions
    (handoff session update, widget fallback tracking).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    result: StrictStr
    is_error: StrictBool = False
    is_widget_fallback: StrictBool = False
    handoff: HandoffResult | None = None

    @model_validator(mode="after")
    def validate_handoff(self) -> DispatchResult:
        if self.handoff is not None and (
            self.is_error is not self.handoff.is_error
            or self.result != self.handoff.tool_result
            or self.is_widget_fallback
        ):
            raise ValueError("Realtime dispatch must preserve its handoff outcome.")
        return self


class RealtimeToolDispatcher:
    def __init__(
        self,
        ctx: ConversationContext,
        identity: LiveVoiceBufferIdentity,
        *,
        tool_executor: LiveVoiceToolExecutor | None = None,
    ) -> None:
        self._ctx = ctx
        self._identity = identity
        self._executor = tool_executor or LiveVoiceToolExecutor(identity)
        self._handoff_executor = ConversationToolBatchExecutor()
        self._widget_fallback_occurred: bool = False

    async def execute(
        self, tool_call_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> DispatchResult:
        """Execute a tool and return a structured result.

        Special handling:
        - **Handoff tools**: delegates to ``execute_handoff_tool`` and returns
          the typed outcome. The manager rebuilds the full context from DB before
          changing the live session; no partial agent/participant update occurs here.
        - **Widget tools**: tracks validation failures per-turn so a second
          call in the same turn gets a "reply in plain text" fallback.
        """
        tool_use_block = LLMToolUseBlock(
            id=tool_call_id,
            name=tool_name,
            input=arguments,
        )

        if ConversationToolBatchExecutor.is_handoff_tool(tool_name):
            handoff_result = HandoffResult.model_validate(
                await self._handoff_executor.execute_handoff_tool(
                    self._ctx, tool_use_block
                )
            )
            return DispatchResult(
                result=handoff_result.tool_result,
                is_error=handoff_result.is_error,
                handoff=handoff_result,
            )

        # Widget fallback guard: if a widget tool already failed this turn,
        # block re-invocation (matches non-realtime runner behavior).
        if self._is_widget_tool(tool_name) and self._widget_fallback_occurred:
            fallback_msg = (
                "A widget tool already failed this turn. "
                "Do not call another widget tool during this turn. "
                "Reply to the user in normal plain text instead."
            )
            return DispatchResult(
                result=fallback_msg, is_error=True, is_widget_fallback=True
            )

        agent = without_live_sandbox_agent_tools(agent_spec_from_context(self._ctx))
        run_context = RunContext(
            config=RunConfig(),
            current_agent=agent,
            handoff_chain=[agent],
            conversation_id=self._ctx.conversation.id,
            organization_id=self._ctx.conversation.organization_id,
            local_context=PlatformRunState(
                conversation_context=self._ctx,
                live_voice_identity=self._identity,
            ),
        )
        async with start_transaction():
            tool_result = await self._executor.execute(
                run_context,
                ToolCall(
                    id=tool_call_id,
                    name=tool_name,
                    arguments=arguments,
                ),
            )

        is_widget_fallback = self._is_widget_tool(tool_name) and tool_result.is_error
        result_value = (
            {"content": tool_result.content}
            if isinstance(tool_result.content, list)
            else tool_result.content
        )

        if is_widget_fallback:
            self._widget_fallback_occurred = True
            result_value = (
                "A widget could not be rendered. "
                "Do not call another widget tool during this turn. "
                "Reply to the user in normal plain text instead."
            )

        return DispatchResult(
            result=(
                result_value
                if isinstance(result_value, str)
                else json.dumps(result_value, ensure_ascii=False)
            ),
            is_error=tool_result.is_error,
            is_widget_fallback=is_widget_fallback,
        )

    def update_context(self, ctx: ConversationContext) -> None:
        """Replace the conversation context (e.g. after handoff rebuild)."""
        self._ctx = ctx

    def reset_turn_state(self) -> None:
        """Reset per-turn state.  Call on turn_complete."""
        self._widget_fallback_occurred = False

    @staticmethod
    def _is_widget_tool(tool_name: str) -> bool:
        return tool_name.startswith(WIDGET_TOOL_PREFIX)
