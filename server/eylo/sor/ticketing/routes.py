"""Authenticated ticketing-specific audit routes for organization members."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from eylo.common.database import start_transaction
from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user
from eylo.sor.runtime.catalog import get_sor_registry
from eylo.sor.shared.reads import SorReadNotFoundError
from eylo.sor.ticketing.audit import TicketingIssueAuditService
from eylo.sor.ticketing.schemas import (
    TicketingAuditAvailability,
    TicketingIssueAuditResponse,
    TicketingIssueCommentResponse,
)

router = APIRouter(
    prefix="/{organization_id}/sor/ticketing",
    tags=["systems-of-record"],
)


@router.get(
    "/issues/{record_id}/audit",
    response_model=TicketingIssueAuditResponse,
)
async def get_ticketing_issue_audit(
    organization_id: UUID,
    record_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
) -> TicketingIssueAuditResponse:
    """Return bounded comments and explicit history availability for one issue."""
    if current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        async with start_transaction(ro=True) as session:
            context = await TicketingIssueAuditService(session).read(
                organization_id=organization_id,
                record_id=record_id,
            )
            manifest = get_sor_registry().get_manifest(
                profile=context.source.profile,
                vendor_key=context.source.vendor_key,
            )
            comments_status = (
                TicketingAuditAvailability.UNSUPPORTED
                if not manifest.supports_comments
                else TicketingAuditAvailability.AVAILABLE
                if context.comments_selected
                else TicketingAuditAvailability.NOT_SELECTED
            )
            history_status = (
                TicketingAuditAvailability.NOT_SELECTED
                if manifest.supports_history
                else TicketingAuditAvailability.UNSUPPORTED
            )
            return TicketingIssueAuditResponse(
                comments_status=comments_status,
                comments_truncated=context.comments_truncated,
                comments=tuple(
                    TicketingIssueCommentResponse.model_validate(comment)
                    for comment in context.comments
                ),
                history_status=history_status,
            )
    except (KeyError, SorReadNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None


__all__ = ["router"]
