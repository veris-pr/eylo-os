"""Small, explicit runner for the new framework execution path."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable
from typing import AsyncIterator, Literal, TypeVar
from uuid import UUID

from pydantic import JsonValue, model_validator

from .agent import AgentSpec
from .approval import ApprovalActionKind, ApprovalRequest, RiskLevel
from .common import FrameworkMetadata, FrozenFrameworkModel
from .config import RunConfig
from .context import RunContext, RunInput, RunMessage
from .durable import InputRequestDetails
from .errors import (
    GuardrailTripwireError,
    ModelOutputLimitError,
    ToolResultIdentityError,
)
from .guardrail import Guardrail, GuardrailStage
from .history import (
    HistoryMessageMetadata,
    ModelMessageMetadata,
    ModelResponseProvenance,
    ToolResultProvenance,
    tool_exchange_messages,
)
from .hooks import RunCallbacks, RunHooks
from .interruptions import (
    RunApprovalInterruption,
    RunInputInterruption,
    ToolApprovalContinuation,
    ToolInputContinuation,
)
from .items import (
    RunApprovalRequestItem,
    RunInputRequestItem,
    RunItem,
    RunItemKind,
    RunMessageItem,
    RunMessagePayload,
    RunToolCallItem,
    RunToolResultItem,
)
from .model import Model, ModelBlockKind, ModelResponse, ModelStopReason, ModelUsage
from .result import (
    RunFailureCode,
    RunFailureMetadata,
    RunResult,
    RunStatus,
    RunTerminalMetadata,
)
from .tool import (
    ToolCall,
    ToolCompletionMetadata,
    ToolCompletionMode,
    ToolExecutionMode,
    ToolExecutor,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
_MAX_APPROVAL_ARGUMENT_FIELDS = 32
ToolInterruptionStatus = Literal[
    RunStatus.WAITING_FOR_APPROVAL, RunStatus.WAITING_FOR_INPUT
]


class ToolExecutionOutcome(FrozenFrameworkModel):
    """Tool execution batch plus optional interruption metadata."""

    results: tuple[ToolResult, ...]
    interrupted_status: ToolInterruptionStatus | None = None
    interruption_metadata: RunApprovalInterruption | RunInputInterruption | None = None

    @model_validator(mode="after")
    def validate_pause_kind(self) -> ToolExecutionOutcome:
        """A pause status must match its request and continuation contract."""
        if self.interrupted_status is RunStatus.WAITING_FOR_APPROVAL:
            if isinstance(self.interruption_metadata, RunApprovalInterruption):
                return self
        elif self.interrupted_status is RunStatus.WAITING_FOR_INPUT:
            if isinstance(self.interruption_metadata, RunInputInterruption):
                return self
        elif self.interrupted_status is None and self.interruption_metadata is None:
            return self
        raise ValueError("Tool interruption status and request must match.")


async def _safe_hook(coro: Awaitable[None], hook_name: str) -> None:
    """Await a hook callback, logging but not propagating errors."""
    try:
        await coro
    except Exception as error:
        logger.error(
            "Hook failed hook=%s error_type=%s; preserving run result",
            hook_name,
            type(error).__name__,
        )


class FrameworkRunner:
    """Stateless orchestrator for one framework run.

    This mirrors the simplicity of ``openai-agents-python``: callers provide an
    agent, LLM-visible input, optional config/context, and get a ``RunResult``.
    The runner owns loop control only; persistence, durable scheduling, and
    transport remain outside this class.
    """

    def __init__(
        self,
        model: Model,
        *,
        tool_executor: ToolExecutor | None = None,
        hooks: RunHooks | None = None,
        callbacks: RunCallbacks | None = None,
        guardrails: tuple[Guardrail, ...] = (),
    ) -> None:
        self._model = model
        self._tool_executor = tool_executor
        self._hooks = hooks or RunHooks()
        self._callbacks = callbacks or RunCallbacks()
        self._guardrails = guardrails

    async def run(
        self,
        agent: AgentSpec,
        run_input: RunInput,
        config: RunConfig | None = None,
        local_context: object | None = None,
    ) -> RunResult:
        """Run an agent to a terminal or interrupted state."""
        context = RunContext(
            config=config if config is not None else RunConfig(),
            current_agent=agent,
            handoff_chain=[agent],
            local_context=local_context,
        )
        run_config = context.config
        items: list[RunItem] = []
        model_responses: list[ModelResponse] = []
        current_input = run_input

        await _safe_hook(self._hooks.on_run_start(context), "on_run_start")

        try:
            await self._check_input_guardrails(context, current_input)

            for turn in range(1, run_config.max_turns + 1):
                context.turn = turn

                if context.is_timed_out:
                    result = self._build_result(
                        context,
                        status=RunStatus.TIMED_OUT,
                        items=items,
                        model_responses=model_responses,
                        error_message="Run timed out.",
                    )
                    await _safe_hook(
                        self._hooks.on_run_end(context, result), "on_run_end"
                    )
                    return result

                await _safe_hook(
                    self._hooks.on_agent_start(context, context.current_agent),
                    "on_agent_start",
                )
                await _safe_hook(
                    self._hooks.on_llm_start(context, current_input), "on_llm_start"
                )

                response = ModelResponse.model_validate(
                    await _await_with_timeout(
                        context,
                        self._model.generate(
                            current_input,
                            context.current_agent.model_settings,
                        ),
                    ),
                )
                model_responses.append(response)
                context.usage = _add_usage(context.usage, response.usage)
                await _safe_hook(
                    self._hooks.on_llm_end(context, response), "on_llm_end"
                )

                if response.stop_reason is ModelStopReason.MAX_TOKENS:
                    # Account for generation, but never accept truncated text or
                    # execute commands from an incomplete model response.
                    raise ModelOutputLimitError

                text = _extract_text(response)
                tool_calls = _extract_tool_calls(response)

                if tool_calls:
                    await _apply_model_response_update(
                        self._callbacks,
                        context,
                        current_input,
                        response,
                        tool_calls,
                    )
                    if text:
                        items.append(
                            RunMessageItem(
                                run_id=context.run_id,
                                kind=RunItemKind.MESSAGE,
                                message=text,
                                payload=RunMessagePayload(content=text),
                            )
                        )
                    tool_results = await self._execute_tools(
                        context,
                        _available_tool_specs(context, current_input),
                        tool_calls,
                        items,
                        response,
                    )
                    if tool_results.interrupted_status is not None:
                        result = self._build_result(
                            context,
                            status=tool_results.interrupted_status,
                            items=items,
                            model_responses=model_responses,
                            metadata=tool_results.interruption_metadata,
                        )
                        await _safe_hook(
                            self._hooks.on_run_end(context, result), "on_run_end"
                        )
                        return result
                    executed_tool_calls = tool_calls[: len(tool_results.results)]
                    current_input = _append_tool_messages(
                        current_input,
                        executed_tool_calls,
                        tool_results.results,
                        response,
                    )
                    current_input = await _apply_post_tool_update(
                        self._callbacks,
                        context,
                        current_input,
                        tool_results.results,
                    )
                    terminal_tool_result = _terminal_tool_result(tool_results.results)
                    terminal_output = _terminal_output_from_tool_result(
                        terminal_tool_result
                    )
                    if terminal_output is not None:
                        items.append(
                            RunMessageItem(
                                run_id=context.run_id,
                                kind=RunItemKind.MESSAGE,
                                message=terminal_output,
                                payload=RunMessagePayload(content=terminal_output),
                            )
                        )
                        result = self._build_result(
                            context,
                            status=RunStatus.COMPLETED,
                            items=items,
                            model_responses=model_responses,
                            final_output=terminal_output,
                            metadata=_terminal_metadata_from_tool_result(
                                terminal_tool_result
                            ),
                        )
                        await self._check_output_guardrails(context, result)
                        await _safe_hook(
                            self._hooks.on_run_end(context, result), "on_run_end"
                        )
                        return result
                    continue

                if text:
                    item = RunMessageItem(
                        run_id=context.run_id,
                        kind=RunItemKind.MESSAGE,
                        message=text,
                        payload=RunMessagePayload(content=text),
                    )
                    items.append(item)
                    result = self._build_result(
                        context,
                        status=RunStatus.COMPLETED,
                        items=items,
                        model_responses=model_responses,
                        final_output=text,
                    )
                    await self._check_output_guardrails(context, result)
                    await _safe_hook(
                        self._hooks.on_run_end(context, result), "on_run_end"
                    )
                    return result

                # Model returned neither text nor tool calls (empty/refusal).
                result = self._build_result(
                    context,
                    status=RunStatus.COMPLETED,
                    items=items,
                    model_responses=model_responses,
                    final_output=None,
                )
                await _safe_hook(self._hooks.on_run_end(context, result), "on_run_end")
                return result

            result = self._build_result(
                context,
                status=RunStatus.MAX_TURNS_EXCEEDED,
                items=items,
                model_responses=model_responses,
                error_message="Run exceeded max turns.",
            )
            await _safe_hook(self._hooks.on_run_end(context, result), "on_run_end")
            return result

        except TimeoutError:
            result = self._build_result(
                context,
                status=RunStatus.TIMED_OUT,
                items=items,
                model_responses=model_responses,
                error_message="Run timed out.",
            )
            await _safe_hook(self._hooks.on_run_end(context, result), "on_run_end")
            return result
        except Exception as error:
            await _safe_hook(self._hooks.on_error(context, error), "on_error")
            status = RunStatus.FAILED
            failure_code = RunFailureCode.RUN_FAILED
            error_message = "Run failed."
            if isinstance(error, GuardrailTripwireError):
                status = RunStatus.GUARDRAIL_TRIPPED
                failure_code = RunFailureCode.GUARDRAIL_BLOCKED
                error_message = "A guardrail blocked the run."
            elif isinstance(error, ModelOutputLimitError):
                failure_code = RunFailureCode.MODEL_OUTPUT_LIMIT
                error_message = "The model reached its output token limit."
            result = self._build_result(
                context,
                status=status,
                items=items,
                model_responses=model_responses,
                error_message=error_message,
                metadata=RunFailureMetadata(
                    failure_code=failure_code,
                    error_type=type(error).__name__,
                ),
            )
            await _safe_hook(self._hooks.on_run_end(context, result), "on_run_end")
            return result

    async def run_streamed(
        self,
        agent: AgentSpec,
        run_input: RunInput,
        config: RunConfig | None = None,
        local_context: object | None = None,
    ) -> AsyncIterator[RunItem]:
        """Run an agent and stream framework items as they are produced."""
        result = await self.run(
            agent,
            run_input,
            config=config,
            local_context=local_context,
        )
        for item in result.items:
            yield item

    async def _execute_tools(
        self,
        context: RunContext,
        tool_specs: tuple[ToolSpec, ...],
        tool_calls: tuple[ToolCall, ...],
        items: list[RunItem],
        model_response: ModelResponse,
    ) -> ToolExecutionOutcome:
        """Execute model-requested tools."""
        results: list[ToolResult] = []
        tool_specs_by_name = {tool.name: tool for tool in tool_specs}
        for call in tool_calls:
            await self._check_tool_input_guardrails(context, call)
            items.append(
                RunToolCallItem(
                    run_id=context.run_id,
                    kind=RunItemKind.TOOL_CALL,
                    payload=call,
                )
            )
            await _apply_tool_call_update(
                self._callbacks, context, call, model_response
            )
            tool_spec = tool_specs_by_name.get(call.name)
            policy_result = _tool_policy_result(context, tool_spec, call)
            if policy_result is not None:
                if policy_result.interrupted_status is not None:
                    assert policy_result.interruption_metadata is not None
                    result = _pause_tool_result(
                        call,
                        policy_result.interrupted_status,
                        policy_result.interruption_metadata,
                    )
                    await self._record_tool_result(
                        context,
                        call,
                        result,
                        items,
                        emit_tool_end=False,
                    )
                    items.append(_approval_request_item(context, policy_result))
                    return _interrupted_tool_outcome(
                        results,
                        result,
                        policy_result.interrupted_status,
                        policy_result.interruption_metadata,
                    )

                assert policy_result.results
                result = policy_result.results[0]
                await self._record_tool_result(
                    context,
                    call,
                    result,
                    items,
                    emit_tool_end=False,
                )
                results.append(result)
                continue

            if self._tool_executor is None:
                raise ValueError(
                    "Model requested tools but no tool executor is configured."
                )

            await _safe_hook(self._hooks.on_tool_start(context, call), "on_tool_start")
            try:
                result = _validated_tool_result(
                    call,
                    await _await_with_timeout(
                        context,
                        self._tool_executor.execute(context, call),
                    ),
                )
            except Exception as error:
                result = ToolResult(
                    tool_call_id=call.id,
                    content="Error: Tool execution failed.",
                    is_error=True,
                    metadata={"tool_execution_failed": True},
                )
                await self._record_tool_result(
                    context,
                    call,
                    result,
                    items,
                    emit_tool_end=False,
                )
                raise error
            approval_metadata = _approval_metadata_from_tool_result(call, result)
            if approval_metadata is not None:
                await self._record_tool_result(
                    context,
                    call,
                    result,
                    items,
                    emit_tool_end=True,
                )
                items.append(_approval_request_item(context, approval_metadata))
                return _interrupted_tool_outcome(
                    results,
                    result,
                    RunStatus.WAITING_FOR_APPROVAL,
                    approval_metadata.interruption_metadata,
                )
            input_metadata = _input_metadata_from_tool_result(call, result)
            if input_metadata is not None:
                await self._record_tool_result(
                    context,
                    call,
                    result,
                    items,
                    emit_tool_end=True,
                )
                items.append(_input_request_item(context, input_metadata))
                return _interrupted_tool_outcome(
                    results,
                    result,
                    RunStatus.WAITING_FOR_INPUT,
                    input_metadata.interruption_metadata,
                )
            try:
                await self._check_tool_output_guardrails(context, result)
            except GuardrailTripwireError:
                result = ToolResult(
                    tool_call_id=call.id,
                    content="Error: Tool output blocked by guardrail.",
                    is_error=True,
                    metadata={"tool_output_blocked": True},
                )
                await self._record_tool_result(
                    context,
                    call,
                    result,
                    items,
                    emit_tool_end=False,
                )
                raise
            await self._record_tool_result(
                context,
                call,
                result,
                items,
                emit_tool_end=True,
            )
            results.append(result)
            if _terminal_output_from_tool_results((result,)) is not None:
                break

        return ToolExecutionOutcome(results=tuple(results))

    async def _record_tool_result(
        self,
        context: RunContext,
        call: ToolCall,
        result: ToolResult,
        items: list[RunItem],
        *,
        emit_tool_end: bool,
    ) -> None:
        """Persist and record a tool result, preserving hook ordering."""
        result = _validated_tool_result(call, result)
        await _apply_tool_result_update(self._callbacks, context, call, result)
        if emit_tool_end:
            await _safe_hook(
                self._hooks.on_tool_end(context, call, result),
                "on_tool_end",
            )
        items.append(_tool_result_item(context, result))

    async def _check_input_guardrails(
        self,
        context: RunContext,
        run_input: RunInput,
    ) -> None:
        for guardrail in self._guardrails:
            if guardrail.spec.stage != GuardrailStage.INPUT:
                continue
            result = await guardrail.check_input(context, run_input)
            if result.tripwire_triggered:
                raise GuardrailTripwireError(result.message or result.name)

    async def _check_output_guardrails(
        self,
        context: RunContext,
        result: RunResult,
    ) -> None:
        for guardrail in self._guardrails:
            if guardrail.spec.stage != GuardrailStage.OUTPUT:
                continue
            guardrail_result = await guardrail.check_output(context, result)
            if guardrail_result.tripwire_triggered:
                raise GuardrailTripwireError(
                    guardrail_result.message or guardrail_result.name
                )

    async def _check_tool_input_guardrails(
        self,
        context: RunContext,
        call: ToolCall,
    ) -> None:
        for guardrail in self._guardrails:
            if guardrail.spec.stage != GuardrailStage.TOOL_INPUT:
                continue
            result = await guardrail.check_tool_input(context, call)
            if result.tripwire_triggered:
                raise GuardrailTripwireError(result.message or result.name)

    async def _check_tool_output_guardrails(
        self,
        context: RunContext,
        tool_result: ToolResult,
    ) -> None:
        for guardrail in self._guardrails:
            if guardrail.spec.stage != GuardrailStage.TOOL_OUTPUT:
                continue
            result = await guardrail.check_tool_output(context, tool_result)
            if result.tripwire_triggered:
                raise GuardrailTripwireError(result.message or result.name)

    @staticmethod
    def _build_result(
        context: RunContext,
        *,
        status: RunStatus,
        items: list[RunItem],
        model_responses: list[ModelResponse],
        final_output: str | None = None,
        error_message: str | None = None,
        metadata: FrameworkMetadata | None = None,
    ) -> RunResult:
        return RunResult(
            run_id=context.run_id,
            status=status,
            final_output=final_output,
            items=tuple(items),
            model_responses=tuple(model_responses),
            usage=context.usage,
            starting_agent=context.handoff_chain[0] if context.handoff_chain else None,
            final_agent=context.current_agent,
            error_message=error_message,
            metadata=metadata if metadata is not None else FrameworkMetadata(),
        )


async def _await_with_timeout(
    context: RunContext,
    awaitable: Awaitable[T],
) -> T:
    """Await an operation without exceeding the run's remaining wall-clock timeout."""
    return await asyncio.wait_for(
        awaitable,
        timeout=context.remaining_timeout_seconds,
    )


