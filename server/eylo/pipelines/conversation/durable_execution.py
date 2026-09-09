"""Durable AgentRun executor for one message-backed conversation turn."""

from __future__ import annotations

from collections.abc import Callable

from eylo.common.config import settings
from eylo.common.database import start_transaction
from eylo.framework.agents import RunConfig as FrameworkRunConfig
from eylo.framework.agents.config import RunPromptCaching, RunStreaming
from eylo.framework.agents.result import RunStatus
from eylo.modules.agent_runs.domain import AgentRunOriginKind
from eylo.modules.agent_runs.service import (
    AgentRunWaitState,
    load_agent_run_wait,
    resume_agent_run_in_transaction,
)
from eylo.modules.agent_runs.waits import AgentRunInputEvent
from eylo.modules.agent_runs.workflow import (
    AgentRunExecutionClaim,
    AgentRunWorkflowContext,
)
from eylo.modules.conversations.repositories.messages import (
    MessageAgentRunRepository,
)
from eylo.modules.conversations.schemas.messages import (
    MessageContentKind,
    MessageInDb,
    MessageKind,
)
from eylo.pipelines.agent_run_heartbeat import run_with_agent_heartbeat
from eylo.pipelines.parallel_agents import ParallelTaskAgentRunExecutor

from .conversation_runner import FrameworkConversationRunner
from .run_failure import fail_agent_run_and_converge_message


class ConversationAgentRunInvalid(Exception):
    """A message-backed run no longer has valid immutable input."""


class ConversationAgentRunExecutor:
    """Reload IDs, execute the framework loop, persist one canonical result."""

    def __init__(
        self,
        *,
        runner_factory: Callable[[], FrameworkConversationRunner] | None = None,
        parallel_executor: ParallelTaskAgentRunExecutor | None = None,
    ) -> None:
        self._runner_factory = runner_factory or FrameworkConversationRunner
        self._parallel_executor = parallel_executor or ParallelTaskAgentRunExecutor()

    async def execute(
        self,
        claim: AgentRunExecutionClaim,
        context: AgentRunWorkflowContext,
    ) -> None:
        try:
            origin = await _load_origin_message(claim)
        except ConversationAgentRunInvalid:
            await fail_agent_run_and_converge_message(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
                failure_summary="message_agent_run_invalid",
            )
            return

        if (
            origin.kind == MessageKind.SYSTEM
            and origin.content_kind == MessageContentKind.TASK
        ):
            await self._parallel_executor.execute_origin(claim, context, origin)
            return
        if origin.kind != MessageKind.USER:
            await fail_agent_run_and_converge_message(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
                failure_summary="Message AgentRun origin is not executable.",
            )
            return

        config = FrameworkRunConfig(
            stream=(
                RunStreaming.ENABLED
                if settings.ENABLE_LLM_STREAMING
                else RunStreaming.DISABLED
            ),
            prompt_caching=(
                RunPromptCaching.ENABLED
                if settings.ENABLE_PROMPT_CACHING
                else RunPromptCaching.DISABLED
            ),
        )
        wait = await load_agent_run_wait(
            organization_id=claim.organization_id,
            run_id=claim.run_id,
        )
        while True:
            result_holder: list = []
            resumed_wait = None

            if wait is not None:
                event_payload = await context.await_event(
                    event_name=wait.event_name,
                    key=wait.resume_step_key,
                    version=1,
                )
                _validate_resume_event(event_payload, claim=claim, wait=wait)
                async with start_transaction() as session:
                    resumed_wait = await resume_agent_run_in_transaction(
                        session,
                        organization_id=claim.organization_id,
                        run_id=claim.run_id,
                        request_id=wait.request_id,
                    )

            async def run_turn() -> None:
                async with start_transaction():
                    runner = self._runner_factory()
                    if wait is None:
                        result = await runner.run(
                            conversation_id=origin.conversation_id,
                            user_message=origin,
                            config=config,
                            agent_run_id=claim.run_id,
                            expected_agent_id=claim.agent_id,
                            expected_agent_revision=claim.agent_revision,
                            durable_context=context,
                        )
                    else:
                        if resumed_wait is None:
                            raise ConversationAgentRunInvalid(
                                "Answered wait was not resumed before execution."
                            )
                        result = await runner.resume(
                            conversation_id=origin.conversation_id,
                            user_message=origin,
                            wait=resumed_wait,
                            config=config,
                            agent_run_id=claim.run_id,
                            expected_agent_id=claim.agent_id,
                            expected_agent_revision=claim.agent_revision,
                            durable_context=context,
                        )
                    result_holder.append(result)

            await run_with_agent_heartbeat(context, run_turn)
            result = result_holder[0]
            if result.status not in {
                RunStatus.WAITING_FOR_INPUT,
                RunStatus.WAITING_FOR_APPROVAL,
            }:
                return
            wait = await load_agent_run_wait(
                organization_id=claim.organization_id,
                run_id=claim.run_id,
            )
            if wait is None:
                raise ConversationAgentRunInvalid(
                    "Paused conversation has no durable input request."
                )


async def _load_origin_message(claim: AgentRunExecutionClaim) -> MessageInDb:
    if (
        claim.origin_kind is not AgentRunOriginKind.MESSAGE
        or claim.origin_message_id is None
    ):
        raise ConversationAgentRunInvalid(
            "Conversation execution requires a message origin."
        )

    async with start_transaction(ro=True) as session:
        origin = await MessageAgentRunRepository(session).get_origin_message(
            organization_id=claim.organization_id,
            message_id=claim.origin_message_id,
        )
        if origin is None:
            raise ConversationAgentRunInvalid(
                "The AgentRun origin message is unavailable."
            )
        message = MessageInDb.model_validate(origin)

    expected_conversation_id = claim.context_manifest.get("conversation_id")
    if expected_conversation_id != str(message.conversation_id):
        raise ConversationAgentRunInvalid(
            "The AgentRun context no longer matches its origin conversation."
        )
    return message


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
        raise ConversationAgentRunInvalid(
            "Durable input event does not match the identified request."
        ) from None


__all__ = ["ConversationAgentRunExecutor"]
