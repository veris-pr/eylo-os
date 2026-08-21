"""Public bounded webhook ingress for executable SOR vendor adapters."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Request, status
from pydantic import BaseModel

from eylo.sor.runtime.adapters import SorAdapterUnavailableError
from eylo.sor.runtime.webhooks import accept_sor_webhook
from eylo.sor.shared.contracts import (
    SorWebhookPayloadError,
    SorWebhookVerificationError,
)
from eylo.sor.shared.services import (
    SorConfigurationError,
    SorConflictError,
    SorNotFoundError,
)
from eylo.sor.shared.webhook_services import SOR_WEBHOOK_MAX_BODY_BYTES

router = APIRouter(prefix="/sor/webhooks", tags=["systems-of-record-webhooks"])

_ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/cloudevents+json",
    "application/x-www-form-urlencoded",
}


class SorWebhookAcceptedResponse(BaseModel):
    """Safe receipt identity returned after verified persistence."""

    receipt_id: UUID
    duplicate: bool


@router.post(
    "/{vendor_key}/{endpoint_token}",
    response_model=SorWebhookAcceptedResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_sor_webhook(
    request: Request,
    vendor_key: Annotated[
        str,
        Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$"),
    ],
    endpoint_token: Annotated[str, Path(min_length=32, max_length=256)],
) -> SorWebhookAcceptedResponse:
    """Verify raw bytes before recording a deduplicated durable receipt."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported SOR webhook content type.",
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook content length.",
            ) from None
        if declared_length < 0 or declared_length > SOR_WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="SOR webhook body is too large.",
            )
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > SOR_WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="SOR webhook body is too large.",
            )
    body = bytes(chunks)
    try:
        receipt_id, created = await accept_sor_webhook(
            vendor_key=vendor_key,
            endpoint_token=endpoint_token,
            headers=dict(request.headers),
            body=body,
        )
    except SorNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    except SorWebhookVerificationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SOR webhook verification failed.",
        ) from None
    except (SorWebhookPayloadError, SorConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from None
    except SorConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from None
    except SorAdapterUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SOR webhook source is temporarily unavailable.",
        ) from None
    return SorWebhookAcceptedResponse(receipt_id=receipt_id, duplicate=not created)


__all__ = ["router"]
