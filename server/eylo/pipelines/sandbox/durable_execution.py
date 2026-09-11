"""Published-agent framework execution for direct objective AgentRuns."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from eylo.common.config import settings
from eylo.common.contracts.sandbox import SandboxError
from eylo.common.contracts.tool_availability import ToolRuntimeFact
from eylo.common.database import get_transaction, start_transaction
from eylo.framework.agents.config import RunConfig, RunPromptCaching, RunStreaming
from eylo.framework.agents.context import RunContext, RunInput, RunMessage
from eylo.framework.agents.durable import InputRequestDetails
from eylo.framework.agents.hooks import RunCallbacks
from eylo.framework.agents.interruptions import (
    RunApprovalInterruption,
    RunInputInterruption,
    ToolInputRequestMetadata,
)
from eylo.framework.agents.model import Model, ModelResponse, ModelUsage
from eylo.framework.agents.result import RunResult, RunStatus, RunTerminalMetadata
from eylo.framework.agents.runner import FrameworkRunner
from eylo.framework.agents.tool import (
    ToolCall,
    ToolCompletionMetadata,
    ToolCompletionMode,
    ToolExecutor,
    ToolKind,
    ToolResult,
    ToolSpec,
)
from eylo.modules.agent_runs.domain import (
    AgentApprovalDecision,
    AgentInputRequestKind,
    AgentRunLifecycle,
    AgentRunOriginKind,
    AgentRunOutcome,
)
from eylo.modules.agent_runs.service import (
    fail_agent_run,
    finish_agent_run_in_transaction,
    load_agent_run_wait,
    pause_agent_run_in_transaction,
    resume_agent_run_in_transaction,
)
from eylo.modules.agent_runs.waits import (
    AgentApprovalWaitState,
    AgentRunInputEvent,
    AgentRunWaitState,
)
from eylo.modules.agent_runs.workflow import (
    AgentRunExecutionClaim,
    AgentRunWorkflowContext,
)
from eylo.modules.llm_configs.wiring import resolve_pinned_llm
from eylo.modules.provider_configs.errors import NotConfiguredError
from eylo.modules.sandbox.run_context import ObjectiveRunContext
from eylo.modules.templates.domain import TemplateConsumerKind
from eylo.pipelines.agent_execution_context import (
    AgentExecutionContext,
    AgentExecutionParticipant,
    AgentExecutionScope,
    PlatformRunState,
)
from eylo.pipelines.agent_run_continuations import (
    ObjectiveRunContinuation,
    RunResumeReceipt,
    RunToolCallSnapshot,
    parse_run_continuation,
)
from eylo.pipelines.agent_run_heartbeat import run_with_agent_heartbeat
from eylo.pipelines.agent_run_results import (
    ObjectiveExhaustionSummary,
    ObjectiveRunSummary,
)
from eylo.pipelines.agent_run_tools import bind_agent_run_tool_command
from eylo.pipelines.agent_run_transcript import (
    AgentRunToolCapture,
    AgentRunTranscript,
    AgentRunTranscriptBridge,
    AgentRunTranscriptError,
    PendingToolCallsModel,
    append_resumed_tool_exchange,
    with_replay_messages,
)
from eylo.pipelines.agents import build_executable_agent_resolver
from eylo.pipelines.conversation.conversation_runner import ExistingConversationModel
from eylo.pipelines.conversation.domain import agent_spec_from_context
from eylo.pipelines.conversation.tool_executor import PlatformToolExecutor
from eylo.pipelines.llm.runtime import to_llm_prompt_caching
from eylo.pipelines.sandbox.sessions import discard_live_run_sessions
from eylo.pipelines.system_tools.availability import (
    refresh_context_tool_availability,
)

_OBJECTIVE_RESULT_LIMIT_BYTES = 65_536
_OBJECTIVE_REASON_LIMIT_CHARS = 4_000
_OBJECTIVE_PROMPT_LIMIT_CHARS = 8_192
_COMPLETE_OBJECTIVE_TOOL = "complete_objective"
_REQUEST_OBJECTIVE_INPUT_TOOL = "request_objective_input"
_PAUSE_STATUSES = {
    RunStatus.WAITING_FOR_INPUT,
    RunStatus.WAITING_FOR_APPROVAL,
}
_CONTROL_INSTRUCTIONS = """\
Use the agent's published tools when they help achieve the objective. Sandbox
compute is optional and exists only when the published agent has sandbox tools.
If one identified user answer is genuinely required, call
`request_objective_input`. A normal final answer concludes the objective as
achieved. To return a structured result or conclude that the objective cannot
be achieved, call `complete_objective`. Never claim a tool action happened
unless its returned result says it happened.\
"""


class ObjectiveAgentRunInvalid(Exception):
    """An objective run no longer agrees with its immutable authority."""


class ObjectiveAgentRunExhausted(Exception):
    """The filed objective reached an explicit step or deadline boundary."""


class ObjectiveAgentRunRetryable(Exception):
    """A tool call is persisted but has no canonical result yet."""


class ObjectiveCompletion(BaseModel):
    """Validated terminal tool payload shared by execution and persistence."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    outcome: Literal[AgentRunOutcome.ACHIEVED, AgentRunOutcome.UNACHIEVABLE]
    result: JsonValue = None
    reason: StrictStr | None = None

    @field_validator("result")
    @classmethod
    def require_finite_result(cls, value: JsonValue) -> JsonValue:
        """Validate before model dumping, which may normalize non-finite floats."""
        json.dumps(value, allow_nan=False)
        return value

    @model_validator(mode="after")
    def require_unachievable_reason(self) -> ObjectiveCompletion:
        if self.outcome is AgentRunOutcome.UNACHIEVABLE:
            if self.reason is None or not self.reason.strip():
                raise ValueError("Unachievable objectives require a reason.")
            if len(self.reason) > _OBJECTIVE_REASON_LIMIT_CHARS:
                raise ValueError("Objective completion reason exceeds its limit.")
        return self

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> ObjectiveCompletion:
        raw_outcome = arguments.get("outcome")
        if raw_outcome == AgentRunOutcome.ACHIEVED.value:
            outcome = AgentRunOutcome.ACHIEVED
        elif raw_outcome == AgentRunOutcome.UNACHIEVABLE.value:
            outcome = AgentRunOutcome.UNACHIEVABLE
        else:
            raise ObjectiveAgentRunInvalid(
                "Objective completion outcome must be achieved or unachievable."
            )
        reason = arguments.get("reason")
        if outcome is AgentRunOutcome.UNACHIEVABLE:
            reason = _required_text(
                arguments, "reason", max_chars=_OBJECTIVE_REASON_LIMIT_CHARS
            )
        elif reason is not None and not isinstance(reason, str):
            raise ObjectiveAgentRunInvalid("Objective completion reason must be text.")
        try:
            return cls.model_validate(
                {
                    "outcome": outcome,
                    "result": arguments.get("result"),
                    "reason": reason,
                }
            )
        except ValidationError as error:
            raise ObjectiveAgentRunInvalid(
                "Objective completion payload is invalid."
            ) from error

    def as_json(self) -> dict[str, JsonValue]:
        return self.model_dump(mode="json")


