"""File PII-safe organization-visible facts for successful Agent SOR actions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.events.durable.domain import DurableEventEnvelope
from eylo.events.durable.service import DurableEventService
from eylo.sor.crm.contracts import CrmToolName
from eylo.sor.knowledge.contracts import KnowledgeToolName
from eylo.sor.shared.contracts import SorProfile, SorProjectionDisposition
from eylo.sor.shared.models import SorCommandModel, SorSourceModel
from eylo.sor.support.contracts import SupportToolName
from eylo.sor.ticketing.contracts import TicketingToolName

SOR_RECORD_SUBJECT_TYPE = "sor.record"
SOR_CONNECTION_SUBJECT_TYPE = "sor.connection"
SOR_ACTION_EVENT_VERSION = 1

SOR_CONNECTION_EVENT_SEQUENCE_MAX = 128


class SorConnectionEventType(StrEnum):
    CONNECTED = "sor.connection.connected"
    REAUTH_REQUIRED = "sor.connection.reauth_required"
    REVOKED = "sor.connection.revoked"


class _ActionEventType(StrEnum):
    CONTACT_CREATED = "crm.contact.created"
    CONTACT_UPDATED = "crm.contact.updated"
    DEAL_CREATED = "crm.deal.created"
    DEAL_UPDATED = "crm.deal.updated"
    DEAL_STAGE_CHANGED = "crm.deal.stage_changed"
    ISSUE_CREATED = "issue.created"
    ISSUE_UPDATED = "issue.updated"
    ISSUE_TRANSITIONED = "issue.transitioned"
    ISSUE_COMMENTED = "issue.commented"
    TICKET_OPENED = "support.ticket.opened"
    TICKET_UPDATED = "support.ticket.updated"
    TICKET_ASSIGNED = "support.ticket.assigned"
    TICKET_REPLIED = "support.ticket.replied"
    TICKET_NOTED = "support.ticket.noted"
    TICKET_CLOSED = "support.ticket.closed"
    DOCUMENT_CREATED = "docs.document.created"
    DOCUMENT_UPDATED = "docs.document.updated"
    DOCUMENT_APPENDED = "docs.document.appended"


type _ActionTool = CrmToolName | TicketingToolName | SupportToolName | KnowledgeToolName

_ACTION_EVENT_TYPES: dict[_ActionTool, _ActionEventType] = {
    CrmToolName.CREATE_CONTACT: _ActionEventType.CONTACT_CREATED,
    CrmToolName.UPDATE_CONTACT: _ActionEventType.CONTACT_UPDATED,
    CrmToolName.CREATE_DEAL: _ActionEventType.DEAL_CREATED,
    CrmToolName.UPDATE_DEAL: _ActionEventType.DEAL_UPDATED,
    CrmToolName.MOVE_DEAL: _ActionEventType.DEAL_STAGE_CHANGED,
    TicketingToolName.CREATE: _ActionEventType.ISSUE_CREATED,
    TicketingToolName.UPDATE: _ActionEventType.ISSUE_UPDATED,
    TicketingToolName.ASSIGN: _ActionEventType.ISSUE_UPDATED,
    TicketingToolName.ADD_LABEL: _ActionEventType.ISSUE_UPDATED,
    TicketingToolName.REMOVE_LABEL: _ActionEventType.ISSUE_UPDATED,
    TicketingToolName.LINK: _ActionEventType.ISSUE_UPDATED,
    TicketingToolName.TRANSITION: _ActionEventType.ISSUE_TRANSITIONED,
    TicketingToolName.COMMENT: _ActionEventType.ISSUE_COMMENTED,
    SupportToolName.OPEN_TICKET: _ActionEventType.TICKET_OPENED,
    SupportToolName.UPDATE_TICKET: _ActionEventType.TICKET_UPDATED,
    SupportToolName.ASSIGN_TICKET: _ActionEventType.TICKET_ASSIGNED,
    SupportToolName.REPLY: _ActionEventType.TICKET_REPLIED,
    SupportToolName.ADD_NOTE: _ActionEventType.TICKET_NOTED,
    SupportToolName.CLOSE_TICKET: _ActionEventType.TICKET_CLOSED,
    SupportToolName.ADD_TAG: _ActionEventType.TICKET_UPDATED,
    SupportToolName.REMOVE_TAG: _ActionEventType.TICKET_UPDATED,
    KnowledgeToolName.CREATE: _ActionEventType.DOCUMENT_CREATED,
    KnowledgeToolName.UPDATE: _ActionEventType.DOCUMENT_UPDATED,
    KnowledgeToolName.APPEND: _ActionEventType.DOCUMENT_APPENDED,
}


_ACTION_TOOLS_BY_NAME: dict[str, _ActionTool] = {
    tool.value: tool for tool in _ACTION_EVENT_TYPES
}


class _ActionPayload(BaseModel):
    """Allowlisted audit facts, never vendor content or arbitrary source fields."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    action: _ActionTool
    agent_id: UUID
    agent_revision: int
    agent_run_id: UUID
    command_id: UUID
    profile: SorProfile
    projection: SorProjectionDisposition
    result_record_id: UUID
    source_id: UUID
    source_revision: str | None
    tool_call_id: str
    vendor_key: str


