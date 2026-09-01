"""Canonical support projection policy independent of vendor payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eylo.sor.shared.contracts import SorProfile
from eylo.sor.shared.models import SorProfileRecordModel, SorRecordModel
from eylo.sor.shared.repositories import SorRepository
from eylo.sor.shared.services import SorProjectionError

from .contracts import (
    SupportAgent,
    SupportAttachment,
    SupportCustomer,
    SupportEntityKind,
    SupportInbox,
    SupportMessage,
    SupportMessageDirection,
    SupportMessageVisibility,
    SupportQueue,
    SupportSlaMetric,
    SupportSlaState,
    SupportTag,
    SupportTicket,
    SupportTicketState,
)
from .models import (
    SupportAgentModel,
    SupportAttachmentModel,
    SupportCustomerModel,
    SupportInboxModel,
    SupportMessageModel,
    SupportQueueModel,
    SupportSlaMetricModel,
    SupportTagModel,
    SupportTicketModel,
)

SupportRecordModel = TypeVar("SupportRecordModel", bound=SorProfileRecordModel)

_TICKET_STATUSES = frozenset(SupportTicketState)
_MESSAGE_VISIBILITIES = frozenset(SupportMessageVisibility)
_MESSAGE_DIRECTIONS = frozenset(SupportMessageDirection)
_SLA_STATES = frozenset(SupportSlaState)


class SupportProjectionService:
    """Persist typed support fields beside one exact shared source identity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.records = SorRepository(session)

    async def upsert_ticket(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        ticket: SupportTicket,
    ) -> SupportTicketModel:
        _validate_ticket(ticket)
        return await self._upsert(
            SupportTicketModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.TICKET,
            vendor_external_id=ticket.external_id,
            values={
                "subject": ticket.subject,
                "normalized_description": ticket.normalized_description,
                "requester_external_id": ticket.requester_external_id,
                "assignee_external_id": ticket.assignee_external_id,
                "group_external_id": ticket.group_external_id,
                "inbox_external_id": ticket.inbox_external_id,
                "native_status": ticket.native_status,
                "normalized_status": (
                    ticket.normalized_status.value
                    if ticket.normalized_status is not None
                    else None
                ),
                "priority": ticket.priority,
                "category": ticket.category,
                "channel": ticket.channel,
                "tag_external_ids": list(ticket.tag_external_ids),
                "first_response_at": ticket.first_response_at,
                "resolved_at": ticket.resolved_at,
                "closed_at": ticket.closed_at,
                "sla_state": ticket.sla_state.value if ticket.sla_state else None,
            },
            search_values=(
                ticket.subject,
                ticket.normalized_description,
                ticket.native_status,
                ticket.priority,
                ticket.category,
                *ticket.tag_external_ids,
            ),
        )

    async def upsert_customer(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        customer: SupportCustomer,
    ) -> SupportCustomerModel:
        _validate_customer(customer)
        return await self._upsert(
            SupportCustomerModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.CUSTOMER,
            vendor_external_id=customer.external_id,
            values={
                "name": customer.name,
                "primary_email": customer.primary_email,
                "primary_phone": customer.primary_phone,
                "company_external_id": customer.company_external_id,
                "active": customer.active,
            },
            search_values=(
                customer.name,
                customer.primary_email,
                customer.primary_phone,
            ),
        )

    async def upsert_agent(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        agent: SupportAgent,
    ) -> SupportAgentModel:
        _validate_agent(agent)
        return await self._upsert(
            SupportAgentModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.AGENT,
            vendor_external_id=agent.external_id,
            values={
                "name": agent.name,
                "primary_email": agent.primary_email,
                "active": agent.active,
                "assignable": agent.assignable,
                "avatar_url": agent.avatar_url,
            },
            search_values=(agent.name, agent.primary_email),
        )

    async def upsert_queue(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        queue: SupportQueue,
    ) -> SupportQueueModel:
        _validate_queue(queue)
        return await self._upsert(
            SupportQueueModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.QUEUE,
            vendor_external_id=queue.external_id,
            values={
                "name": queue.name,
                "description": queue.description,
                "active": queue.active,
            },
            search_values=(queue.name, queue.description),
        )

    async def upsert_inbox(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        inbox: SupportInbox,
    ) -> SupportInboxModel:
        _validate_inbox(inbox)
        return await self._upsert(
            SupportInboxModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.INBOX,
            vendor_external_id=inbox.external_id,
            values={"name": inbox.name, "kind": inbox.kind, "active": inbox.active},
            search_values=(inbox.name, inbox.kind),
        )

    async def upsert_message(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        message: SupportMessage,
    ) -> SupportMessageModel:
        _validate_message(message)
        return await self._upsert(
            SupportMessageModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.MESSAGE,
            vendor_external_id=message.external_id,
            values={
                "ticket_external_id": message.ticket_external_id,
                "visibility": message.visibility.value,
                "direction": (
                    message.direction.value if message.direction is not None else None
                ),
                "author_external_id": message.author_external_id,
                "normalized_text": message.normalized_text,
                "source_body": message.source_body,
                "body_format": message.body_format,
                "attachment_external_ids": list(message.attachment_external_ids),
                "source_created_at": message.created_at,
                "source_updated_at": message.updated_at,
            },
            search_values=(
                message.normalized_text,
                message.author_external_id,
                message.visibility,
            ),
        )

    async def upsert_tag(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        tag: SupportTag,
    ) -> SupportTagModel:
        _validate_tag(tag)
        return await self._upsert(
            SupportTagModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.TAG,
            vendor_external_id=tag.external_id,
            values={"name": tag.name},
            search_values=(tag.name,),
        )

    async def upsert_sla_metric(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        metric: SupportSlaMetric,
    ) -> SupportSlaMetricModel:
        _validate_sla_metric(metric)
        return await self._upsert(
            SupportSlaMetricModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.SLA_METRIC,
            vendor_external_id=metric.external_id,
            values={
                "ticket_external_id": metric.ticket_external_id,
                "metric": metric.metric,
                "value": metric.value,
                "unit": metric.unit,
                "native_state": metric.native_state,
                "normalized_state": (
                    metric.normalized_state.value
                    if metric.normalized_state is not None
                    else None
                ),
                "target_at": metric.target_at,
                "achieved_at": metric.achieved_at,
                "breached_at": metric.breached_at,
            },
            search_values=(metric.metric, metric.native_state, metric.normalized_state),
        )

    async def upsert_attachment(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        attachment: SupportAttachment,
    ) -> SupportAttachmentModel:
        _validate_attachment(attachment)
        return await self._upsert(
            SupportAttachmentModel,
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=SupportEntityKind.ATTACHMENT,
            vendor_external_id=attachment.external_id,
            values={
                "ticket_external_id": attachment.ticket_external_id,
                "message_external_id": attachment.message_external_id,
                "name": attachment.name,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "source_url": attachment.source_url,
            },
            search_values=(attachment.name, attachment.content_type),
        )

    async def _upsert(
        self,
        model: type[SupportRecordModel],
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: SupportEntityKind,
        vendor_external_id: str,
        values: dict[str, object],
        search_values: Sequence[str | None],
    ) -> SupportRecordModel:
        record = await self._require_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            entity_kind=entity_kind,
            vendor_external_id=vendor_external_id,
        )
        row = await self.session.scalar(
            select(model).where(
                model.organization_id == organization_id,
                model.source_id == source_id,
                model.record_id == record_id,
                model.deleted.is_(False),
            )
        )
        if row is None:
            row = model(
                organization_id=organization_id,
                source_id=source_id,
                record_id=record_id,
                profile=SorProfile.SUPPORT,
                canonical_entity_kind=entity_kind.value,
                **values,
            )
            self.session.add(row)
        else:
            for field_name, value in values.items():
                setattr(row, field_name, value)
        _update_search(record, *search_values)
        await self.session.flush()
        return row

    async def _require_record(
        self,
        *,
        organization_id: UUID,
        source_id: UUID,
        record_id: UUID,
        entity_kind: SupportEntityKind,
        vendor_external_id: str,
    ) -> SorRecordModel:
        record = await self.records.get_record(
            organization_id=organization_id,
            source_id=source_id,
            record_id=record_id,
            for_update=True,
        )
        if record is None:
            raise SorProjectionError("Canonical support source record not found.")
        if (
            record.profile is not SorProfile.SUPPORT
            or record.canonical_entity_kind != entity_kind.value
            or record.vendor_external_id != vendor_external_id
        ):
            raise SorProjectionError(
                "Support value does not match its canonical source identity."
            )
        return record