class ObjectiveFrameworkTurn(BaseModel):
    """Validated run conclusion and its captured invocation identities."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", revalidate_instances="always"
    )

    result: RunResult
    captured: AgentRunToolCapture


class ObjectiveControlToolExecutor:
    """Own objective wait/terminal controls; delegate published product tools."""

    def __init__(self, delegate: ToolExecutor) -> None:
        self._delegate = delegate

    async def execute(self, context: RunContext, call: ToolCall) -> ToolResult:
        if call.name == _REQUEST_OBJECTIVE_INPUT_TOOL:
            prompt = _required_text(
                call.arguments, "prompt", max_chars=_OBJECTIVE_PROMPT_LIMIT_CHARS
            )
            expected_schema = call.arguments.get("expected_response_schema") or {}
            if not isinstance(expected_schema, dict):
                raise ObjectiveAgentRunInvalid(
                    "Objective input response schema must be an object."
                )
            return ToolResult(
                tool_call_id=call.id,
                content="Objective paused pending identified user input.",
                metadata=ToolInputRequestMetadata(
                    input_request=InputRequestDetails(
                        prompt=prompt, expected_input_schema=expected_schema
                    )
                ),
            )
        if call.name == _COMPLETE_OBJECTIVE_TOOL:
            completion = ObjectiveCompletion.from_arguments(call.arguments)
            terminal_output = json.dumps(
                completion.as_json(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            return ToolResult(
                tool_call_id=call.id,
                content=terminal_output,
                metadata=ToolCompletionMetadata(
                    terminal_response=ToolCompletionMode.COMPLETE,
                    terminal_output=terminal_output,
                ),
            )
        return await self._delegate.execute(context, call)


class ObjectiveFrameworkRunner:
    """Resolve the exact published agent and run its neutral framework loop."""

    def __init__(
        self,
        *,
        model_factory: Callable[
            [PlatformRunState[AgentExecutionContext], RunConfig], Model
        ]
        | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self._model_factory = model_factory
        delegate = tool_executor or PlatformToolExecutor()
        self._tool_executor = ObjectiveControlToolExecutor(delegate)

    async def run(
        self,
        *,
        claim: AgentRunExecutionClaim,
        workflow_context: AgentRunWorkflowContext,
        wait: AgentRunWaitState | None,
        max_steps: int,
        deadline: datetime,
    ) -> ObjectiveFrameworkTurn:
        execution_context = await _build_execution_context(claim)
        await refresh_context_tool_availability(
            execution_context,
            runtime_facts=(
                ToolRuntimeFact.DURABLE_EXECUTION,
                ToolRuntimeFact.AGENT_RUN,
            ),
        )
        published_agent = agent_spec_from_context(execution_context)
        control_tools = _objective_control_tools()
        published_names = {tool.name for tool in published_agent.tools}
        collisions = published_names & {tool.name for tool in control_tools}
        if collisions:
            raise ObjectiveAgentRunInvalid(
                "Published tool names collide with objective run controls."
            )
        agent = published_agent.model_copy(
            update={"tools": (*published_agent.tools, *control_tools)}
        )

        transcript = AgentRunTranscript(
            organization_id=claim.organization_id,
            agent_run_id=claim.run_id,
        )
        replay = await transcript.replay()
        remaining_steps = max_steps - len(replay.command_ids)
        remaining_seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
        if remaining_steps <= 0:
            raise ObjectiveAgentRunExhausted(
                f"Reached the explicit {max_steps}-tool-step limit."
            )
        if remaining_seconds <= 0:
            raise ObjectiveAgentRunExhausted("Reached the explicit objective deadline.")

        config = RunConfig(
            max_turns=remaining_steps,
            request_timeout_seconds=remaining_seconds,
            stream=RunStreaming.DISABLED,
            prompt_caching=(
                RunPromptCaching.ENABLED
                if settings.ENABLE_PROMPT_CACHING
                else RunPromptCaching.DISABLED
            ),
        )
        run_input = with_replay_messages(
            _initial_run_input(claim, execution_context, agent.tools),
            replay,
        )
        if wait is not None:
            run_input = await self._resume_input(
                claim=claim,
                wait=wait,
                run_input=run_input,
                agent=agent,
                execution_context=execution_context,
                config=config,
                workflow_context=workflow_context,
                transcript=transcript,
                command_ids=replay.command_ids,
            )

        captured = AgentRunToolCapture()
        local_context = PlatformRunState(
            conversation_context=execution_context,
            agent_run_id=claim.run_id,
            durable_context=workflow_context,
        )
        bridge = AgentRunTranscriptBridge(
            transcript=transcript,
            local_context=local_context,
            command_ids=replay.command_ids,
        )

        async def capture_model_response(
            run_context: RunContext,
            current_input: RunInput,
            response: ModelResponse,
            tool_calls: tuple[ToolCall, ...],
        ) -> None:
            captured.tool_calls = tool_calls
            await bridge.after_model_response(
                run_context,
                current_input,
                response,
                tool_calls,
            )

        base_model = (
            self._model_factory(local_context, config)
            if self._model_factory is not None
            else ExistingConversationModel(
                local_context,
                llm_resolver=resolve_pinned_llm,
                prompt_caching=to_llm_prompt_caching(config.prompt_caching),
            )
        )
        model = PendingToolCallsModel(
            base_model,
            agent_run_id=claim.run_id,
            pending_calls=replay.pending_calls if wait is None else (),
        )
        result = await FrameworkRunner(
            model,
            tool_executor=self._tool_executor,
            callbacks=RunCallbacks(
                after_model_response=capture_model_response,
                before_tool_call=bridge.before_tool_call,
                after_tool_result=bridge.after_tool_result,
            ),
        ).run(
            agent,
            run_input,
            config=config,
            local_context=local_context,
        )
        if result.status is RunStatus.FAILED:
            replay_after_failure = await transcript.replay()
            if replay_after_failure.pending_calls:
                raise ObjectiveAgentRunRetryable(
                    "Persisted objective tool call requires durable replay."
                )
        return ObjectiveFrameworkTurn(result=result, captured=captured)

    async def _resume_input(
        self,
        *,
        claim: AgentRunExecutionClaim,
        wait: AgentRunWaitState,
        run_input: RunInput,
        agent,
        execution_context: AgentExecutionContext,
        config: RunConfig,
        workflow_context: AgentRunWorkflowContext,
        transcript: AgentRunTranscript,
        command_ids: dict[str, UUID],
    ) -> RunInput:
        wait.require_answered()
        try:
            continuation = parse_run_continuation(wait, ObjectiveRunContinuation)
        except ValueError as error:
            raise ObjectiveAgentRunInvalid(
                "Objective continuation contains an invalid tool call."
            ) from error
        call = continuation.objective.tool_call

        async def resolve_result() -> dict[str, bool]:
            if isinstance(wait, AgentApprovalWaitState):
                response = wait.require_response()
                if response.decision is AgentApprovalDecision.REJECT:
                    result = ToolResult(
                        tool_call_id=call.id,
                        content="The user rejected this tool action.",
                        is_error=True,
                        metadata={"approval_rejected": True},
                    )
                else:
                    command_id = command_ids.get(call.id)
                    if command_id is None:
                        raise ObjectiveAgentRunInvalid(
                            "Approved tool call has no durable command identity."
                        )
                    local_context = PlatformRunState(
                        conversation_context=execution_context,
                        agent_run_id=claim.run_id,
                        durable_context=workflow_context,
                    )
                    bind_agent_run_tool_command(
                        local_context,
                        call=call,
                        command_id=command_id,
                    )
                    result = await self._tool_executor.execute(
                        RunContext(
                            config=config,
                            current_agent=agent,
                            handoff_chain=[agent],
                            local_context=local_context,
                        ),
                        call,
                    )
            else:
                result = ToolResult(
                    tool_call_id=call.id,
                    content=json.dumps(
                        wait.response,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    metadata={
                        "human_input_received": True,
                        "input_request_id": str(wait.request_id),
                    },
                )
            await transcript.record_tool_result(call, result)
            return RunResumeReceipt(
                recorded=True, is_error=result.is_error
            ).model_dump(mode="json")

        receipt = await workflow_context.step(
            key=f"resume:{wait.request_id}",
            version=1,
            operation=resolve_result,
        )
        try:
            RunResumeReceipt.model_validate(receipt)
        except ValidationError as error:
            raise ObjectiveAgentRunInvalid(
                "Objective resume receipt is invalid."
            ) from error
        tool_result = await transcript.tool_result(call)
        if tool_result is None:
            raise ObjectiveAgentRunInvalid("Objective resume result is unavailable.")
        return append_resumed_tool_exchange(run_input, call, tool_result)


class ObjectiveAgentRunExecutor:
    """Execute a direct objective through its exact published agent revision."""

    def __init__(
        self,
        *,
        runner_factory: Callable[[], ObjectiveFrameworkRunner] | None = None,
    ) -> None:
        self._runner_factory = runner_factory or ObjectiveFrameworkRunner

    async def execute(
        self,
        claim: AgentRunExecutionClaim,
        context: AgentRunWorkflowContext,
    ) -> None:
        try:
            await self._execute(claim, context)
        except ObjectiveAgentRunExhausted as error:
            await _discard_compute(claim)
            await _finish_completed(
                claim,
                outcome=AgentRunOutcome.EXHAUSTED,
                result=ObjectiveExhaustionSummary(agent_run_id=claim.run_id),
                reason=str(error),
            )
        except (
            ObjectiveAgentRunInvalid,
            AgentRunTranscriptError,
            NotConfiguredError,
        ) as error:
            await _discard_compute(claim)
            await fail_agent_run(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
                failure_summary=_objective_failure_code(error),
            )
        except SandboxError:
            await _discard_compute(claim)
            await fail_agent_run(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
                failure_summary="sandbox_execution_failed",
            )

    async def _execute(
        self,
        claim: AgentRunExecutionClaim,
        context: AgentRunWorkflowContext,
    ) -> None:
        max_steps, deadline = _validate_claim(claim)
        wait = await load_agent_run_wait(
            organization_id=claim.organization_id,
            run_id=claim.run_id,
        )
        while True:
            if wait is not None:
                payload = await context.await_event(
                    event_name=wait.event_name,
                    key=wait.resume_step_key,
                    version=1,
                )
                _validate_resume_event(payload, claim=claim, wait=wait)

            turn_holder: list[ObjectiveFrameworkTurn] = []

            async def execute_turn() -> None:
                async with start_transaction() as db:
                    resumed_wait = None
                    if wait is not None:
                        resumed_wait = await resume_agent_run_in_transaction(
                            db,
                            organization_id=claim.organization_id,
                            run_id=claim.run_id,
                            request_id=wait.request_id,
                        )
                    turn = await self._runner_factory().run(
                        claim=claim,
                        workflow_context=context,
                        wait=resumed_wait,
                        max_steps=max_steps,
                        deadline=deadline,
                    )
                    await _persist_turn(claim=claim, turn=turn)
                    turn_holder.append(turn)

            await run_with_agent_heartbeat(context, execute_turn)
            turn = turn_holder[0]
            if turn.result.status not in _PAUSE_STATUSES:
                return
            wait = await load_agent_run_wait(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
            )
            if wait is None:
                raise ObjectiveAgentRunInvalid(
                    "Paused objective has no durable input request."
                )


async def _build_execution_context(
    claim: AgentRunExecutionClaim,
) -> AgentExecutionContext:
    resolved = await build_executable_agent_resolver(get_transaction()).resolve_exact(
        organization_id=claim.organization_id,
        agent_id=claim.agent_id,
        revision=claim.agent_revision,
        consumer_kind=TemplateConsumerKind.SANDBOX_AGENT,
    )
    conversation = AgentExecutionScope(
        id=claim.run_id,
        organization_id=claim.organization_id,
        swarm_id=None,
        swarm_revision=None,
        channel=None,
        meta={},
    )
    return AgentExecutionContext(
        conversation=conversation,
        primary_agent=resolved.agent,
        tools=list(resolved.tools),
        system_prompt=resolved.system_prompt
        or resolved.agent.description
        or resolved.agent.name,
        principal_participant=AgentExecutionParticipant(
            id=claim.principal.principal_id,
            entity_id=str(claim.principal.principal_id),
        ),
        agent_participant=AgentExecutionParticipant(
            id=claim.agent_id,
            entity_id=str(claim.agent_id),
            agent_id=claim.agent_id,
            agent_revision=claim.agent_revision,
        ),
        messages=[],
    )


def _initial_run_input(claim, execution_context, tools) -> RunInput:
    instructions = f"{execution_context.system_prompt}\n\n{_CONTROL_INSTRUCTIONS}"
    return RunInput(
        instructions=instructions,
        messages=(
            RunMessage(
                role="user",
                content=claim.goal,
                metadata={
                    "organization_id": str(claim.organization_id),
                    "agent_run_id": str(claim.run_id),
                    "request_id": str(claim.run_id),
                },
            ),
        ),
        tools=tools,
        metadata={
            "organization_id": str(claim.organization_id),
            "agent_run_id": str(claim.run_id),
            "request_id": str(claim.run_id),
        },
    )


def _objective_control_tools() -> tuple[ToolSpec, ToolSpec]:
    return (
        ToolSpec(
            name=_REQUEST_OBJECTIVE_INPUT_TOOL,
            description=(
                "Pause this objective indefinitely for one identified user answer."
            ),
            kind=ToolKind.SYSTEM,
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "minLength": 1},
                    "expected_response_schema": {"type": "object"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
        ),
        ToolSpec(
            name=_COMPLETE_OBJECTIVE_TOOL,
            description=(
                "Conclude this objective with an achieved or unachievable outcome."
            ),
            kind=ToolKind.SYSTEM,
            input_schema={
                "type": "object",
                "properties": {
                    "outcome": {
                        "type": "string",
                        "enum": [
                            AgentRunOutcome.ACHIEVED.value,
                            AgentRunOutcome.UNACHIEVABLE.value,
                        ],
                    },
                    "result": {},
                    "reason": {"type": "string"},
                },
                "required": ["outcome"],
                "additionalProperties": False,
            },
        ),
    )


async def _persist_turn(
    *,
    claim: AgentRunExecutionClaim,
    turn: ObjectiveFrameworkTurn,
) -> None:
    result = turn.result
    if result.status in _PAUSE_STATUSES:
        await _discard_compute(claim)
        kind, prompt, expected_schema, continuation = _pause_fields(
            result,
            turn.captured,
        )
        await pause_agent_run_in_transaction(
            get_transaction(),
            organization_id=claim.organization_id,
            run_id=claim.run_id,
            kind=kind,
            prompt=prompt,
            expected_response_schema=expected_schema,
            continuation=continuation,
        )
        return

    lifecycle, outcome, projected, reason, failure = _terminal_fields(
        claim,
        result,
        turn.captured,
    )
    await _discard_compute(claim)
    await finish_agent_run_in_transaction(
        get_transaction(),
        organization_id=claim.organization_id,
        run_id=claim.run_id,
        lifecycle=lifecycle,
        outcome=outcome,
        result=projected,
        outcome_reason=reason,
        failure_summary=failure,
    )


def _pause_fields(
    result: RunResult,
    captured: AgentRunToolCapture,
) -> tuple[AgentInputRequestKind, str, dict, dict]:
    interruption = result.metadata
    if not isinstance(interruption, (RunApprovalInterruption, RunInputInterruption)):
        raise ObjectiveAgentRunInvalid(
            "Framework pause is missing continuation metadata."
        )
    calls = captured.tool_calls
    if calls is None:
        raise ObjectiveAgentRunInvalid("Framework pause has no captured tool call.")
    call = next(
        (
            candidate
            for candidate in calls
            if candidate.id == interruption.continuation.tool_call_id
        ),
        None,
    )
    if call is None:
        raise ObjectiveAgentRunInvalid(
            "Framework pause continuation differs from its tool call."
        )

    if result.status is RunStatus.WAITING_FOR_APPROVAL and isinstance(
        interruption, RunApprovalInterruption
    ):
        approval = interruption.approval_request
        request = approval
        kind = AgentInputRequestKind.APPROVAL
        prompt = (
            approval.action_summary
            or approval.policy_reason
            or "Approve this objective action?"
        )
        expected_schema = {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": [decision.value for decision in AgentApprovalDecision],
                },
                "comment": {"type": "string"},
            },
            "required": ["decision"],
            "additionalProperties": False,
        }
    elif result.status is RunStatus.WAITING_FOR_INPUT and isinstance(
        interruption, RunInputInterruption
    ):
        details = interruption.input_request
        request = details
        kind = AgentInputRequestKind.INPUT
        prompt = details.prompt or "Provide the requested information."
        expected_schema = details.expected_input_schema
    else:
        raise ObjectiveAgentRunInvalid("Framework result is not a pause.")

    return (
        kind,
        prompt,
        expected_schema,
        ObjectiveRunContinuation(
            framework=interruption.continuation,
            request=request,
            objective=RunToolCallSnapshot(tool_call=call),
        ).model_dump(mode="json"),
    )


def _terminal_fields(
    claim: AgentRunExecutionClaim,
    result: RunResult,
    captured: AgentRunToolCapture,
) -> tuple[
    AgentRunLifecycle,
    AgentRunOutcome,
    dict[str, JsonValue] | None,
    str | None,
    str | None,
]:
    if result.status is RunStatus.COMPLETED:
        completion = _objective_completion(result, captured)
        return (
            AgentRunLifecycle.COMPLETED,
            completion.outcome,
            _objective_result(claim, result, completion.result),
            completion.reason,
            None,
        )
    if result.status in {RunStatus.TIMED_OUT, RunStatus.MAX_TURNS_EXCEEDED}:
        reason = f"Objective execution ended with {result.status.value}."
        return (
            AgentRunLifecycle.COMPLETED,
            AgentRunOutcome.EXHAUSTED,
            _objective_result(claim, result, None),
            reason,
            None,
        )
    return (
        AgentRunLifecycle.FAILED,
        AgentRunOutcome.FAILED,
        None,
        None,
        "objective_framework_failed",
    )


def _objective_completion(
    result: RunResult,
    captured: AgentRunToolCapture,
) -> ObjectiveCompletion:
    result = RunResult.model_validate(result)
    terminal_id = (
        result.metadata.terminal_tool_call_id
        if isinstance(result.metadata, RunTerminalMetadata)
        else None
    )
    calls = captured.tool_calls
    if terminal_id is not None and calls is not None:
        call = next(
            (
                candidate
                for candidate in calls
                if candidate.id == terminal_id
                and candidate.name == _COMPLETE_OBJECTIVE_TOOL
            ),
            None,
        )
        if call is not None:
            return ObjectiveCompletion.from_arguments(call.arguments)
    return ObjectiveCompletion(
        outcome=AgentRunOutcome.ACHIEVED, result=result.final_output
    )


def _objective_result(
    claim: AgentRunExecutionClaim,
    result: RunResult,
    output: JsonValue,
) -> dict[str, JsonValue]:
    try:
        projected = ObjectiveRunSummary(
            agent_run_id=claim.run_id,
            framework_run_id=result.run_id,
            framework_status=result.status,
            output=output,
            usage=result.usage,
        ).model_dump(mode="json")
    except ValidationError as error:
        raise ObjectiveAgentRunInvalid("Objective result is invalid.") from error
    encoded = json.dumps(
        projected,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > _OBJECTIVE_RESULT_LIMIT_BYTES:
        raise ObjectiveAgentRunInvalid("Objective result exceeds 65536 encoded bytes.")
    return projected


async def _finish_completed(
    claim: AgentRunExecutionClaim,
    *,
    outcome: AgentRunOutcome,
    result: ObjectiveExhaustionSummary,
    reason: str | None,
) -> None:
    if result.agent_run_id != claim.run_id:
        raise ObjectiveAgentRunInvalid("Objective result belongs to another run.")
    projected = result.model_dump(mode="json")
    async with start_transaction() as db:
        await finish_agent_run_in_transaction(
            db,
            organization_id=claim.organization_id,
            run_id=claim.run_id,
            lifecycle=AgentRunLifecycle.COMPLETED,
            outcome=outcome,
            result=projected,
            outcome_reason=reason,
        )


def _validate_claim(claim: AgentRunExecutionClaim) -> tuple[int, datetime]:
    if (
        claim.origin_kind is not AgentRunOriginKind.OBJECTIVE
        or claim.origin_message_id is not None
        or claim.origin_schedule_run_id is not None
    ):
        raise ObjectiveAgentRunInvalid(
            "Objective executor received a different origin."
        )
    try:
        run_context = ObjectiveRunContext.model_validate_json(
            json.dumps(claim.context_manifest, allow_nan=False)
        )
    except ValueError as error:
        raise ObjectiveAgentRunInvalid("Objective context is invalid.") from error
    return run_context.max_steps, run_context.deadline


def _validate_resume_event(
    payload: object,
    *,
    claim: AgentRunExecutionClaim,
    wait: AgentRunWaitState,
) -> None:
    try:
        AgentRunInputEvent(
            organization_id=claim.organization_id,
            run_id=claim.run_id,
            request_id=wait.request_id,
        ).require_matching_payload(payload)
    except ValueError:
        raise ObjectiveAgentRunInvalid(
            "Durable input event does not match the objective request."
        ) from None


def _objective_failure_code(error: Exception) -> str:
    if isinstance(error, NotConfiguredError):
        return "objective_provider_not_configured"
    if isinstance(error, AgentRunTranscriptError):
        return "objective_transcript_invalid"
    return "objective_run_invalid"


def _required_text(
    source: Mapping[str, object],
    key: str,
    *,
    max_chars: int,
) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ObjectiveAgentRunInvalid(f"{key} must be text.")
    if len(value) > max_chars:
        raise ObjectiveAgentRunInvalid(f"{key} exceeds its character ceiling.")
    return value


async def _discard_compute(claim: AgentRunExecutionClaim) -> None:
    await discard_live_run_sessions(
        organization_id=claim.organization_id,
        agent_run_id=claim.run_id,
    )


__all__ = [
    "ObjectiveAgentRunExecutor",
    "ObjectiveAgentRunInvalid",
    "ObjectiveFrameworkRunner",
]
