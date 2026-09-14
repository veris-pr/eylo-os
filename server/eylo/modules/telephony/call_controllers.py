"""Controller for telephony call history operations."""

from uuid import UUID

from fastapi import HTTPException

from eylo.common.schemas import PaginationParams
from eylo.modules.telephony.schemas import (
    CallDirection,
    CallStatus,
    TelephonyCallApiResponseSchema,
    TelephonyCallsPaginated,
)
from eylo.modules.telephony.services import TelephonyCallService


class TelephonyCallController:
    def __init__(self) -> None:
        self.service = TelephonyCallService()

    async def get(
        self,
        call_id: UUID,
        organization_id: UUID,
    ) -> TelephonyCallApiResponseSchema:
        call = await self.service.get_by_organization(call_id, organization_id)
        if call is None:
            raise HTTPException(status_code=404, detail="Not found.")
        return TelephonyCallApiResponseSchema.model_validate(call)

    async def list(
        self,
        organization_id: UUID,
        pagination: PaginationParams,
        status: CallStatus | None = None,
        direction: CallDirection | None = None,
        campaign_id: UUID | None = None,
        conversation_id: UUID | None = None,
    ) -> TelephonyCallsPaginated:
        calls = await self.service.list_by_organization(
            organization_id=organization_id,
            limit=pagination.limit,
            offset=pagination.get_offset(),
            status=status,
            direction=direction,
            campaign_id=campaign_id,
            conversation_id=conversation_id,
        )
        total = await self.service.count_by_organization(
            organization_id,
            status=status,
            direction=direction,
            campaign_id=campaign_id,
            conversation_id=conversation_id,
        )
        return TelephonyCallsPaginated(
            data=[TelephonyCallApiResponseSchema.model_validate(c) for c in calls],
            total=total,
            limit=pagination.limit,
            page=pagination.page,
        )