def _validate_ticket(ticket: SupportTicket) -> None:
    _required(ticket.external_id, maximum=512, field="ticket external ID")
    _optional(ticket.subject, maximum=1_000_000, field="ticket subject")
    _optional(
        ticket.normalized_description,
        maximum=1_000_000,
        field="ticket description",
    )
    for value, maximum, field_name in (
        (ticket.requester_external_id, 512, "ticket requester"),
        (ticket.assignee_external_id, 512, "ticket assignee"),
        (ticket.group_external_id, 512, "ticket queue"),
        (ticket.inbox_external_id, 512, "ticket inbox"),
        (ticket.native_status, 160, "ticket source status"),
        (ticket.priority, 96, "ticket priority"),
        (ticket.category, 160, "ticket category"),
        (ticket.channel, 160, "ticket channel"),
        (ticket.sla_state, 96, "ticket SLA state"),
        (ticket.source_url, 2_048, "ticket source URL"),
    ):
        _optional(value, maximum=maximum, field=field_name)
    _choice_optional(
        ticket.normalized_status,
        choices=_TICKET_STATUSES,
        field="ticket normalized status",
    )
    _identities(ticket.tag_external_ids, maximum_items=256, field="ticket tags")
    _aware_optional(ticket.first_response_at, field="ticket first response")
    _aware_optional(ticket.resolved_at, field="ticket resolution")
    _aware_optional(ticket.closed_at, field="ticket closure")
    _aware_optional(ticket.source_updated_at, field="ticket source update")
    _mapping(ticket.custom_fields, field="ticket custom fields")


