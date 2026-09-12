"""Authenticated outbound voice-call routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from eylo.modules.auth.schemas import CurrentUserSchema
from eylo.modules.auth.services.auth_service import get_current_user
from eylo.modules.telephony.constants import CALL_IDEMPOTENCY_KEY_MAX_LENGTH
from eylo.modules.telephony.schemas import OutboundCallRequest, OutboundCallResult
from eylo.modules.telephony.voice_controller import VoiceController

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice"])

controller = VoiceController()


@router.post("/outbound", response_model=OutboundCallResult)
async def outbound_call(
    body: OutboundCallRequest,
    current_user: Annotated[CurrentUserSchema, Depends(get_current_user)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=CALL_IDEMPOTENCY_KEY_MAX_LENGTH,
        ),
    ],
) -> OutboundCallResult:
    """File one idempotent outbound call under the authenticated organization."""
    return await controller.outbound_call(
        body,
        current_user.organization_id,
        idempotency_key,
    )
