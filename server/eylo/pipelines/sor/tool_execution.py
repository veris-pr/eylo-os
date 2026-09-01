"""Execute profile-native SOR tools under exact Agent and source authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import ValidationError

from eylo.common.database import start_transaction
from eylo.modules.agent_runs.service import (
    AgentRunConflict,
    pause_agent_run_for_tool_in_transaction,
    resume_agent_run_from_tool_in_transaction,
)
from eylo.pipelines.outbound.durable_execution import DurableStepContext
from eylo.sor.knowledge.agent_reads import shape_knowledge_tool_response
from eylo.sor.runtime.agent_reads import SorAgentReadError, read_agent_view
from eylo.sor.runtime.authority import SorAuthorityError, resolve_agent_sources
from eylo.sor.runtime.commands import (
    SOR_COMMAND_WAIT_OWNER_KIND,
    SorCommandAuthorizationError,
    file_sor_command,
    read_sor_command_receipt,
    sor_command_terminal_event,
)
from eylo.sor.runtime.tools import (
    SorDocumentGetInput,
    SorReadSelectionInput,
    mutation_tool_input_model,
    read_tool_input_model,
    resolve_sor_tool,
)
from eylo.sor.runtime.work import SorWorkConflict, SorWorkNotFound
from eylo.sor.shared.contracts import (
    SorCommandState,
    SorProfile,
    SorToolEffect,
    SorToolSpec,
)
from eylo.sor.shared.secrets import SorSecretEnvelopeError
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
    SorProjectionError,
)

if TYPE_CHECKING:
    from eylo.modules.conversations.schemas.conversations import ConversationContext


@dataclass(frozen=True, slots=True)
class SorToolExecutionOutcome:
    """Safe model-facing result and private dispatch metadata."""

    content: dict[str, Any] = field(repr=False)
    is_error: bool
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", dict(self.content))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


async def execute_sor_read_tool(
    *,
    tool_name: str,
    tool_input: Mapping[str, Any],
    conversation_context: ConversationContext,
) -> SorToolExecutionOutcome:
    """Read the Agent-safe canonical projection for one exact published tool."""
    resolved = resolve_sor_tool(tool_name)
    if resolved is None or resolved[1].effect is not SorToolEffect.READ:
        return _error_outcome("sor_tool_unavailable")
    profile, spec = resolved
    try:
        command = read_tool_input_model(spec).model_validate(dict(tool_input))
        entity = _selected_entity(spec, getattr(command, "entity", None))
        _require_read_identity_when_needed(spec, command)
        agent_id, agent_revision = _agent_identity(conversation_context)
        organization_id = UUID(str(conversation_context.conversation.organization_id))
        async with start_transaction(ro=True) as session:
            projection = await read_agent_view(
                session,
                organization_id=organization_id,
                agent_id=agent_id,
                agent_revision=agent_revision,
                profile=profile,
                entity=entity,
                search=command.search,
                source_ids=command.source_ids,
                record_id=command.record_id,
                external_key=command.external_key,
                required_tool=tool_name,
                limit=command.limit,
                cursor=command.cursor,
                sort_by=command.sort_by,
                sort_direction=command.sort_direction,
                include_relations="relation" in spec.entities,
            )
    except ValidationError:
        return _error_outcome("sor_tool_input_invalid")
    except (SorAgentReadError, SorAuthorityError, ValueError) as error:
        return _error_outcome(_safe_error_code(error))

    data = (
        shape_knowledge_tool_response(
            projection,
            tool_name=tool_name,
            search=command.search,
            content_offset=(
                command.content_offset
                if isinstance(command, SorDocumentGetInput)
                else 0
            ),
            content_limit_chars=(
                command.content_limit_chars
                if isinstance(command, SorDocumentGetInput)
                else 20_000
            ),
        )
        if profile is SorProfile.KNOWLEDGE
        else projection.model_dump(mode="json")
    )
    if "describe" in tool_name:
        data["items"] = []
        data["next_cursor"] = None
        data["has_more"] = False
    return SorToolExecutionOutcome(
        content={"kind": "sor_result", "data": data},
        is_error=False,
        metadata={
            "sor_execution": True,
            "profile": profile.value,
            "tool": tool_name,
            "effect": SorToolEffect.READ.value,
        },
    )


async def execute_sor_mutation_tool(
    *,
    tool_name: str,
    tool_call_id: str,
    tool_input: Mapping[str, Any],
    conversation_context: ConversationContext,
    agent_run_id: UUID,
    durable_context: DurableStepContext,
) -> SorToolExecutionOutcome:
    """File one command, wait without holding capacity, then return its receipt."""
    resolved = resolve_sor_tool(tool_name)
    if resolved is None or resolved[1].effect is not SorToolEffect.MUTATION:
        return _error_outcome("sor_tool_unavailable")
    profile, spec = resolved
    try:
        command = mutation_tool_input_model(profile=profile, spec=spec).model_validate(
            dict(tool_input)
        )
        entity = _selected_entity(spec, None)
        agent_id, agent_revision = _agent_identity(conversation_context)
        organization_id = UUID(str(conversation_context.conversation.organization_id))
        source = await _resolve_mutation_source(
            organization_id=organization_id,
            agent_id=agent_id,
            agent_revision=agent_revision,
            profile=profile,
            spec=spec,
            entity=entity,
            source_id=command.source_id,
        )
    except ValidationError:
        return _error_outcome("sor_tool_input_invalid")
    except (SorAuthorityError, ValueError) as error:
        return _error_outcome(_safe_error_code(error))

    if isinstance(source, SorToolExecutionOutcome):
        return source

    try:
        filed = await file_sor_command(
            organization_id=organization_id,
            source_id=source["source_id"],
            profile_tool=tool_name,
            agent_id=agent_id,
            agent_revision=agent_revision,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            payload=command.payload,
            target_record_id=command.target_record_id,
            enforce_target_revision=command.target_record_id is not None,
        )
        receipt = await read_sor_command_receipt(
            organization_id=organization_id,
            command_id=filed.command_id,
        )
        if not _terminal(receipt):
            async with start_transaction() as session:
                await pause_agent_run_for_tool_in_transaction(
                    session,
                    organization_id=organization_id,
                    run_id=agent_run_id,
                    owner_kind=SOR_COMMAND_WAIT_OWNER_KIND,
                    owner_id=filed.command_id,
                )
            await durable_context.await_event(
                sor_command_terminal_event(filed.command_id),
                step_name=f"sor-command:{filed.command_id}:await-terminal:v1",
                timeout=None,
            )
            receipt = await read_sor_command_receipt(
                organization_id=organization_id,
                command_id=filed.command_id,
            )
        if not _terminal(receipt):
            raise SorConfigurationError("SOR command woke before becoming terminal.")
        _require_receipt_identity(
            receipt,
            agent_run_id=agent_run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
        async with start_transaction() as session:
            await resume_agent_run_from_tool_in_transaction(
                session,
                organization_id=organization_id,
                run_id=agent_run_id,
                owner_kind=SOR_COMMAND_WAIT_OWNER_KIND,
                owner_id=filed.command_id,
            )
    except (
        AgentRunConflict,
        KeyError,
        SorAuthorityError,
        SorCommandAuthorizationError,
        SorConfigurationError,
        SorConflictError,
        SorNotFoundError,
        SorProjectionError,
        SorSecretEnvelopeError,
        SorWorkConflict,
        SorWorkNotFound,
    ) as error:
        return _error_outcome(_safe_error_code(error))

    state = SorCommandState(str(receipt["state"]))
    succeeded = state is SorCommandState.SUCCEEDED
    return SorToolExecutionOutcome(
        content={
            "kind": "sor_command_result" if succeeded else "sor_command_error",
            "data": receipt if succeeded else None,
            "error": None if succeeded else receipt.get("safe_error_category"),
            "message": None if succeeded else receipt.get("safe_error_summary"),
        },
        is_error=not succeeded,
        metadata={
            "sor_execution": True,
            "profile": profile.value,
            "tool": tool_name,
            "effect": SorToolEffect.MUTATION.value,
            "command_id": str(filed.command_id),
            "command_state": state.value,
        },
    )


async def _resolve_mutation_source(
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_revision: int,
    profile: SorProfile,
    spec: SorToolSpec,
    entity: str,
    source_id: UUID | None,
) -> dict[str, Any] | SorToolExecutionOutcome:
    requested = (source_id,) if source_id is not None else ()
    async with start_transaction(ro=True) as session:
        sources = await resolve_agent_sources(
            session,
            organization_id=organization_id,
            agent_id=agent_id,
            agent_revision=agent_revision,
            profile=profile,
            tool_name=spec.name,
            requested_source_ids=requested,
            effect=SorToolEffect.MUTATION,
            entity=entity,
        )
    if len(sources) == 1:
        source = sources[0]
        return {
            "source_id": source.source_id,
            "name": source.name,
            "vendor_key": source.vendor_key,
        }
    if not sources:
        return _error_outcome("sor_source_unavailable")
    return SorToolExecutionOutcome(
        content={
            "kind": "sor_source_selection_required",
            "error": "sor_source_selection_required",
            "sources": [
                {
                    "source_id": str(source.source_id),
                    "name": source.name,
                    "vendor_key": source.vendor_key,
                }
                for source in sources
            ],
        },
        is_error=True,
        metadata={"sor_execution": True, "source_selection_required": True},
    )


def _selected_entity(spec: SorToolSpec, requested: str | None) -> str:
    entity = requested or spec.primary_entity
    if entity not in spec.target_entities:
        raise ValueError("SOR tool cannot access the requested entity.")
    return entity


def _require_read_identity_when_needed(
    spec: SorToolSpec,
    command: SorReadSelectionInput,
) -> None:
    if "_get" not in spec.name:
        return
    if command.record_id is None and command.external_key is None:
        raise ValueError("This SOR read requires a record ID or external key.")


def _agent_identity(context: ConversationContext) -> tuple[UUID, int]:
    agent = context.primary_agent
    participant = context.get_primary_agent()
    revision = getattr(participant, "agent_revision", None)
    if agent is None or participant is None or not isinstance(revision, int):
        raise ValueError("SOR execution requires a pinned primary Agent revision.")
    return UUID(str(agent.id)), revision


def _terminal(receipt: Mapping[str, Any]) -> bool:
    try:
        state = SorCommandState(str(receipt["state"]))
    except (KeyError, TypeError, ValueError):
        return False
    return state in {
        SorCommandState.SUCCEEDED,
        SorCommandState.FAILED,
        SorCommandState.CONFLICT,
        SorCommandState.CANCELLED,
    }


def _require_receipt_identity(
    receipt: Mapping[str, Any],
    *,
    agent_run_id: UUID,
    tool_call_id: str,
    tool_name: str,
) -> None:
    if (
        receipt.get("agent_run_id") != str(agent_run_id)
        or receipt.get("tool_call_id") != tool_call_id
        or receipt.get("profile_tool") != tool_name
    ):
        raise SorConfigurationError("SOR command receipt identity changed.")


def _safe_error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code.lower()
    if isinstance(error, AgentRunConflict):
        return "agent_run_conflict"
    if isinstance(error, SorNotFoundError):
        return "sor_resource_unavailable"
    return "sor_request_invalid"


def _error_outcome(code: str) -> SorToolExecutionOutcome:
    return SorToolExecutionOutcome(
        content={"kind": "sor_error", "error": code},
        is_error=True,
        metadata={"sor_execution": True, "error_code": code},
    )


__all__ = [
    "SorToolExecutionOutcome",
    "execute_sor_mutation_tool",
    "execute_sor_read_tool",
]