def _extract_text(response: ModelResponse) -> str:
    """Return combined text blocks from a model response."""
    return "".join(
        block.content for block in response.blocks if block.kind is ModelBlockKind.TEXT
    )


def _extract_tool_calls(response: ModelResponse) -> tuple[ToolCall, ...]:
    """Return tool calls requested by a model response."""
    return tuple(
        block.content
        for block in response.blocks
        if block.kind is ModelBlockKind.TOOL_CALL
    )


def _append_tool_messages(
    run_input: RunInput,
    tool_calls: tuple[ToolCall, ...],
    tool_results: tuple[ToolResult, ...],
    model_response: ModelResponse,
) -> RunInput:
    """Return input with tool calls/results appended for the next turn."""
    messages = list(run_input.messages)
    request_id = HistoryMessageMetadata(
        request_id=run_input.metadata.get("request_id")
    ).request_id
    results_by_call_id = {result.tool_call_id: result for result in tool_results}
    calls_by_id = {call.id: call for call in tool_calls}

    for index, block in enumerate(model_response.blocks):
        model_meta = _model_response_metadata_for_next_turn(model_response, index)
        if block.kind == ModelBlockKind.TEXT:
            text = block.content
            if text:
                messages.append(
                    RunMessage(
                        role="assistant",
                        content=text,
                        metadata=ModelMessageMetadata(
                            request_id=request_id, meta=model_meta
                        ),
                    )
                )
            continue

        if block.kind != ModelBlockKind.TOOL_CALL:
            continue

        parsed_call = block.content
        result = results_by_call_id.get(parsed_call.id)
        if result is None:
            continue
        call = calls_by_id.get(parsed_call.id, parsed_call)
        messages.extend(
            tool_exchange_messages(
                call,
                result,
                request_id=request_id,
                result_text=_tool_result_content_for_message(result),
                model_meta=model_meta,
                result_meta=_tool_result_metadata_for_next_turn(result),
            )
        )

    return run_input.model_copy(
        update={
            "messages": tuple(messages),
            "metadata": run_input.metadata.model_copy(
                update={
                    "transient_tool_message_count": len(messages)
                    - len(run_input.messages)
                }
            ),
        }
    )