def _validate_customer(customer: SupportCustomer) -> None:
    _required(customer.external_id, maximum=512, field="customer external ID")
    for value, maximum, field_name in (
        (customer.name, 1_000_000, "customer name"),
        (customer.primary_email, 1_024, "customer email"),
        (customer.primary_phone, 320, "customer phone"),
        (customer.company_external_id, 512, "customer company"),
        (customer.source_url, 2_048, "customer source URL"),
    ):
        _optional(value, maximum=maximum, field=field_name)
    _mapping(customer.custom_fields, field="customer custom fields")


def _validate_agent(agent: SupportAgent) -> None:
    _required(agent.external_id, maximum=512, field="Agent external ID")
    _required(agent.name, maximum=1_000_000, field="Agent name")
    _optional(agent.primary_email, maximum=1_024, field="Agent email")
    _optional(agent.avatar_url, maximum=2_048, field="Agent avatar URL")


def _validate_queue(queue: SupportQueue) -> None:
    _required(queue.external_id, maximum=512, field="queue external ID")
    _required(queue.name, maximum=1_000_000, field="queue name")
    _optional(queue.description, maximum=1_000_000, field="queue description")


def _validate_inbox(inbox: SupportInbox) -> None:
    _required(inbox.external_id, maximum=512, field="inbox external ID")
    _required(inbox.name, maximum=1_000_000, field="inbox name")
    _optional(inbox.kind, maximum=160, field="inbox kind")


def _validate_message(message: SupportMessage) -> None:
    _required(message.external_id, maximum=512, field="message external ID")
    _required(message.ticket_external_id, maximum=512, field="message ticket")
    _choice(
        message.visibility, choices=_MESSAGE_VISIBILITIES, field="message visibility"
    )
    _choice_optional(
        message.direction,
        choices=_MESSAGE_DIRECTIONS,
        field="message direction",
    )
    _optional(message.author_external_id, maximum=512, field="message author")
    _required(message.normalized_text, maximum=1_000_000, field="message text")
    _optional(message.body_format, maximum=96, field="message body format")
    _json_value(message.source_body, field="message source body")
    _identities(
        message.attachment_external_ids,
        maximum_items=256,
        field="message attachments",
    )
    _aware(message.created_at, field="message creation")
    _aware_optional(message.updated_at, field="message update")


