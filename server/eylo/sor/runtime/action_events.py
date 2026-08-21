"""File PII-safe organization-visible facts for successful Agent SOR actions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from eylo.events.durable.domain import DurableEventEnvelope
from eylo.events.durable.service import DurableEventService
from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorCommandModel, SorSourceModel

SOR_RECORD_SUBJECT_TYPE = "sor.record"
SOR_CONNECTION_SUBJECT_TYPE = "sor.connection"
SOR_ACTION_EVENT_VERSION = 1

_CONNECTION_EVENT_TYPES = frozenset(
    {
        "sor.connection.connected",
        "sor.connection.reauth_required",
        "sor.connection.revoked",
    }
)

_ACTION_EVENT_TYPES = {
    "crm_create_contact": "crm.contact.created",
    "crm_update_contact": "crm.contact.updated",
    "crm_create_deal": "crm.deal.created",
    "crm_update_deal": "crm.deal.updated",
    "crm_move_deal": "crm.deal.stage_changed",
    "issue_create": "issue.created",
    "issue_update": "issue.updated",
    "issue_assign": "issue.updated",
    "issue_add_label": "issue.updated",
    "issue_remove_label": "issue.updated",
    "issue_link": "issue.updated",
    "issue_transition": "issue.transitioned",
    "issue_comment": "issue.commented",
    "support_open_ticket": "support.ticket.opened",
    "support_update_ticket": "support.ticket.updated",
    "support_assign_ticket": "support.ticket.assigned",
    "support_reply": "support.ticket.replied",
    "support_add_note": "support.ticket.noted",
    "support_close_ticket": "support.ticket.closed",
    "support_add_tag": "support.ticket.updated",
    "support_remove_tag": "support.ticket.updated",
    "docs_create": "docs.document.created",
    "docs_update": "docs.document.updated",
    "docs_append": "docs.document.appended",
}


async def file_sor_action_event(
    session: AsyncSession,
    *,
    command: SorCommandModel,
    source: SorSourceModel,
    result_record_id: UUID,
    projection: str,
    source_revision: str | None,
) -> UUID | None:
    """File one idempotent fact without source content or arbitrary custom values."""
    event_type = _ACTION_EVENT_TYPES.get(command.profile_tool)
    if event_type is None:
        return None
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
            payload={
                "action": command.profile_tool,
                "agent_id": str(command.agent_id),
                "agent_revision": command.agent_revision,
                "agent_run_id": str(command.agent_run_id),
                "command_id": str(command.id),
                "profile": command.profile.value,
                "projection": projection,
                "result_record_id": str(result_record_id),
                "source_id": str(source.id),
                "source_revision": source_revision,
                "tool_call_id": command.tool_call_id,
                "vendor_key": source.vendor_key,
            },
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
    event_type: str,
    occurred_at: datetime,
    profile: SorProfile,
    vendor_key: str,
    connector_id: UUID | None = None,
    source_id: UUID | None = None,
    error_code: str | None = None,
) -> UUID:
    """File one idempotent connection fact without scopes or credentials."""
    if event_type not in _CONNECTION_EVENT_TYPES:
        raise ValueError("Unsupported SOR connection event type.")
    if not event_sequence or len(event_sequence) > 128:
        raise ValueError("SOR connection event sequence is invalid.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("SOR connection event time must include a timezone.")
    occurred_at = occurred_at.astimezone(timezone.utc)
    event_id = uuid5(
        NAMESPACE_URL,
        f"eylo:{event_type}:v1:{organization_id}:{connection_id}:{event_sequence}",
    )
    payload = {
        "action": event_type,
        "connection_id": str(connection_id),
        "connection_revision": connection_revision,
        "connector_id": str(connector_id) if connector_id is not None else None,
        "error_code": error_code,
        "profile": profile.value,
        "source_id": str(source_id) if source_id is not None else None,
        "vendor_key": vendor_key,
    }
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