def _tool_result_content_for_message(result: ToolResult) -> str:
    """Serialize structured tool output for the model-visible message contract."""
    if isinstance(result.content, str):
        return result.content
    return json.dumps(
        result.content,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _tool_result_metadata_for_next_turn(result: ToolResult) -> ToolResultProvenance:
    """Return metadata safe to round-trip into transient tool-result messages."""
    return ToolResultProvenance.from_result(result)


def _model_response_metadata_for_next_turn(
    response: ModelResponse,
    response_block_index: int,
) -> ModelResponseProvenance:
    """Return model metadata in the shape existing LLM adapters understand."""
    return ModelResponseProvenance(
        model_response=response, response_block_index=response_block_index
    )


async def _apply_post_tool_update(
    callbacks: RunCallbacks,
    context: RunContext,
    run_input: RunInput,
    tool_results: tuple[ToolResult, ...],
) -> RunInput:
    """Allow application adapters to refresh local context after tool side effects."""
    callback = callbacks.after_tool_results
    if callback is None:
        return run_input
    updated_input = await callback(context, run_input, tool_results)
    if not isinstance(updated_input, RunInput):
        raise TypeError("after_tool_results must return RunInput.")
    return updated_input


async def _apply_model_response_update(
    callbacks: RunCallbacks,
    context: RunContext,
    run_input: RunInput,
    response: ModelResponse,
    tool_calls: tuple[ToolCall, ...],
) -> None:
    """Run application-local side effects for model responses with tools."""
    callback = callbacks.after_model_response
    if callback is None:
        return
    await callback(context, run_input, response, tool_calls)


async def _apply_tool_result_update(
    callbacks: RunCallbacks,
    context: RunContext,
    call: ToolCall,
    result: ToolResult,
) -> None:
    """Run application-local side effects for tool results."""
    callback = callbacks.after_tool_result
    if callback is None:
        return
    await callback(context, call, result)


async def _apply_tool_call_update(
    callbacks: RunCallbacks,
    context: RunContext,
    call: ToolCall,
    response: ModelResponse,
) -> None:
    """Run application-local side effects for a tool call before execution."""
    callback = callbacks.before_tool_call
    if callback is None:
        return
    await callback(context, call, response)


def _tool_policy_result(
    context: RunContext,
    tool_spec: ToolSpec | None,
    call: ToolCall,
) -> ToolExecutionOutcome | None:
    """Return policy-driven outcome before dispatching a tool executor."""
    if tool_spec is None:
        result = ToolResult(
            tool_call_id=call.id,
            content="Error: The requested tool is not available to this agent.",
            is_error=True,
            metadata={"tool_policy_violation": True, "reason": "unknown_tool"},
        )
        return ToolExecutionOutcome(results=(result,))

    if tool_spec.execution_mode == ToolExecutionMode.DISABLED:
        result = ToolResult(
            tool_call_id=call.id,
            content="Error: Tool execution is disabled by policy.",
            is_error=True,
            metadata={
                "tool_policy_violation": True,
                "reason": "disabled_tool",
            },
        )
        return ToolExecutionOutcome(results=(result,))

    if tool_spec.execution_mode == ToolExecutionMode.REQUIRES_APPROVAL:
        approval_request = ApprovalRequest(
            durable_run_id=context.run_id,
            requested_by_agent_id=context.current_agent.id,
            action_kind=ApprovalActionKind.TOOL_CALL,
            action_summary=_tool_approval_summary(tool_spec),
            action_payload_redacted=_tool_approval_payload(tool_spec, call),
            risk_level=RiskLevel.MEDIUM,
            policy_reason="Stored tool policy requires approval before execution.",
        )
        return ToolExecutionOutcome(
            results=(),
            interrupted_status=RunStatus.WAITING_FOR_APPROVAL,
            interruption_metadata=_approval_interruption_metadata(
                call,
                approval_request,
            ),
        )

    return None


def _tool_approval_summary(tool_spec: ToolSpec) -> str:
    """Describe the stored tool authority without reflecting model output."""
    slug = tool_spec.metadata.get("slug")
    tool_id = tool_spec.metadata.get("id")
    revision = tool_spec.metadata.get("revision")
    if (
        isinstance(slug, str)
        and isinstance(tool_id, str | UUID)
        and type(revision) is int
        and revision > 0
    ):
        return f"Approve tool action {slug} ({tool_id}@{revision})."
    return "Approve this tool action."


def _tool_approval_payload(tool_spec: ToolSpec, call: ToolCall) -> dict[str, JsonValue]:
    """Project only stored identity and schema-owned argument structure."""
    payload: dict[str, JsonValue] = {}
    tool_id = tool_spec.metadata.get("id")
    revision = tool_spec.metadata.get("revision")
    if isinstance(tool_id, str | UUID):
        payload["tool_id"] = str(tool_id)
    if type(revision) is int and revision > 0:
        payload["tool_revision"] = revision

    properties = tool_spec.input_schema.get("properties")
    schema_fields = set(properties) if isinstance(properties, dict) else set()
    recognized_fields = sorted(
        field
        for field in call.arguments
        if isinstance(field, str) and field in schema_fields
    )
    payload["argument_fields"] = recognized_fields[:_MAX_APPROVAL_ARGUMENT_FIELDS]
    payload["argument_count"] = len(call.arguments)
    payload["unrecognized_argument_count"] = sum(
        field not in schema_fields for field in call.arguments
    )
    if len(recognized_fields) > _MAX_APPROVAL_ARGUMENT_FIELDS:
        payload["omitted_argument_field_count"] = (
            len(recognized_fields) - _MAX_APPROVAL_ARGUMENT_FIELDS
        )
    return payload


def _available_tool_specs(
    context: RunContext,
    run_input: RunInput,
) -> tuple[ToolSpec, ...]:
    """Return the model-visible tools for the current turn."""
    tools_by_name = {tool.name: tool for tool in context.current_agent.tools}
    tools_by_name.update({tool.name: tool for tool in run_input.tools})
    return tuple(tools_by_name.values())


def _approval_metadata_from_tool_result(
    call: ToolCall,
    result: ToolResult,
) -> ToolExecutionOutcome | None:
    """Return approval interruption when a tool executor reports one."""
    approval_request = result.metadata.get("approval_request")
    if approval_request is None:
        return None

    return ToolExecutionOutcome(
        results=(),
        interrupted_status=RunStatus.WAITING_FOR_APPROVAL,
        interruption_metadata=_approval_interruption_metadata(
            call,
            ApprovalRequest.model_validate(approval_request),
        ),
    )


def _input_metadata_from_tool_result(
    call: ToolCall,
    result: ToolResult,
) -> ToolExecutionOutcome | None:
    """Return input-request interruption when a tool executor reports one."""
    input_request = result.metadata.get("input_request")
    if input_request is None:
        return None

    return ToolExecutionOutcome(
        results=(),
        interrupted_status=RunStatus.WAITING_FOR_INPUT,
        interruption_metadata=_input_interruption_metadata(
            call, InputRequestDetails.model_validate(input_request)
        ),
    )


def _pause_tool_result(
    call: ToolCall,
    status: ToolInterruptionStatus,
    metadata: RunApprovalInterruption | RunInputInterruption,
) -> ToolResult:
    """Create a paired tool result so persisted provider history stays valid."""
    if status == RunStatus.WAITING_FOR_APPROVAL:
        content = "Tool execution paused pending approval."
    else:
        content = "Tool execution paused pending user input."
    return ToolResult(
        tool_call_id=call.id,
        content=content,
        metadata={
            "tool_execution_paused": True,
            "status": status.value,
            **metadata.model_dump(mode="json"),
        },
    )


def _interrupted_tool_outcome(
    prior_results: list[ToolResult],
    result: ToolResult,
    status: ToolInterruptionStatus,
    metadata: RunApprovalInterruption | RunInputInterruption | None,
) -> ToolExecutionOutcome:
    return ToolExecutionOutcome(
        results=(*prior_results, result),
        interrupted_status=status,
        interruption_metadata=metadata,
    )


def _approval_interruption_metadata(
    call: ToolCall,
    approval_request: ApprovalRequest,
) -> RunApprovalInterruption:
    """Build continuation metadata for approval-gated tool calls."""
    return RunApprovalInterruption(
        approval_request=approval_request,
        continuation=ToolApprovalContinuation(tool_call_id=call.id),
    )


def _input_interruption_metadata(
    call: ToolCall,
    input_request: InputRequestDetails,
) -> RunInputInterruption:
    """Build continuation metadata for input-gated tool calls."""
    return RunInputInterruption(
        input_request=input_request,
        continuation=ToolInputContinuation(tool_call_id=call.id),
    )


def _approval_request_item(
    context: RunContext,
    outcome: ToolExecutionOutcome,
) -> RunItem:
    """Represent a pause-for-approval as an inspectable run item."""
    if not isinstance(outcome.interruption_metadata, RunApprovalInterruption):
        raise ValueError("Approval item requires an approval interruption.")
    return RunApprovalRequestItem(
        run_id=context.run_id,
        kind=RunItemKind.APPROVAL_REQUEST,
        payload=outcome.interruption_metadata,
        message="Approval required before executing a tool action.",
    )


def _input_request_item(
    context: RunContext,
    outcome: ToolExecutionOutcome,
) -> RunItem:
    """Represent a pause-for-input as an inspectable run item."""
    if not isinstance(outcome.interruption_metadata, RunInputInterruption):
        raise ValueError("Input item requires an input interruption.")
    return RunInputRequestItem(
        run_id=context.run_id,
        kind=RunItemKind.INPUT_REQUEST,
        payload=outcome.interruption_metadata,
        message="Input required before completing a tool action.",
    )


def _validated_tool_result(call: ToolCall, result: ToolResult) -> ToolResult:
    """Reject malformed/foreign results before callbacks can persist completion."""
    result = ToolResult.model_validate(result)
    if result.tool_call_id != call.id:
        raise ToolResultIdentityError(
            "Tool result does not belong to the invocation being completed."
        )
    return result


def _tool_result_item(context: RunContext, result: ToolResult) -> RunItem:
    """Return the standard item shape for an observed tool result."""
    return RunToolResultItem(
        run_id=context.run_id,
        kind=RunItemKind.TOOL_RESULT,
        message=_tool_result_content_for_message(result),
        payload=result,
    )


def _terminal_output_from_tool_results(
    tool_results: tuple[ToolResult, ...],
) -> str | None:
    """Return terminal tool output when a tool intentionally ends the run."""
    return _terminal_output_from_tool_result(_terminal_tool_result(tool_results))


def _terminal_tool_result(
    tool_results: tuple[ToolResult, ...],
) -> ToolResult | None:
    return next(
        (
            result
            for result in tool_results
            if isinstance(result.metadata, ToolCompletionMetadata)
            and result.metadata.terminal_response is ToolCompletionMode.COMPLETE
        ),
        None,
    )


def _terminal_output_from_tool_result(result: ToolResult | None) -> str | None:
    if result is None or not isinstance(result.metadata, ToolCompletionMetadata):
        return None
    if result.metadata.terminal_response is not ToolCompletionMode.COMPLETE:
        return None
    output = result.metadata.terminal_output or result.content
    return str(output)


def _terminal_metadata_from_tool_result(
    result: ToolResult | None,
) -> FrameworkMetadata:
    """Return result metadata for terminal tool completions."""
    if result is None or not isinstance(result.metadata, ToolCompletionMetadata):
        return FrameworkMetadata()
    if result.metadata.terminal_artifact is not None:
        return RunTerminalMetadata(
            terminal_response=result.metadata.terminal_response,
            terminal_tool_call_id=result.tool_call_id,
            terminal_artifact=result.metadata.terminal_artifact,
        )
    return RunTerminalMetadata(
        terminal_response=result.metadata.terminal_response,
        terminal_tool_call_id=result.tool_call_id,
    )


def _add_usage(current: ModelUsage, incoming: ModelUsage) -> ModelUsage:
    """Return accumulated usage without mutating frozen value objects."""
    return ModelUsage(
        input_tokens=current.input_tokens + incoming.input_tokens,
        output_tokens=current.output_tokens + incoming.output_tokens,
        cache_creation_input_tokens=(
            current.cache_creation_input_tokens + incoming.cache_creation_input_tokens
        ),
        cache_read_input_tokens=(
            current.cache_read_input_tokens + incoming.cache_read_input_tokens
        ),
        reasoning_tokens=current.reasoning_tokens + incoming.reasoning_tokens,
    )
