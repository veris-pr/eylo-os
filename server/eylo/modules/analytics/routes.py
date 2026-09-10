"""HTTP routes for the `analytics` domain."""

import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from eylo.modules.analytics.contracts import (
    AnalyticsAgentPoint,
    AnalyticsCountPoint,
    AnalyticsEntity,
    AnalyticsTimeSlice,
)
from eylo.modules.analytics.services import AnalyticsService
from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user

from .constants import APP_TAG

router = APIRouter(prefix="/{organization_id}/analytics", tags=[APP_TAG])


@router.get("/conversations/created-per-agent", response_model=list[AnalyticsAgentPoint])
async def get_conversations_created_per_agent(
    organization_id: UUID,
    current_user: CurrentUserSchema = Depends(get_current_user),
    startDate: datetime.datetime | None = None,
    endDate: datetime.datetime | None = None,
    timeslice: AnalyticsTimeSlice = AnalyticsTimeSlice.DAY,
) -> list[AnalyticsAgentPoint]:
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=403)
    return await AnalyticsService().conversations_created_per_agent(
        organization_id,
        start_date=startDate or datetime.datetime.min,
        end_date=endDate or datetime.datetime.max,
        timeslice=timeslice,
    )


@router.get("/{entity}/created", response_model=list[AnalyticsCountPoint])
async def get_entity_created(
    organization_id: UUID,
    entity: AnalyticsEntity,
    current_user: CurrentUserSchema = Depends(get_current_user),
    startDate: datetime.datetime | None = None,
    endDate: datetime.datetime | None = None,
    timeslice: AnalyticsTimeSlice = AnalyticsTimeSlice.DAY,
) -> list[AnalyticsCountPoint]:
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=403)
    return await _entity_created_between_dates(
        entity,
        organization_id,
        start_date=startDate or datetime.datetime.min,
        end_date=endDate or datetime.datetime.max,
        timeslice=timeslice,
    )


async def _entity_created_between_dates(
    entity: AnalyticsEntity,
    organization_id: UUID,
    start_date: datetime.datetime,
    end_date: datetime.datetime,
    timeslice: AnalyticsTimeSlice = AnalyticsTimeSlice.DAY,
) -> list[AnalyticsCountPoint]:
    if entity is AnalyticsEntity.CONVERSATIONS:
        return await AnalyticsService().conversations_created_between_dates(
            organization_id, start_date, end_date, timeslice
        )
    elif entity is AnalyticsEntity.CONTACTS:
        return await AnalyticsService().contacts_created_between_dates(
            organization_id, start_date, end_date, timeslice
        )
    elif entity is AnalyticsEntity.MESSAGES:
        return await AnalyticsService().messages_created_between_dates(
            organization_id, start_date, end_date, timeslice
        )
    elif entity is AnalyticsEntity.MEMBERS:
        return await AnalyticsService().members_created_between_dates(
            organization_id, start_date, end_date, timeslice
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid entity type")
