"""Authenticated Support-specific audit routes for organization members."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from eylo.common.database import start_transaction
from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.shared.reads import SorReadNotFoundError
from eylo.sor.support.audit import SupportTicketAuditService
from eylo.sor.support.schemas import (
    SupportAuditAvailability,
    SupportTicketAttachmentResponse,
    SupportTicketAuditResponse,
    SupportTicketMessageResponse,
    SupportTicketSlaMetricResponse,
)

router = APIRouter(
    prefix="/{organization_id}/sor/support",
    tags=["systems-of-record"],
)


def _availability(*, supported: bool, selected: bool) -> SupportAuditAvailability:
    if not supported:
        return SupportAuditAvailability.UNSUPPORTED
    if not selected:
        return SupportAuditAvailability.NOT_SELECTED
    return SupportAuditAvailability.AVAILABLE


@router.get(
    "/tickets/{record_id}/audit",
    response_model=SupportTicketAuditResponse,
)
async def get_support_ticket_audit(
    organization_id: UUID,
    record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> SupportTicketAuditResponse:
    """Return bounded chronology and explicit metadata availability for a ticket."""
    if current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        async with start_transaction(ro=True) as session:
            context = await SupportTicketAuditService(session).read(
                organization_id=organization_id,
                record_id=record_id,
            )
            manifest = get_sor_registry().get_manifest(
                profile=context.source.profile,
                vendor_key=context.source.vendor_key,
            )
            return SupportTicketAuditResponse(
                messages_status=_availability(
                    supported=manifest.supports_comments,
                    selected="message" in context.selected_entities,
                ),
                messages_truncated=context.messages_truncated,
                messages=tuple(
                    SupportTicketMessageResponse.model_validate(message)
                    for message in context.messages
                ),
                attachments_status=_availability(
                    supported=manifest.supports_attachments,
                    selected="attachment" in context.selected_entities,
                ),
                attachments_truncated=context.attachments_truncated,
                attachments=tuple(
                    SupportTicketAttachmentResponse.model_validate(attachment)
                    for attachment in context.attachments
                ),
                sla_metrics_status=_availability(
                    supported="sla_metric" in manifest.readable_entities,
                    selected="sla_metric" in context.selected_entities,
                ),
                sla_metrics_truncated=context.sla_metrics_truncated,
                sla_metrics=tuple(
                    SupportTicketSlaMetricResponse.model_validate(metric)
                    for metric in context.sla_metrics
                ),
            )
    except (KeyError, SorReadNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None


__all__ = ["router"]
