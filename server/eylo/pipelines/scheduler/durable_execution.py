"""Durable execution for one schedule-occurrence AgentRun."""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

from pydantic import JsonValue, ValidationError
from sqlalchemy import select

from eylo.common.config import settings
from eylo.common.contracts.tool_availability import ToolRuntimeFact
from eylo.common.database import get_transaction, start_transaction
from eylo.common.revisions import RevisionAvailability
from eylo.framework.agents.config import RunConfig, RunPromptCaching, RunStreaming
from eylo.framework.agents.context import RunContext, RunInput, RunMessage
from eylo.framework.agents.hooks import RunCallbacks
from eylo.framework.agents.interruptions import (
    RunApprovalInterruption,
    RunInputInterruption,
)
from eylo.framework.agents.model import Model, ModelResponse
from eylo.framework.agents.result import RunResult, RunStatus
from eylo.framework.agents.runner import FrameworkRunner
from eylo.framework.agents.tool import ToolCall, ToolResult
from eylo.modules.agent_runs.domain import (
    AgentApprovalDecision,
    AgentInputRequestKind,
    AgentRunLifecycle,
    AgentRunOriginKind,
    AgentRunOutcome,
)
from eylo.modules.agent_runs.service import (
    accept_agent_run_cancellation,
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
from eylo.modules.scheduler.models import ScheduleRevisionModel, ScheduleRunModel
from eylo.modules.scheduler.run_context import ScheduleRunContext
from eylo.modules.templates.domain import TemplateConsumerKind
from eylo.pipelines.agent_execution_context import (
    AgentExecutionContext,
    AgentExecutionParticipant,
    AgentExecutionScope,
    PlatformRunState,
)
from eylo.pipelines.agent_run_continuations import (
    RunResumeReceipt,
    RunToolCallSnapshot,
    ScheduledRunContinuation,
    parse_run_continuation,
)
from eylo.pipelines.agent_run_heartbeat import run_with_agent_heartbeat
from eylo.pipelines.agent_run_results import ScheduledRunSummary
from eylo.pipelines.agent_run_tools import bind_agent_run_tool_command
from eylo.pipelines.agent_run_transcript import (
    AgentRunToolCapture,
    AgentRunTranscript,
    AgentRunTranscriptBridge,
    PendingToolCallsModel,
    append_resumed_tool_exchange,
    with_replay_messages,
)
from eylo.pipelines.agents import build_executable_agent_resolver
from eylo.pipelines.conversation.conversation_runner import ExistingConversationModel
from eylo.pipelines.conversation.domain import agent_spec_from_context
from eylo.pipelines.conversation.tool_executor import PlatformToolExecutor
from eylo.pipelines.llm.runtime import to_llm_prompt_caching
from eylo.pipelines.system_tools.availability import (
    refresh_context_tool_availability,
)

_PAUSE_STATUSES = {
    RunStatus.WAITING_FOR_INPUT,
    RunStatus.WAITING_FOR_APPROVAL,
}


class ScheduledAgentRunInvalid(Exception):
    """A schedule-backed run no longer has valid immutable input."""


class ScheduledAgentRunRetryable(Exception):
    """A scheduled tool call is persisted but has no canonical result yet."""


class ScheduledAgentRunCancelled(Exception):
    """The exact schedule revision withdrew its filed work."""


class ScheduledFrameworkRunner:
    """Resolve exact agent authority and run one non-conversation framework turn."""

    def __init__(
        self,
        *,
        model_factory: Callable[
            [PlatformRunState[AgentExecutionContext], RunConfig], Model
        ]
        | None = None,
        tool_executor=None,
    ) -> None:
        self._model_factory = model_factory
        self._tool_executor = tool_executor or PlatformToolExecutor()

    async def run(
        self,
        *,
        claim: AgentRunExecutionClaim,
        workflow_context: AgentRunWorkflowContext,
        wait: AgentRunWaitState | None,
    ) -> RunResult:
        execution_context = await _build_execution_context(claim)
        await refresh_context_tool_availability(
            execution_context,
            runtime_facts=(
                ToolRuntimeFact.DURABLE_EXECUTION,
                ToolRuntimeFact.AGENT_RUN,
            ),
        )
        agent = agent_spec_from_context(execution_context)
        config = RunConfig(
            stream=RunStreaming.DISABLED,
            prompt_caching=(
                RunPromptCaching.ENABLED
                if settings.ENABLE_PROMPT_CACHING
                else RunPromptCaching.DISABLED
            ),
        )
        transcript = AgentRunTranscript(
            organization_id=claim.organization_id,
            agent_run_id=claim.run_id,
        )
        replay = await transcript.replay()
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
            _context: RunContext,
            run_input: RunInput,
            response: ModelResponse,
            tool_calls: tuple[ToolCall, ...],
        ) -> None:
            captured.tool_calls = tool_calls
            await bridge.after_model_response(
                _context,
                run_input,
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
        runner = FrameworkRunner(
            model,
            tool_executor=self._tool_executor,
            callbacks=RunCallbacks(
                after_model_response=capture_model_response,
                before_tool_call=bridge.before_tool_call,
                after_tool_result=bridge.after_tool_result,
            ),
        )
        result = await runner.run(
            agent,
            run_input,
            config=config,
            local_context=local_context,
        )
        if result.status is RunStatus.FAILED:
            replay_after_failure = await transcript.replay()
            if replay_after_failure.pending_calls:
                raise ScheduledAgentRunRetryable(
                    "Persisted scheduled tool call requires durable replay."
                )
        await _persist_result(
            claim=claim,
            result=result,
            captured=captured,
        )
        return result

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
            continuation = parse_run_continuation(wait, ScheduledRunContinuation)
        except ValueError as error:
            raise ScheduledAgentRunInvalid(
                "Scheduled AgentRun continuation contains an invalid tool call."
            ) from error
        call = continuation.scheduled.tool_call

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
                        raise ScheduledAgentRunInvalid(
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
            return RunResumeReceipt(recorded=True, is_error=result.is_error).model_dump(
                mode="json"
            )

        checkpointed = await workflow_context.step(
            key=f"resume:{wait.request_id}",
            version=1,
            operation=resolve_result,
        )
        try:
            RunResumeReceipt.model_validate(checkpointed)
        except ValidationError as error:
            raise ScheduledAgentRunInvalid(
                "Scheduled AgentRun resume receipt is invalid."
            ) from error
        tool_result = await transcript.tool_result(call)
        if tool_result is None:
            raise ScheduledAgentRunInvalid(
                "Scheduled AgentRun resume result is unavailable."
            )
        return append_resumed_tool_exchange(run_input, call, tool_result)


class ScheduledAgentRunExecutor:
    """Execute schedule-origin claims and preserve AgentRun wait semantics."""

    def __init__(
        self,
        *,
        runner_factory: Callable[[], ScheduledFrameworkRunner] | None = None,
    ) -> None:
        self._runner_factory = runner_factory or ScheduledFrameworkRunner

    async def execute(
        self,
        claim: AgentRunExecutionClaim,
        context: AgentRunWorkflowContext,
    ) -> None:
        try:
            await _validate_occurrence(claim)
        except ScheduledAgentRunCancelled:
            await accept_agent_run_cancellation(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
            )
            return
        except ScheduledAgentRunInvalid:
            await fail_agent_run(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
                failure_summary="scheduled_agent_run_invalid",
            )
            return

        wait = await load_agent_run_wait(
            organization_id=claim.organization_id,
            run_id=claim.run_id,
        )
        while True:
            if wait is not None:
                event_payload = await context.await_event(
                    event_name=wait.event_name,
                    key=wait.resume_step_key,
                    version=1,
                )
                _validate_resume_event(event_payload, claim=claim, wait=wait)

            result_holder: list[RunResult] = []

            async def execute_turn() -> None:
                async with start_transaction() as session:
                    resumed_wait = None
                    if wait is not None:
                        resumed_wait = await resume_agent_run_in_transaction(
                            session,
                            organization_id=claim.organization_id,
                            run_id=claim.run_id,
                            request_id=wait.request_id,
                        )
                    result_holder.append(
                        await self._runner_factory().run(
                            claim=claim,
                            workflow_context=context,
                            wait=resumed_wait,
                        )
                    )

            await run_with_agent_heartbeat(context, execute_turn)
            result = result_holder[0]
            if result.status not in _PAUSE_STATUSES:
                return
            wait = await load_agent_run_wait(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
            )
            if wait is None:
                raise ScheduledAgentRunInvalid(
                    "Paused scheduled AgentRun has no durable input request."
                )


async def _build_execution_context(
    claim: AgentRunExecutionClaim,
) -> AgentExecutionContext:
    resolver = build_executable_agent_resolver(get_transaction())
    resolved = await resolver.resolve_exact(
        organization_id=claim.organization_id,
        agent_id=claim.agent_id,
        revision=claim.agent_revision,
        consumer_kind=TemplateConsumerKind.BACKGROUND_AGENT,
    )
    if claim.origin_schedule_run_id is None:
        raise ScheduledAgentRunInvalid("Scheduled run has no originating occurrence.")
    conversation = AgentExecutionScope(
        id=claim.origin_schedule_run_id,
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
    return RunInput(
        instructions=execution_context.system_prompt,
        messages=(
            RunMessage(
                role="user",
                content=claim.goal,
                metadata={
                    "organization_id": str(claim.organization_id),
                    "schedule_run_id": str(claim.origin_schedule_run_id),
                    "request_id": str(claim.origin_schedule_run_id),
                },
            ),
        ),
        tools=tools,
        metadata={
            "organization_id": str(claim.organization_id),
            "schedule_run_id": str(claim.origin_schedule_run_id),
            "request_id": str(claim.origin_schedule_run_id),
        },
    )


async def _persist_result(
    *,
    claim: AgentRunExecutionClaim,
    result: RunResult,
    captured: AgentRunToolCapture,
) -> None:
    if result.status in _PAUSE_STATUSES:
        kind, prompt, expected_schema, continuation = _pause_fields(result, captured)
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

    lifecycle, outcome, run_result, reason, failure = _terminal_fields(claim, result)
    await finish_agent_run_in_transaction(
        get_transaction(),
        organization_id=claim.organization_id,
        run_id=claim.run_id,
        lifecycle=lifecycle,
        outcome=outcome,
        result=run_result,
        outcome_reason=reason,
        failure_summary=failure,
    )


def _pause_fields(
    result: RunResult,
    captured: AgentRunToolCapture,
) -> tuple[AgentInputRequestKind, str, dict[str, JsonValue], dict[str, JsonValue]]:
    interruption = result.metadata
    if not isinstance(interruption, (RunApprovalInterruption, RunInputInterruption)):
        raise ScheduledAgentRunInvalid(
            "Framework pause is missing continuation metadata."
        )
    calls = captured.tool_calls
    if calls is None:
        raise ScheduledAgentRunInvalid("Framework pause has no captured tool call.")
    call = next(
        (
            candidate
            for candidate in calls
            if candidate.id == interruption.continuation.tool_call_id
        ),
        None,
    )
    if call is None:
        raise ScheduledAgentRunInvalid(
            "Framework pause continuation differs from its tool call."
        )

    expected_schema: dict[str, JsonValue]
    if result.status is RunStatus.WAITING_FOR_APPROVAL and isinstance(
        interruption, RunApprovalInterruption
    ):
        approval = interruption.approval_request
        request = approval
        kind = AgentInputRequestKind.APPROVAL
        prompt = (
            approval.action_summary
            or approval.policy_reason
            or "Approve this scheduled agent action?"
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
        raise ScheduledAgentRunInvalid("Framework result is not a pause.")

    return (
        kind,
        prompt,
        expected_schema,
        ScheduledRunContinuation(
            framework=interruption.continuation,
            request=request,
            scheduled=RunToolCallSnapshot(tool_call=call),
        ).model_dump(mode="json"),
    )


def _terminal_fields(
    claim: AgentRunExecutionClaim,
    result: RunResult,
) -> tuple[
    AgentRunLifecycle,
    AgentRunOutcome,
    dict[str, JsonValue] | None,
    str | None,
    str | None,
]:
    if result.status is RunStatus.COMPLETED:
        return (
            AgentRunLifecycle.COMPLETED,
            AgentRunOutcome.ACHIEVED,
            _run_result(claim, result),
            None,
            None,
        )
    if result.status in {RunStatus.TIMED_OUT, RunStatus.MAX_TURNS_EXCEEDED}:
        reason = f"Scheduled agent execution ended with {result.status.value}."
        return (
            AgentRunLifecycle.COMPLETED,
            AgentRunOutcome.EXHAUSTED,
            _run_result(claim, result),
            reason,
            None,
        )
    return (
        AgentRunLifecycle.FAILED,
        AgentRunOutcome.FAILED,
        None,
        None,
        f"Scheduled agent execution ended with {result.status.value}.",
    )


def _run_result(
    claim: AgentRunExecutionClaim, result: RunResult
) -> dict[str, JsonValue]:
    if claim.origin_schedule_run_id is None:
        raise ScheduledAgentRunInvalid("Scheduled result has no occurrence identity.")
    try:
        projected = ScheduledRunSummary(
            schedule_run_id=claim.origin_schedule_run_id,
            framework_run_id=result.run_id,
            framework_status=result.status,
            output=result.final_output,
            usage=result.usage,
        ).model_dump(mode="json")
    except ValidationError as error:
        raise ScheduledAgentRunInvalid("Scheduled result is invalid.") from error
    if len(json.dumps(projected, separators=(",", ":")).encode("utf-8")) > 65536:
        raise ScheduledAgentRunInvalid(
            "Scheduled agent result exceeds the canonical 65536-byte limit."
        )
    return projected


async def _validate_occurrence(claim: AgentRunExecutionClaim) -> None:
    if (
        claim.origin_kind is not AgentRunOriginKind.SCHEDULE_OCCURRENCE
        or claim.origin_schedule_run_id is None
    ):
        raise ScheduledAgentRunInvalid(
            "Scheduled execution requires a schedule occurrence origin."
        )
    try:
        run_context = ScheduleRunContext.model_validate_json(
            json.dumps(claim.context_manifest, allow_nan=False)
        )
    except ValueError as error:
        raise ScheduledAgentRunInvalid("Schedule context is invalid.") from error
    async with start_transaction(ro=True) as session:
        occurrence = await session.scalar(
            select(ScheduleRunModel).where(
                ScheduleRunModel.id == claim.origin_schedule_run_id,
                ScheduleRunModel.organization_id == claim.organization_id,
                ScheduleRunModel.deleted.is_(False),
            )
        )
        if occurrence is None:
            raise ScheduledAgentRunInvalid("Schedule occurrence is unavailable.")
        revision = await session.scalar(
            select(ScheduleRevisionModel).where(
                ScheduleRevisionModel.schedule_id == occurrence.schedule_id,
                ScheduleRevisionModel.revision == occurrence.schedule_revision,
                ScheduleRevisionModel.organization_id == claim.organization_id,
                ScheduleRevisionModel.deleted.is_(False),
            )
        )
    if revision is None or revision.availability != RevisionAvailability.PUBLISHED:
        raise ScheduledAgentRunCancelled
    if (
        occurrence.agent_id != claim.agent_id
        or occurrence.agent_revision != claim.agent_revision
        or run_context.schedule_run_id != occurrence.id
        or run_context.schedule_id != occurrence.schedule_id
        or run_context.schedule_revision != occurrence.schedule_revision
    ):
        raise ScheduledAgentRunInvalid(
            "AgentRun does not match its immutable schedule occurrence."
        )


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
        raise ScheduledAgentRunInvalid(
            "Durable input event does not match the identified request."
        ) from None


__all__ = ["ScheduledAgentRunExecutor", "ScheduledFrameworkRunner"]