def _validate_tag(tag: SupportTag) -> None:
    _required(tag.external_id, maximum=512, field="tag external ID")
    _required(tag.name, maximum=1_000_000, field="tag name")


def _validate_sla_metric(metric: SupportSlaMetric) -> None:
    _required(metric.external_id, maximum=512, field="SLA metric external ID")
    _required(metric.ticket_external_id, maximum=512, field="SLA metric ticket")
    _required(metric.metric, maximum=160, field="SLA metric name")
    if metric.value is not None and not _finite_decimal(metric.value):
        raise SorProjectionError("Support SLA metric value is invalid.")
    _optional(metric.unit, maximum=64, field="SLA metric unit")
    _optional(metric.native_state, maximum=160, field="SLA source state")
    _choice_optional(
        metric.normalized_state,
        choices=_SLA_STATES,
        field="SLA normalized state",
    )
    _aware_optional(metric.target_at, field="SLA target")
    _aware_optional(metric.achieved_at, field="SLA achievement")
    _aware_optional(metric.breached_at, field="SLA breach")


def _finite_decimal(value: Decimal) -> bool:
    return value.is_finite() and value.copy_abs() < Decimal("1e18")


def _validate_attachment(attachment: SupportAttachment) -> None:
    _required(attachment.external_id, maximum=512, field="attachment external ID")
    _required(attachment.ticket_external_id, maximum=512, field="attachment ticket")
    _optional(
        attachment.message_external_id,
        maximum=512,
        field="attachment message",
    )
    _required(attachment.name, maximum=1_000_000, field="attachment name")
    _optional(attachment.content_type, maximum=320, field="attachment content type")
    _optional(attachment.source_url, maximum=2_048, field="attachment source URL")
    if attachment.size_bytes is not None and not 0 <= attachment.size_bytes < 2**63:
        raise SorProjectionError(
            "Support attachment size is outside the supported range."
        )


def _required(value: str, *, maximum: int, field: str) -> None:
    if not value or len(value) > maximum:
        raise SorProjectionError(f"Support {field} is invalid.")


def _optional(value: str | None, *, maximum: int, field: str) -> None:
    if value is not None and len(value) > maximum:
        raise SorProjectionError(f"Support {field} is too large.")


def _choice(value: str, *, choices: frozenset[str], field: str) -> None:
    if value not in choices:
        raise SorProjectionError(f"Support {field} is invalid.")


def _choice_optional(
    value: str | None,
    *,
    choices: frozenset[str],
    field: str,
) -> None:
    if value is not None:
        _choice(value, choices=choices, field=field)


def _identities(values: Sequence[str], *, maximum_items: int, field: str) -> None:
    if (
        len(values) > maximum_items
        or len(values) != len(set(values))
        or any(not value or len(value) > 512 for value in values)
    ):
        raise SorProjectionError(f"Support {field} are invalid.")


def _aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SorProjectionError(f"Support {field} timestamp must be timezone-aware.")


def _aware_optional(value: datetime | None, *, field: str) -> None:
    if value is not None:
        _aware(value, field=field)


def _mapping(value: Mapping[str, object], *, field: str) -> None:
    if any(not isinstance(key, str) or not key for key in value):
        raise SorProjectionError(f"Support {field} are invalid.")


def _json_value(value: object | None, *, field: str) -> None:
    if value is not None and not isinstance(value, (dict, list, str)):
        raise SorProjectionError(f"Support {field} is invalid.")


def _update_search(record: SorRecordModel, *values: str | None) -> None:
    record.search_text = " ".join(value for value in values if value)[:1_000_000]
    record.search_vector = func.to_tsvector("simple", record.search_text)


__all__ = ["SupportProjectionService"]