class _ConnectionPayload(BaseModel):
    """Connection lifecycle facts without credentials or scopes."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    action: SorConnectionEventType
    connection_id: UUID
    connection_revision: int
    connector_id: UUID | None
    error_code: str | None
    profile: SorProfile
    source_id: UUID | None
    vendor_key: str


async def file_sor_action_event(
    session: AsyncSession,
    *,
    command: SorCommandModel,
    source: SorSourceModel,
    result_record_id: UUID,
    projection: SorProjectionDisposition,
    source_revision: str | None,
) -> UUID | None:
    """File one idempotent fact without source content or arbitrary custom values."""
    action = _ACTION_TOOLS_BY_NAME.get(command.profile_tool)
    if action is None:
        return None
    event_type = _ACTION_EVENT_TYPES[action]
    if command.finished_at is None:
        raise ValueError("A successful SOR command must have finished_at.")

    subject_id = command.target_record_id or result_record_id
    event_id = uuid5(
        NAMESPACE_URL,
        f"eylo:{event_type}:v1:{command.organization_id}:{command.id}",
    )
    await DurableEventService(session).file(
        envelope=DurableEventEnvelope(
            event_id=event_id,
            organization_id=command.organization_id,
            subject_type=SOR_RECORD_SUBJECT_TYPE,
            subject_id=subject_id,
            event_type=event_type,
            event_version=SOR_ACTION_EVENT_VERSION,
            occurred_at=command.finished_at,
            recorded_at=command.finished_at,
            correlation_id=command.agent_run_id,
            causation_id=command.id,
            payload=_ActionPayload(
                action=action,
                agent_id=command.agent_id,
                agent_revision=command.agent_revision,
                agent_run_id=command.agent_run_id,
                command_id=command.id,
                profile=command.profile,
                projection=projection,
                result_record_id=result_record_id,
                source_id=source.id,
                source_revision=source_revision,
                tool_call_id=command.tool_call_id,
                vendor_key=source.vendor_key,
            ).model_dump(mode="json"),
        ),
        consumer_names=(),
    )
    return event_id


async def file_sor_connection_event(
    session: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    connection_revision: int,
    event_sequence: str,
    event_type: SorConnectionEventType,
    occurred_at: datetime,
    profile: SorProfile,
    vendor_key: str,
    connector_id: UUID | None = None,
    source_id: UUID | None = None,
    error_code: str | None = None,
) -> UUID:
    """File one idempotent connection fact without scopes or credentials."""
    try:
        event_type = SorConnectionEventType(event_type)
    except ValueError as exc:
        raise ValueError("Unsupported SOR connection event type.") from exc
    if not event_sequence or len(event_sequence) > SOR_CONNECTION_EVENT_SEQUENCE_MAX:
        raise ValueError("SOR connection event sequence is invalid.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("SOR connection event time must include a timezone.")
    occurred_at = occurred_at.astimezone(timezone.utc)
    event_id = uuid5(
        NAMESPACE_URL,
        f"eylo:{event_type}:v1:{organization_id}:{connection_id}:{event_sequence}",
    )
    payload = _ConnectionPayload(
        action=event_type,
        connection_id=connection_id,
        connection_revision=connection_revision,
        connector_id=connector_id,
        error_code=error_code,
        profile=profile,
        source_id=source_id,
        vendor_key=vendor_key,
    ).model_dump(mode="json")
    await DurableEventService(session).file(
        envelope=DurableEventEnvelope(
            event_id=event_id,
            organization_id=organization_id,
            subject_type=SOR_CONNECTION_SUBJECT_TYPE,
            subject_id=connection_id,
            event_type=event_type,
            event_version=SOR_ACTION_EVENT_VERSION,
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            correlation_id=source_id or connector_id,
            causation_id=None,
            payload=payload,
        ),
        consumer_names=(),
    )
    return event_id


__all__ = ["file_sor_action_event", "file_sor_connection_event"]
